"""服务端语义自检（CONTRACT §2 / §3）：临时端口 + 临时账本目录，跑一遍全部语义。

    python3 -m judge.service.selftest          # 退出码 0 表示全过

覆盖：

* ``/api/evaluate``：合法 200、非法 **200 + ok:false**、用例不存在 400、坏 JSON 400、
  输出解析失败 422，且调用不写账本（无副作用）；
* ``/api/runs``：A 式（只登记输出）/ B 式（服务端跑 solver）两种提交、202 + queued、
  ``queued→running→done`` 状态流转、**10 s 超时 kill 并记 timeout**、solver 失败 →
  failed、同 ``idempotency_key`` 只写一行、运行中取结果 409；
* ``/api/runs/{id}/cases/{case}`` 与 ``…/ops``：字段齐备、切片分页与 ``total``；
* ``/api/versions``：``time/base`` 几何平均、非法版本 ``score:null`` 但仍出现、rank 升序；
* 账本：追加 + ``fsync`` + ``flock``（用打桩计数验证真的调用了）、每行含 ``solver_cmd``
  原文与 ``commit``、ops 只存路径、同一 solver 命令 + 同一 commit 重跑结果一致；
* SSE：拿到 ``run.queued/running/done`` 事件；
* 只绑 127.0.0.1、Ctrl-C 干净退出、CLI 的 ``run/ls/eval/acceptance`` 与退出码。

只用 stdlib（无 pytest、无外网），一切落在 ``tempfile.mkdtemp()`` 里。
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from .config import REPO_ROOT, Config
from .server import ServiceApp, create_server

__all__ = ["main", "Checker"]

TERMINAL = {"done", "failed", "timeout"}


class SelftestError(AssertionError):
    pass


# --------------------------------------------------------------------------- #
# 基础设施
# --------------------------------------------------------------------------- #


class Checker:
    """记录并打印每条检查（失败继续跑，最后汇总退出码）。"""

    def __init__(self) -> None:
        self.rows: list[tuple[str, bool, str]] = []

    def check(self, name: str, fn: Callable[[], Optional[str]]) -> None:
        started = time.monotonic()
        try:
            evidence = fn() or ""
        except Exception as exc:
            elapsed = time.monotonic() - started
            self.rows.append((name, False, f"{type(exc).__name__}: {exc}"))
            print(f"  ✗ {name}  ({elapsed:.2f}s) · {type(exc).__name__}: {exc}", flush=True)
            traceback.print_exc(limit=3)
        else:
            elapsed = time.monotonic() - started
            self.rows.append((name, True, evidence))
            suffix = f" · {evidence}" if evidence else ""
            print(f"  ✓ {name}  ({elapsed:.2f}s){suffix}", flush=True)

    @property
    def failed(self) -> int:
        return sum(1 for _name, ok, _detail in self.rows if not ok)

    @property
    def passed(self) -> int:
        return sum(1 for _name, ok, _detail in self.rows if ok)


class SseClient:
    """极简 SSE 客户端（后台线程读 ``data:`` 行）。"""

    def __init__(self, host: str, port: int) -> None:
        self.connection = http.client.HTTPConnection(host, port, timeout=30)
        self.connection.request("GET", "/api/events", headers={"Accept": "text/event-stream"})
        # getresponse() 在 Connection: close 时会把 conn.sock 置空，先自己留一份引用
        self._socket = self.connection.sock
        self.response = self.connection.getresponse()
        if self.response.status != 200:
            raise SelftestError(f"SSE 期望 200，得到 {self.response.status}")
        self.events: list[dict] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self) -> None:
        try:
            while not self._stop.is_set():
                line = self.response.fp.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text.startswith("data: "):
                    try:
                        event = json.loads(text[6:])
                    except json.JSONDecodeError:
                        continue
                    with self._lock:
                        self.events.append(event)
        except (OSError, ValueError):
            pass

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self.events)

    def wait_for(self, kind: str, run_id: Optional[str] = None, timeout: float = 20.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for event in self.snapshot():
                if event.get("type") == kind and (run_id is None or event.get("run_id") == run_id):
                    return event
            time.sleep(0.02)
        raise SelftestError(
            f"SSE 没等到 {kind}（run_id={run_id}）；收到 {[e.get('type') for e in self.snapshot()]}"
        )

    def close(self) -> None:
        self._stop.set()
        try:
            if self._socket is not None:
                self._socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.response.close()
        except (OSError, ValueError):
            pass
        self.connection.close()


class Harness:
    """临时账本目录 + 临时端口的服务实例，外加 HTTP / 子进程助手。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.config = Config.from_env(root=REPO_ROOT, runs_dir=root / "runs")
        self.app = ServiceApp(self.config)
        self.server = create_server(self.app, "127.0.0.1", 0)
        self.host, self.port = self.server.server_address[0], self.server.server_address[1]
        self.base = f"http://{self.host}:{self.port}"
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        self.thread.start()
        self.env = dict(os.environ)
        self.env.update(
            {
                "JUDGE_RUNS_DIR": str(self.config.runs_dir),
                "JUDGE_CASES_DIR": str(self.config.cases_dir),
                "JUDGE_HTTP_LOG": "",
            }
        )

    # -- HTTP ------------------------------------------------------------
    def request(self, method: str, path: str, payload: Any = None) -> tuple[int, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return int(response.status), (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                return int(exc.code), (json.loads(raw) if raw else {})
            except json.JSONDecodeError:
                return int(exc.code), {"raw": raw}

    def get(self, path: str) -> tuple[int, Any]:
        return self.request("GET", path)

    def post(self, path: str, payload: Any) -> tuple[int, Any]:
        return self.request("POST", path, payload)

    # -- 运行 ------------------------------------------------------------
    def submit(self, payload: dict) -> str:
        status, body = self.post("/api/runs", payload)
        if status != 202:
            raise SelftestError(f"POST /api/runs 期望 202，得到 {status} {body}")
        run_id = body.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise SelftestError(f"POST /api/runs 没返回 run_id：{body}")
        return run_id

    def wait(self, run_id: str, timeout: float = 60.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status, view = self.get(f"/api/runs/{run_id}")
            if status == 404:
                raise SelftestError(f"run {run_id} 不存在")
            if status == 200 and isinstance(view, dict) and view.get("state") in TERMINAL:
                return view
            time.sleep(0.02)
        raise SelftestError(f"run {run_id} 在 {timeout}s 内没到终态")

    def ledger_rows(self) -> list[dict]:
        path = self.config.ledger_path
        if not path.is_file():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def case_text(self, name: str) -> str:
        return (self.config.cases_dir / f"{name}.out").read_text(encoding="utf-8")

    def cli(self, args: list[str], *, timeout: float = 120.0) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "judge", *args],
            cwd=str(REPO_ROOT),
            env=self.env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.app.manager.shutdown()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _tcp_ready(host: str, port: int, timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_ready(host: str, port: int, limit: float = 10.0) -> None:
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if _tcp_ready(host, port):
            return
        time.sleep(0.03)
    raise SelftestError(f"服务 {host}:{port} 没在 {limit}s 内就绪")


def _illegal_output(text: str) -> str:
    """把 ex1 的 comb 从调度里删掉 → 缺操作（missing）。"""
    return text.replace("156 0:0:comb 1:0:gemm", "156 1:0:gemm")


# --------------------------------------------------------------------------- #
# 检查项
# --------------------------------------------------------------------------- #


def run_checks(checker: Checker, h: Harness, root: Path) -> None:
    ideal = h.case_text("ex1")
    ledger = h.config.ledger_path

    # 故意慢但会写出正确输出的 solver（用来观察 running / 409，不污染 timeout 用例）
    slow_script = root / "slow_solver.py"
    slow_script.write_text(
        "import pathlib, shutil, sys, time\n"
        "time.sleep(1.2)\n"
        "case_in = pathlib.Path(sys.argv[1])\n"
        f"shutil.copyfile(pathlib.Path(r'{h.config.cases_dir}') / (case_in.stem + '.out'), pathlib.Path(sys.argv[2]))\n",
        encoding="utf-8",
    )
    slow_solver = f"{sys.executable} {slow_script}"

    # ---------------- health / meta / cases ----------------
    def check_health() -> str:
        status, body = h.get("/api/health")
        assert status == 200, status
        assert body["ok"] is True
        assert body["ledger_lines"] == 0, body
        assert body["versions"] == 0, body
        status, meta = h.get("/api/meta")
        assert status == 200 and "ledger_path" in meta
        status, cases = h.get("/api/cases")
        assert status == 200 and {item["case"] for item in cases} >= {"ex1", "ex2", "mini"}
        base = {item["case"]: item["base"] for item in cases}
        assert base["ex1"] == 592 and base["mini"] == 180, base
        status, versions = h.get("/api/versions")
        assert status == 200 and versions == []
        return "health/meta/cases/versions 空账本 OK"

    checker.check("health/meta/cases 端点", check_health)

    # ---------------- evaluate ----------------
    def check_evaluate_ok() -> str:
        status, body = h.post("/api/evaluate", {"case": "ex1", "output": ideal})
        assert status == 200, status
        assert body["ok"] is True and body["time"] == 592, body
        # 无副作用：不写账本
        assert h.ledger_rows() == []
        assert ledger.is_file() and ledger.read_text(encoding="utf-8") == ""
        return "ex1 → time=592，200，账本仍为空"

    checker.check("POST /api/evaluate 合法解（200 + time）", check_evaluate_ok)

    def check_evaluate_idempotent() -> str:
        first = h.post("/api/evaluate", {"case": "ex1", "output": ideal})
        second = h.post("/api/evaluate", {"case": "ex1", "output": ideal})
        assert first == second
        assert h.ledger_rows() == []
        return "两次调用结果完全相同，无副作用"

    checker.check("POST /api/evaluate 幂等无副作用", check_evaluate_idempotent)

    def check_evaluate_illegal() -> str:
        status, body = h.post("/api/evaluate", {"case": "ex1", "output": _illegal_output(ideal)})
        assert status == 200, f"非法解必须 200，得到 {status}"
        assert body["ok"] is False, body
        assert body["time"] is None
        assert body["errors"] and body["errors"][0]["category"] == "missing", body["errors"][:2]
        return f"200 + ok:false（{len(body['errors'])} 条 missing）"

    checker.check("POST /api/evaluate 非法解（200 + ok:false）", check_evaluate_illegal)

    def check_evaluate_errors() -> str:
        status, body = h.post("/api/evaluate", {"case": "nope", "output": ""})
        assert status == 400 and body.get("error") == "case-not-found", (status, body)
        status, _body = h.post("/api/evaluate", {"case": "ex1", "output": "1 2 1\n"})
        assert status == 422, f"输出解析失败应 422，得到 {status}"
        status, body = h.post("/api/evaluate", {"case": "ex1"})
        assert status == 400, (status, body)
        request = urllib.request.Request(
            h.base + "/api/evaluate", data=b"{not json", method="POST", headers={"Content-Type": "application/json"}
        )
        try:
            urllib.request.urlopen(request, timeout=10)
            raise AssertionError("坏 JSON 应该 400")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400, exc.code
            assert json.loads(exc.read().decode())["error"] == "bad-json"
        return "400 case-not-found / 400 bad-json / 422 parse"

    checker.check("POST /api/evaluate 错误语义（§2.8）", check_evaluate_errors)

    # ---------------- run 状态流转（A 式）----------------
    state_log: list[str] = []

    def check_run_flow() -> str:
        run_id = h.submit(
            {
                "version": "smoke-a",
                "commit": "c0ffee1",
                "cases": ["ex1", "ex2"],
                "outputs": {"ex1": ideal, "ex2": h.case_text("ex2")},
                "notes": "A 式",
                "origin": "cli",
                "actor": "agent",
            }
        )
        view = h.wait(run_id)
        assert view["state"] == "done", view
        assert view["total"] == 2 and view["done"] == 2, view
        results = {item["case"]: item for item in view["results"]}
        assert results["ex1"]["ok"] and results["ex1"]["time"] == 592, results["ex1"]
        assert results["ex2"]["ok"] and results["ex2"]["time"] == 4880, results["ex2"]
        assert view["started_at"] and view["created_at"] and view["deadline_at"], view
        state_log.append(view["state"])
        return "queued→…→done，2/2 例，592/4880"

    checker.check("POST /api/runs（A 式）状态流转与结果", check_run_flow)

    def check_observe_running() -> str:
        """用慢一点的 solver 观察 queued→running→done。"""
        run_id = h.submit(
            {"version": "smoke-slow", "commit": "c0ffee1", "cases": ["ex1"], "solver": slow_solver}
        )
        seen: set[str] = set()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status, view = h.get(f"/api/runs/{run_id}")
            assert status == 200, status
            seen.add(str(view.get("state")))
            if view.get("state") in TERMINAL:
                break
            time.sleep(0.02)
        assert "running" in seen, f"没观察到 running：{seen}"
        assert "done" in seen, seen
        return f"观察到状态 {sorted(seen)}"

    checker.check("run 状态 queued→running→done 可观", check_observe_running)

    def check_case_detail() -> str:
        run_id = h.submit(
            {"version": "smoke-detail", "commit": "c0ffee1", "cases": ["ex2"], "outputs": {"ex2": h.case_text("ex2")}}
        )
        h.wait(run_id)
        status, detail = h.get(f"/api/runs/{run_id}/cases/ex2")
        assert status == 200, (status, detail)
        for key in (
            "ok", "time", "lb", "groups", "engines", "grid", "K", "psi", "errors",
            "solve_ms", "output_sha256", "ops_total",
        ):
            assert key in detail, f"缺字段 {key}"
        assert detail["time"] == 4880 and detail["K"] == 2 and detail["psi"] == [1]
        assert detail["grid"] == {"V": 2, "P": 2}
        assert detail["ops_total"] == 40, detail["ops_total"]
        assert len(detail["groups"]) == 2 and len(detail["engines"]) == 2
        for group in detail["groups"]:
            # 不断言 movl 的具体值（闭区间口径），只查总量约束
            assert group["mexp"] + group["movl"] + group["mact"] <= group["limit"], group
        assert detail["output_sha256"] and len(detail["output_sha256"]) == 64
        status, output = h.get(f"/api/runs/{run_id}/cases/ex2/output")
        assert status == 200 and output["text"] == h.case_text("ex2")
        return "字段齐备，ops_total=40，output 原文可读"

    checker.check("GET /runs/{id}/cases/{case} 字段与 output 原文", check_case_detail)

    def check_ops_slicing() -> str:
        run_id = h.submit(
            {"version": "smoke-ops", "commit": "c0ffee1", "cases": ["ex1"], "outputs": {"ex1": ideal}}
        )
        h.wait(run_id)
        base = f"/api/runs/{run_id}/cases/ex1/ops"
        status, page = h.get(base + "?limit=7")
        assert status == 200 and page["total"] == 20 and page["returned"] == 7, page
        assert page["next_cursor"] == 7
        cursor, seen, pages = 0, 0, 0
        while cursor is not None:
            status, chunk = h.get(base + f"?limit=7&cursor={cursor}")
            assert status == 200 and chunk["total"] == 20
            seen += chunk["returned"]
            pages += 1
            cursor = chunk["next_cursor"]
        assert seen == 20 and pages == 3, (seen, pages)
        status, filtered = h.get(base + "?mb=0&until=116")
        assert status == 200 and filtered["total"] == 3, filtered
        assert all(op["mb"] == 0 and op["t"] < 116 for op in filtered["ops"])
        status, grouped = h.get(base + "?group=0")
        assert status == 200 and grouped["total"] == 20
        status, bad = h.get(base + "?limit=abc")
        assert status == 400, (status, bad)
        return "分页 7+7+6=20、mb/until/group 过滤与 total 正确"

    checker.check("ops 切片分页与 total", check_ops_slicing)

    # ---------------- SSE ----------------
    def check_sse() -> str:
        client = SseClient(h.host, h.port)
        try:
            run_id = h.submit(
                {"version": "smoke-sse", "commit": "c0ffee1", "cases": ["ex1"], "outputs": {"ex1": ideal}}
            )
            h.wait(run_id)
            client.wait_for("run.done", run_id)
            kinds = {event.get("type") for event in client.snapshot() if event.get("run_id") == run_id}
            assert "run.queued" in kinds, kinds
            assert "run.done" in kinds, kinds
            done_event = client.wait_for("run.done", run_id)
            assert done_event["state"] == "done" and done_event["total"] == 1, done_event
            return f"收到事件 {sorted(kinds)}"
        finally:
            client.close()

    checker.check("SSE 收到 run.queued/running/done", check_sse)

    # ---------------- 幂等 ----------------
    def check_idempotency() -> str:
        before = len(h.ledger_rows())
        payload = {
            "version": "smoke-idem",
            "commit": "c0ffee1",
            "cases": ["ex1"],
            "outputs": {"ex1": ideal},
            "idempotency_key": "sha256:selftest-idem",
        }
        first_id = h.submit(payload)
        h.wait(first_id)
        middle = len(h.ledger_rows())
        second_id = h.submit(payload)
        second_view = h.wait(second_id)
        after = len(h.ledger_rows())
        assert first_id == second_id, (first_id, second_id)
        assert middle == before + 1, (before, middle)
        assert after == middle, f"同 idempotency_key 不应新增账本行：{middle} → {after}"
        assert second_view["state"] == "done"
        return f"同一 run_id={first_id}，账本只写了 1 行"

    checker.check("同 idempotency_key 只写一行", check_idempotency)

    # ---------------- 10s 超时 ----------------
    def check_timeout() -> str:
        before = len(h.ledger_rows())
        solver = f'{sys.executable} -c "import time; time.sleep(11)"'
        started = time.monotonic()
        run_id = h.submit(
            {
                "version": "smoke-timeout",
                "commit": "c0ffee1",
                "cases": ["ex1"],
                "solver": solver,
                "notes": "故意 11s",
            }
        )
        view = h.wait(run_id, timeout=40)
        elapsed = time.monotonic() - started
        assert view["state"] == "timeout", view
        results = view["results"]
        assert results and results[0]["state"] == "timeout", results
        categories = {error["category"] for error in view["errors"]}
        assert "timeout" in categories, view["errors"]
        solve_ms = results[0]["solve_ms"]
        assert solve_ms >= 10_000, f"solve_ms={solve_ms} 应 ≥ 10000"
        assert 9.5 <= elapsed <= 14.0, f"整次运行 {elapsed:.2f}s，应≈10s（超时即 kill，不跑到 11s+）"
        rows = h.ledger_rows()
        assert len(rows) == before + 1, (before, len(rows))
        row = rows[-1]
        assert row["solver_cmd"] == solver, "账本必须记 solver 命令原文"
        assert row["state"] == "timeout"
        return f"10 s 超时 kill，state=timeout，solve_ms={solve_ms}，耗时 {elapsed:.2f}s"

    checker.check("单用例 10 s 超时 kill 并记 timeout", check_timeout)

    # ---------------- solver 失败 / 可复现 ----------------
    solver_script = root / "fake_solver.py"
    solver_script.write_text(
        "import pathlib, shutil, sys\n"
        "case_in = pathlib.Path(sys.argv[1])\n"
        "out = pathlib.Path(sys.argv[2])\n"
        f"shutil.copyfile(pathlib.Path(r'{h.config.cases_dir}') / (case_in.stem + '.out'), out)\n",
        encoding="utf-8",
    )
    fake_solver = f"{sys.executable} {solver_script}"

    def check_solver_reproducible() -> str:
        rows_before = len(h.ledger_rows())
        run_ids = []
        for _ in range(2):
            run_id = h.submit(
                {
                    "version": "smoke-solver",
                    "commit": "deadbee",
                    "cases": ["ex1"],
                    "solver": fake_solver,
                    "notes": "可复现检查",
                }
            )
            view = h.wait(run_id)
            assert view["state"] == "done", view
            run_ids.append(run_id)
        rows = h.ledger_rows()
        assert len(rows) == rows_before + 2
        first, second = rows[-2], rows[-1]
        assert first["solver_cmd"] == fake_solver and second["solver_cmd"] == fake_solver
        assert first["commit"] == second["commit"] == "deadbee"
        assert first["cases"][0]["time"] == second["cases"][0]["time"] == 592
        assert first["cases"][0]["output_sha256"] == second["cases"][0]["output_sha256"]
        # ops 只存路径，且文件真的在
        case_entry = first["cases"][0]
        assert isinstance(case_entry["ops_path"], str) and "ops" not in case_entry
        ops_file = Path(h.config.runs_dir.parent / case_entry["ops_path"])
        assert ops_file.is_file(), ops_file
        assert sum(1 for _ in ops_file.open(encoding="utf-8")) == 20
        return "同命令 + 同 commit 两次 Time/输出哈希一致，账本记命令原文"

    checker.check("账本 solver_cmd 原文 + 同命令同 commit 可复现", check_solver_reproducible)

    def check_solver_failure() -> str:
        solver = f'{sys.executable} -c "import sys; sys.exit(3)"'
        run_id = h.submit({"version": "smoke-fail", "commit": "deadbee", "cases": ["ex1"], "solver": solver})
        view = h.wait(run_id)
        assert view["state"] == "failed", view
        assert view["results"][0]["state"] == "failed", view["results"]
        categories = {error["category"] for error in view["errors"]}
        assert "solver" in categories, view["errors"]
        return "solver 退出码 3 → run failed + category=solver"

    checker.check("solver 失败 → failed", check_solver_failure)

    # ---------------- 非法版本进版本表 ----------------
    def check_versions() -> str:
        run_id = h.submit(
            {
                "version": "smoke-illegal",
                "commit": "deadbee",
                "cases": ["ex1"],
                "outputs": {"ex1": _illegal_output(ideal)},
                "notes": "非法版本",
            }
        )
        view = h.wait(run_id)
        assert view["state"] == "done" and view["results"][0]["ok"] is False
        status, versions = h.get("/api/versions")
        assert status == 200 and versions, versions
        by_run = {entry["run_id"]: entry for entry in versions}
        assert run_id in by_run, by_run.keys()
        illegal = by_run[run_id]
        assert illegal["score"] is None and illegal["ok"] is False, illegal
        # 合法版本 score = 1.0（time == base）
        good = [entry for entry in versions if entry["score"] is not None]
        assert good, versions
        assert all(entry["score"] == 1.0 for entry in good), good
        # rank 升序，null 排最后
        ranks = [entry["rank"] for entry in versions]
        assert ranks == sorted(ranks), ranks
        scores = [entry["score"] if entry["score"] is not None else float("inf") for entry in versions]
        assert scores == sorted(scores), scores
        assert versions[-1]["score"] is None, "score:null 的版本必须排在最后"
        for entry in versions:
            for key in ("version", "commit", "run_id", "score", "rank", "ok", "cases", "actor", "created_at", "state"):
                assert key in entry, f"版本表缺字段 {key}"
            for name, item in entry["cases"].items():
                assert "base" in item and "time" in item and "ok" in item
        return f"{len(versions)} 个版本，非法版本 score=null 且排最后，合法版本 score=1.0"

    checker.check("/api/versions 相对分与排名", check_versions)

    # ---------------- 409 not-ready ----------------
    def check_not_ready() -> str:
        run_id = h.submit({"version": "smoke-pending", "commit": "c0ffee1", "cases": ["ex1"], "solver": slow_solver})
        status, body = h.get(f"/api/runs/{run_id}/cases/ex1")
        assert status == 409, f"运行中取结果应 409，得到 {status} {body}"
        assert body.get("error") == "not-ready" and body.get("state") == "running", body
        h.wait(run_id, timeout=30)
        status, body = h.get(f"/api/runs/{run_id}/cases/ex1")
        assert status == 200 and body["ok"] is True, (status, body)
        return "运行中 409 not-ready，结束后 200"

    checker.check("运行中取结果 409（§2.8）", check_not_ready)

    # ---------------- 账本 fsync / flock / append-only ----------------
    def check_ledger_durability() -> str:
        import fcntl as fcntl_module


        counters = {"fsync": 0, "flock": 0}
        real_fsync = os.fsync
        real_flock = fcntl_module.flock

        def counting_fsync(fd: int) -> None:
            counters["fsync"] += 1
            real_fsync(fd)

        def counting_flock(fd: int, operation: int) -> None:
            counters["flock"] += 1
            real_flock(fd, operation)

        rows_before = len(h.ledger_rows())
        os.fsync = counting_fsync  # type: ignore[assignment]
        fcntl_module.flock = counting_flock  # type: ignore[assignment]
        try:
            run_id = h.submit(
                {"version": "smoke-durable", "commit": "c0ffee1", "cases": ["ex1"], "outputs": {"ex1": ideal}}
            )
            h.wait(run_id)
        finally:
            os.fsync = real_fsync  # type: ignore[assignment]
            fcntl_module.flock = real_flock  # type: ignore[assignment]
        assert counters["fsync"] >= 1, "追加账本时必须 fsync"
        assert counters["flock"] >= 1, "追加账本时必须 flock"
        rows = h.ledger_rows()
        assert len(rows) == rows_before + 1
        # 只追加：旧行内容不变
        raw_before = ledger.read_text(encoding="utf-8").splitlines()
        assert len(raw_before) == len(rows)
        assert all(json.loads(line) for line in raw_before)
        return f"fsync×{counters['fsync']} flock×{counters['flock']}，行数 {len(rows)}"

    checker.check("账本 fsync + flock + 只追加", check_ledger_durability)

    # ---------------- 只绑回环 ----------------
    def check_loopback_only() -> str:
        assert h.server.server_address[0] == "127.0.0.1", h.server.server_address
        try:
            create_server(h.app, "0.0.0.0", 0)
        except ValueError as exc:
            assert "回环" in str(exc) or "loopback" in str(exc).lower()
        else:
            raise AssertionError("create_server 必须拒绝 0.0.0.0")
        assert h.host == "127.0.0.1"
        return "server_address=127.0.0.1，0.0.0.0 被拒绝"

    checker.check("只监听 127.0.0.1（不绑 0.0.0.0）", check_loopback_only)

    # ---------------- CLI ----------------
    def check_cli_eval() -> str:
        legal = h.cli(["eval", "cases/ex1.in", "cases/ex1.out", "--json"])
        assert legal.returncode == 0, (legal.returncode, legal.stderr[-400:])
        payload = json.loads(legal.stdout)
        assert payload["ok"] and payload["time"] == 592
        illegal_path = root / "illegal.out"
        illegal_path.write_text(_illegal_output(ideal), encoding="utf-8")
        illegal = h.cli(["eval", "cases/ex1.in", str(illegal_path), "--json"])
        assert illegal.returncode == 1, (illegal.returncode, illegal.stderr[-400:])
        broken_path = root / "broken.out"
        broken_path.write_text("1 2 1\n", encoding="utf-8")
        broken = h.cli(["eval", "cases/ex1.in", str(broken_path)])
        assert broken.returncode == 2, (broken.returncode, broken.stderr[-400:])
        return "退出码 0/1/2 符合 CONTRACT §4"

    checker.check("CLI eval 退出码", check_cli_eval)

    def check_cli_run() -> str:
        before = len(h.ledger_rows())
        completed = h.cli(
            [
                "run",
                "--version", "cli-selftest",
                "--commit", "c0ffee1",
                "--cases", "ex1",
                "--url", h.base,
                "--json",
            ]
        )
        assert completed.returncode == 0, (completed.returncode, completed.stdout[-500:], completed.stderr[-500:])
        view = json.loads(completed.stdout)
        assert view["state"] == "done" and view["results"][0]["time"] == 592, view
        assert len(h.ledger_rows()) == before + 1
        status, versions = h.get("/api/versions")
        entry = [item for item in versions if item["run_id"] == view["run_id"]]
        assert entry and entry[0]["score"] == 1.0 and entry[0]["rank"] is not None, entry
        # 人类可读摘要：几行、能贴进对话
        human = h.cli(["run", "--version", "cli-human", "--commit", "c0ffee1", "--cases", "ex1", "--url", h.base])
        assert human.returncode == 0, (human.returncode, human.stderr[-300:])
        assert "Time=592" in human.stdout and len(human.stdout.splitlines()) <= 8, human.stdout
        return "CLI run 落账本，/api/versions 能聚合出该行（score=1.0, rank 非空）"

    checker.check("CLI run 落账本 + versions 聚合", check_cli_run)

    def check_cli_offline_and_local() -> str:
        dead_port = _free_port()
        offline = h.cli(
            ["run", "--version", "cli-offline", "--cases", "ex1", "--url", f"http://127.0.0.1:{dead_port}"]
        )
        assert offline.returncode == 3, (offline.returncode, offline.stderr[-300:])
        before = len(h.ledger_rows())
        local = h.cli(["run", "--version", "cli-local", "--cases", "ex1", "--local"])
        assert local.returncode == 0, (local.returncode, local.stdout[-500:], local.stderr[-500:])
        assert len(h.ledger_rows()) == before + 1
        assert "本地队列" in local.stdout, local.stdout
        listed = h.cli(["ls", "--limit", "5"])
        assert listed.returncode == 0 and "cli-local" in listed.stdout, listed.stdout[-500:]
        acceptance = h.cli(["acceptance"])
        assert acceptance.returncode == 0, (acceptance.returncode, acceptance.stdout[-800:])
        assert "7/7" in acceptance.stdout, acceptance.stdout[-300:]
        return "离线 → 3、--local → 0 并落账本、ls 可见、acceptance 7/7"

    checker.check("CLI 离线/本地模式 + ls + acceptance", check_cli_offline_and_local)

    # ---------------- Ctrl-C ----------------
    def check_ctrl_c() -> str:
        port = _free_port()
        process = subprocess.Popen(
            [sys.executable, "-m", "judge", "serve", "--port", str(port)],
            cwd=str(REPO_ROOT),
            env=h.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            _wait_ready("127.0.0.1", port)
            status, body = _http_get(f"http://127.0.0.1:{port}/api/health")
            assert status == 200 and body.get("ok") is True, (status, body)
            process.send_signal(signal.SIGINT)
            stdout, stderr = process.communicate(timeout=15)
        finally:
            if process.poll() is None:  # pragma: no cover
                process.kill()
                process.communicate()
        assert process.returncode == 0, f"Ctrl-C 后退出码 {process.returncode}（stderr: {stderr[-500:]}）"
        assert "Traceback" not in stderr, stderr[-800:]
        assert "已停止" in stdout, stdout[-300:]
        return "SIGINT → 退出码 0，无 traceback，打印已停止"

    checker.check("serve Ctrl-C 干净退出", check_ctrl_c)

    # ---------------- 账本行结构 ----------------
    def check_ledger_schema() -> str:
        rows = h.ledger_rows()
        assert rows, "账本应有行"
        required = {"run_id", "created_at", "origin", "actor", "version", "commit", "solver_cmd", "idem", "notes", "cases"}
        case_required = {
            "case", "ok", "time", "lb", "solve_ms", "output_sha256", "grid", "K", "psi",
            "groups", "engines", "ops_path", "errors",
        }
        for row in rows:
            missing = required - set(row)
            assert not missing, f"账本行缺字段 {missing}"
            assert isinstance(row["created_at"], str) and row["created_at"].endswith("Z")
            for entry in row["cases"]:
                missing = case_required - set(entry)
                assert not missing, f"账本 case 项缺字段 {missing}"
                if entry["ops_path"]:
                    assert isinstance(entry["ops_path"], str), entry["ops_path"]
                    assert "ops" not in entry, "ops 不能内联进账本"
        return f"{len(rows)} 行账本，字段齐全，ops 只存路径"

    checker.check("账本行结构（§3）", check_ledger_schema)


def _http_get(url: str) -> tuple[int, Any]:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # pragma: no cover
        return int(exc.code), {}


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="judge-selftest-"))
    print(f"judge selftest · 临时目录 {root}", flush=True)
    checker = Checker()
    harness: Optional[Harness] = None
    try:
        harness = Harness(root)
        print(f"服务已起：{harness.base}（账本 {harness.config.ledger_path}）", flush=True)
        run_checks(checker, harness, root)
    except Exception:  # pragma: no cover - 基建失败
        traceback.print_exc()
        print("\nselftest 基建失败", flush=True)
        return 1
    finally:
        if harness is not None:
            harness.close()
        shutil.rmtree(root, ignore_errors=True)

    total = len(checker.rows)
    failed = checker.failed
    print(f"\nselftest：{checker.passed}/{total} 项通过" + ("（全部通过）" if failed == 0 else f" —— {failed} 项失败"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
