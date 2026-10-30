"""t12 修复回归（服务层）：不启 HTTP 服务的快测。

覆盖 `docs/review-judge-service.md` 的五条 findings：

* **F5** `RunManager.active()` 只返回 ``queued`` / ``running``（health / meta / SSE hello
  都走它，所以调用方不用改）；已完成的 run 仍可用 ``view()`` / ``case_view()`` 读回。
* **F1** 超时用 ``start_new_session=True`` + ``killpg(SIGKILL)`` 整组杀：solver 派生的
  孙进程不会变成孤儿（沿用“超时 → 该用例 timeout、其余继续”的语义）。
* **F2** ``deadline_at`` 写进账本行，重启后回读非空（老行按 started_at 重算的兜底也测）。
* **F3** ops 列式缓存：同一份 ops 第二次读不再 ``json.loads``；文件变化（mtime/size）即失效。
* **F4** ``next_cursor`` 边界：空页是 ``None``，不会等于 ``cursor``；``limit=0`` 不出死循环。

复跑：``python3 -m unittest discover -s judge/tests -q``
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from judge.service import ledger as ledger_module
from judge.service.config import REPO_ROOT, Config
from judge.service.ledger import Ledger
from judge.service.queue import ACTIVE_STATES, RunManager, SubmitSpec
from judge.service.sse import EventBus


def _config(root: Path, *, timeout: float = 10.0) -> Config:
    """临时 ``runs/`` + 仓库自带的 ``cases/``。"""
    return Config(
        root=REPO_ROOT,
        cases_dir=REPO_ROOT / "cases",
        runs_dir=root / "runs",
        case_timeout=timeout,
    )


def _ex1_output() -> str:
    return (REPO_ROOT / "cases" / "ex1.out").read_text(encoding="utf-8")


class _ManagerCase(unittest.TestCase):
    """每个测试一个临时 ``runs/`` + 一个 ``RunManager``（不起 HTTP）。"""

    timeout = 10.0

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="judge-t12-"))
        self.config = _config(self.root, timeout=self.timeout)
        self.ledger = Ledger(self.config)
        self.manager = RunManager(self.config, self.ledger, EventBus(), timeout=self.timeout)

    def tearDown(self) -> None:
        try:
            self.manager.shutdown()
        finally:
            shutil.rmtree(self.root, ignore_errors=True)

    def submit_outputs(self, *, version: str = "v0") -> str:
        view, _created = self.manager.submit(
            SubmitSpec(
                version=version,
                commit="c0ffee1",
                cases=["ex1"],
                outputs={"ex1": _ex1_output()},
                origin="test",
                actor="test",
            )
        )
        return str(view["run_id"])

    def write_solver(self, name: str, body: str) -> str:
        path = self.root / name
        path.write_text(body, encoding="utf-8")
        return f"{sys.executable} {path}"


class ActiveRunsOnly(_ManagerCase):
    """F5：``active()`` 只算 queued/running。"""

    def test_finished_runs_are_not_active(self) -> None:
        run_ids = [self.submit_outputs(version=f"v{i}") for i in range(2)]
        for run_id in run_ids:
            view = self.manager.wait(run_id, timeout=30)
            self.assertEqual(view["state"], "done")
        self.assertEqual(self.manager.active(), [], "已完成的 run 不应出现在 active()")
        # 但读回能力保留
        for run_id in run_ids:
            view = self.manager.view(run_id)
            self.assertIsNotNone(view)
            self.assertEqual(view["state"], "done")
            status, detail = self.manager.case_view(run_id, "ex1")
            self.assertEqual(status, 200)
            self.assertTrue(detail["ok"])

    def test_running_run_is_active_with_progress(self) -> None:
        solver = self.write_solver(
            "slow.py",
            "import pathlib, shutil, sys, time\n"
            "time.sleep(0.6)\n"
            "shutil.copyfile(pathlib.Path(r'%s') / (pathlib.Path(sys.argv[1]).stem + '.out'), pathlib.Path(sys.argv[2]))\n"
            % (REPO_ROOT / "cases"),
        )
        view, _created = self.manager.submit(
            SubmitSpec(version="slow", commit="c0ffee1", cases=["ex1"], solver_cmd=solver)
        )
        deadline = time.monotonic() + 10
        seen_active = None
        while time.monotonic() < deadline:
            active = self.manager.active()
            if active:
                seen_active = active[0]
                break
            time.sleep(0.01)
        self.assertIsNotNone(seen_active, "运行中的 run 应该出现在 active() 里")
        self.assertIn(seen_active["state"], ACTIVE_STATES)
        self.assertEqual(seen_active["total"], 1)
        final = self.manager.wait(str(view["run_id"]), timeout=30)
        self.assertEqual(final["state"], "done")
        self.assertEqual(self.manager.active(), [])


class DeadlineAtPersisted(_ManagerCase):
    """F2：``deadline_at`` 落盘 + 重启回读。"""

    def test_ledger_row_has_deadline_and_survives_restart(self) -> None:
        run_id = self.submit_outputs()
        view = self.manager.wait(run_id, timeout=30)
        self.assertTrue(view["deadline_at"])
        rows = self.ledger.rows()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["deadline_at"], "账本行必须带 deadline_at")

        restarted = RunManager(self.config, Ledger(self.config), EventBus(), timeout=self.timeout)
        try:
            again = restarted.view(run_id)
        finally:
            restarted.shutdown()
        self.assertIsNotNone(again)
        self.assertEqual(again["deadline_at"], rows[0]["deadline_at"])

    def test_old_row_without_deadline_is_recomputed(self) -> None:
        view = self.manager._view_from_row(
            {
                "run_id": "r-9999",
                "started_at": "2026-10-20T04:00:00Z",
                "cases": [{"case": "ex1"}],
            }
        )
        self.assertTrue(view["deadline_at"])
        self.assertEqual(view["deadline_at"], "2026-10-20T04:00:10Z")


class OpsSliceBoundaries(unittest.TestCase):
    """F3 / F4：列式缓存与 ``next_cursor`` 边界。"""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="judge-t12-ops-"))
        self.config = _config(self.root)
        self.ledger = Ledger(self.config)
        self.ops = [
            {"t": index, "mb": index // 5, "l": index % 3, "op": "s" if index % 2 else "disp", "dur": index % 4, "g": index % 2}
            for index in range(25)
        ]
        self.stored = self.ledger.write_ops("r-0001", "ex1", self.ops)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _naive(self, *, since=None, until=None, group=None, mb=None, limit=5000, cursor=0) -> dict:
        selected = [
            op
            for op in self.ops
            if (since is None or op["t"] >= since)
            and (until is None or op["t"] < until)
            and (group is None or op["g"] == group)
            and (mb is None or op["mb"] == mb)
        ]
        page = selected[cursor : cursor + limit]
        return {
            "total": len(selected),
            "returned": len(page),
            "next_cursor": None
            if not page
            else (cursor + len(page) if cursor + len(page) < len(selected) else None),
            "ops": page,
        }

    def test_next_cursor_pages_through_all_ops(self) -> None:
        cursor, seen, pages = 0, 0, []
        while True:
            page = self.ledger.read_ops_slice(self.stored, limit=5, cursor=cursor)
            pages.append((page["returned"], page["next_cursor"]))
            seen += page["returned"]
            cursor = page["next_cursor"]
            if cursor is None:
                break
        self.assertEqual(seen, 25)
        self.assertEqual([item[1] for item in pages], [5, 10, 15, 20, None])

    def test_empty_page_has_null_next_cursor(self) -> None:
        for cursor in (25, 26, 999):
            with self.subTest(cursor=cursor):
                page = self.ledger.read_ops_slice(self.stored, limit=5, cursor=cursor)
                self.assertEqual(page["returned"], 0)
                self.assertIsNone(page["next_cursor"], "空页的 next_cursor 必须是 null（否则客户端死循环）")

    def test_zero_limit_never_returns_cursor_as_next(self) -> None:
        page = self.ledger.read_ops_slice(self.stored, limit=0, cursor=3)
        self.assertEqual(page["returned"], 0)
        self.assertIsNone(page["next_cursor"])

    def test_ops_view_rejects_non_positive_limit(self) -> None:
        """HTTP 层把 ``limit < 1`` 当请求错误（否则空页 + next_cursor==cursor 会死循环）。"""
        manager = RunManager(self.config, self.ledger, EventBus())
        try:
            view, _created = manager.submit(
                SubmitSpec(
                    version="v0",
                    commit="c0ffee1",
                    cases=["ex1"],
                    outputs={"ex1": _ex1_output()},
                )
            )
            run_id = str(view["run_id"])
            manager.wait(run_id, timeout=30)
            for kwargs in (dict(limit=0), dict(limit=-3)):
                with self.subTest(**kwargs):
                    status, payload = manager.ops_view(run_id, "ex1", **kwargs)
                    self.assertEqual(status, 400)
                    self.assertEqual(payload["error"], "bad-request")
            status, payload = manager.ops_view(run_id, "ex1", limit=5, cursor=999)
            self.assertEqual(status, 200)
            self.assertIsNone(payload["next_cursor"])
        finally:
            manager.shutdown()

    def test_filters_match_naive_reference(self) -> None:
        for kwargs in (
            dict(),
            dict(limit=7, cursor=3),
            dict(since=5, until=17, limit=4, cursor=1),
            dict(group=1, limit=3),
            dict(mb=4, limit=2),
            dict(since=4, group=0, mb=2),
            dict(until=1),
            dict(since=100),
        ):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(
                    self.ledger.read_ops_slice(self.stored, **kwargs),
                    self._naive(**kwargs),
                )

    def test_cache_is_reused_and_invalidated(self) -> None:
        calls = {"n": 0}
        real_loads = json.loads

        def counting_loads(*args, **kwargs):
            calls["n"] += 1
            return real_loads(*args, **kwargs)

        with mock.patch.object(ledger_module.json, "loads", counting_loads):
            first = self.ledger.read_ops_slice(self.stored, limit=5)
            parsed_once = calls["n"]
            second = self.ledger.read_ops_slice(self.stored, limit=5)
            after_cached = calls["n"]

        self.assertEqual(first, second)
        self.assertGreater(parsed_once, 20, "首请求应解析整份 ops")
        self.assertEqual(after_cached, parsed_once, "第二次读必须命中缓存，不再 json.loads")
        self.assertIn(str(Path(self.ledger.resolve(self.stored)).resolve()), self.ledger._ops_cache)

        # 直接改文件（不走 write_ops）→ mtime/size 变化应让缓存失效
        path = self.ledger.resolve(self.stored)
        path.write_text(
            "\n".join(json.dumps(op, separators=(",", ":")) for op in self.ops[:4]) + "\n",
            encoding="utf-8",
        )
        refreshed = self.ledger.read_ops_slice(self.stored, limit=10)
        self.assertEqual(refreshed["total"], 4)
        self.assertEqual(refreshed["returned"], 4)

    def test_cache_limit_is_bounded(self) -> None:
        for index in range(ledger_module.OPS_CACHE_LIMIT + 2):
            stored = self.ledger.write_ops(f"r-{index:04d}", "ex1", self.ops[:3])
            self.ledger.read_ops_slice(stored, limit=1)
        self.assertLessEqual(len(self.ledger._ops_cache), ledger_module.OPS_CACHE_LIMIT)


class SolverTimeoutKillsGroup(_ManagerCase):
    """F1：超时整组 kill（含 solver 派生的孙进程）。"""

    timeout = 0.5

    @staticmethod
    def _sleep_processes(duration: str) -> list[str]:
        result = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True)
        hits = []
        for line in result.stdout.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[0].isdigit() and parts[1].strip() in (
                f"/bin/sleep {duration}",
                f"sleep {duration}",
            ):
                hits.append(line.strip())
        return hits

    def test_timeout_kills_grandchildren(self) -> None:
        marker = "4242"
        solver = self.write_solver(
            "spawn.py",
            "import subprocess\n"
            f"subprocess.run(['/bin/sleep', '{marker}'])\n",
        )
        view, _created = self.manager.submit(
            SubmitSpec(version="spawn", commit="c0ffee1", cases=["ex1"], solver_cmd=solver)
        )
        started = time.monotonic()
        final = self.manager.wait(str(view["run_id"]), timeout=20)
        elapsed = time.monotonic() - started
        try:
            self.assertEqual(final["state"], "timeout")
            self.assertEqual(final["results"][0]["state"], "timeout")
            self.assertEqual([error["category"] for error in final["errors"]], ["timeout"])
            self.assertLess(elapsed, 5.0, "超时应在 ~0.5s 内结束（不是等 solver 自己退出）")
            time.sleep(0.3)  # 给 killpg 一点生效时间
            self.assertEqual(
                self._sleep_processes(marker),
                [],
                "solver 派生的孙进程必须在 killpg 后消失（否则会污染后续用例的预算）",
            )
        finally:
            for pid in self._sleep_processes(marker):
                try:
                    os.kill(int(pid.split()[0]), 9)
                except OSError:  # pragma: no cover
                    pass


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
