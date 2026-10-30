#!/usr/bin/env python3
"""端到端联调：`judge serve` → CLI 提交 solver 结果 → 账本 / 相对分与排名 / ops 切片 →
headless Chrome 渲染 `ui/` → 负例（非法解、超时、幂等）。

用法::

    python3 scripts/e2e.py                 # 全跑（loopback + UI + 负例 + 外部映射探测）
    python3 scripts/e2e.py --skip-ui       # 只跑后端链路
    python3 scripts/e2e.py --keep          # 保留临时目录（默认跑完删除）

约定：
* loopback 固定 ``127.0.0.1:3081``（可用 ``E2E_PORT`` 覆盖；端口被占则直接失败，避免测到别的服务）；
* 外部映射地址默认 ``http://123.60.231.190:4014``，可用 ``JUDGE_URL`` 覆盖；不可达时**明确 SKIP**；
* 仓库 ``runs/`` 不被写入：服务与 CLI 都用 ``JUDGE_RUNS_DIR`` 指向工程内临时目录，跑完删除；
* Chrome 的 ``--user-data-dir`` 只落在工程内临时目录，结束时删除。

退出码：0 = 全部断言通过（SKIP 不计失败）；1 = 有断言失败。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOOPBACK_HOST = "127.0.0.1"
LOOPBACK_PORT = int(os.environ.get("E2E_PORT", "3081"))
EXTERNAL_URL = os.environ.get("JUDGE_URL", "http://123.60.231.190:4014")
CASES = ["ex1", "ex2", "ex3", "ex4", "ex5", "ex6"]
# 2026-10-29 规则（V·P ≤ R + 共享专家可重叠）下的求解器结果
SOLVER_TIME = {"ex1": 560, "ex2": 4880, "ex3": 6072, "ex4": 3200, "ex5": 416, "ex6": 1696}
# 题面基线（2026-10 版：D 取消后 ex3 的题面值从 4000 变 7000）
# 题面样例基线（2026-10-29 版）
BASE = {"ex1": 560, "ex2": 4880, "ex3": 7000, "ex4": 3200, "ex5": 416, "ex6": 1696}

RESULTS: list[tuple[str, str, str]] = []  # (status, name, detail)


def record(status: str, name: str, detail: str = "") -> None:
    RESULTS.append((status, name, detail))
    print(f"{status:4} {name}" + (f" :: {detail}" if detail else ""), flush=True)


def ok(name: str, detail: str = "") -> None:
    record("PASS", name, detail)


def skip(name: str, detail: str = "") -> None:
    record("SKIP", name, detail)


def fail(name: str, detail: str = "") -> None:
    record("FAIL", name, detail)


def check(condition: bool, name: str, detail: str = "") -> bool:
    (ok if condition else fail)(name, detail)
    return condition


# --------------------------------------------------------------------------- #
# HTTP 小工具
# --------------------------------------------------------------------------- #
def http_json(url: str, method: str = "GET", payload: dict | None = None, timeout: float = 10.0):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return resp.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body)
        except Exception:
            return exc.code, {"raw": body[:200].decode("utf-8", "replace")}


def port_free(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.3)
        try:
            sock.connect((LOOPBACK_HOST, port))
            return False
        except OSError:
            return True


def wait_health(url: str, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status, body = http_json(f"{url}/api/health", timeout=1.0)
            if status == 200 and body and body.get("service") == "judge":
                return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


# --------------------------------------------------------------------------- #
# 子进程管理
# --------------------------------------------------------------------------- #
class Proc:
    """把子进程输出落到日志文件（避免 PIPE 写满阻塞服务），stop 时返回日志尾巴。"""

    def __init__(self, argv: list[str], env: dict | None = None, cwd: Path = REPO,
                 log_path: Path | None = None):
        self.log_path = log_path
        self.handle = open(log_path, "w", encoding="utf-8") if log_path else subprocess.DEVNULL
        self.proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=self.handle,
                                     stderr=subprocess.STDOUT, text=True)

    def stop(self) -> str:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        if self.log_path:
            self.handle.close()
            try:
                return self.log_path.read_text(encoding="utf-8", errors="replace")[-800:]
            except OSError:
                return ""
        return ""


def run_cli(args: list[str], env: dict, timeout: float = 180.0) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "judge", *args], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=timeout)


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MoE judge 端到端联调")
    parser.add_argument("--skip-ui", action="store_true", help="跳过 headless Chrome")
    parser.add_argument("--keep", action="store_true", help="保留临时目录（排障用）")
    args = parser.parse_args(argv)

    work = Path(tempfile.mkdtemp(prefix="judge-e2e-", dir=REPO))
    runs_dir = work / "runs"
    runs_dir.mkdir(parents=True)
    env = dict(os.environ)
    env["JUDGE_RUNS_DIR"] = str(runs_dir)
    env.pop("JUDGE_CASES_DIR", None)
    base = f"http://{LOOPBACK_HOST}:{LOOPBACK_PORT}"
    service: Proc | None = None
    static: Proc | None = None
    stamp = time.strftime("%H%M%S")

    try:
        # ---- 0. loopback 端口 ----
        if not port_free(LOOPBACK_PORT):
            fail(f"loopback {LOOPBACK_HOST}:{LOOPBACK_PORT} 被占用", "换个端口用 E2E_PORT=…")
            return 1
        service = Proc([sys.executable, "-m", "judge", "serve", "--port", str(LOOPBACK_PORT)], env=env, log_path=work / "serve.log")
        if not wait_health(base):
            fail("judge serve 启动 /api/health", (service.stop() or "")[-400:])
            return 1
        ok("judge serve 起在 loopback", base)

        # ---- 1. CLI 提交 solver 结果（6 例）----
        proc = run_cli(["run", "--version", f"v-e2e-{stamp}", "--commit", f"e2e-{stamp}",
                        "--cases", *CASES, "--outputs", "out", "--url", base, "--json",
                        "--wait-timeout", "120"], env)
        if proc.returncode != 0:
            fail("judge run 提交 6 例", f"exit={proc.returncode} {proc.stderr.strip()[:300]}")
            return 1
        view = json.loads(proc.stdout)
        run_id = view.get("run_id")
        ok("judge run 提交 6 例", f"run_id={run_id} state={view.get('state')}")

        times = {item["case"]: item.get("time") for item in view.get("results", [])}
        check(times == SOLVER_TIME and view.get("state") == "done",
              "run 终态 done 且 6 例 Time = solver 结果", str(times))

        # ---- 2. 账本落行 ----
        ledger = runs_dir / "ledger.jsonl"
        rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
        row = next((r for r in rows if r.get("run_id") == run_id), None)
        check(row is not None and row.get("state") == "done", "账本落行且 state=done",
              f"ledger_rows={len(rows)}")
        ledger_times = {c["case"]: c.get("time") for c in (row or {}).get("cases", [])}
        check(ledger_times == SOLVER_TIME, "账本 cases Time 与 solver 一致", str(ledger_times))
        check(all(c.get("output_sha256") for c in (row or {}).get("cases", [])),
              "账本每例都有 output_sha256")

        # ---- 3. /api/versions：相对分与排名 ----
        status, versions = http_json(f"{base}/api/versions")
        entry = next((v for v in versions or [] if v.get("run_id") == run_id), None)
        expect_score = round(math.exp(sum(math.log(times[c] / BASE[c]) for c in CASES) / len(CASES)), 6)
        check(status == 200 and entry is not None and entry.get("score") is not None
              and round(entry["score"], 6) == expect_score,
              "versions 相对分 = 各例 time/base 的几何平均",
              f"score={entry and entry.get('score')} 期望={expect_score:.6f}")
        check(entry is not None and entry.get("rank") == 1, "versions 排名", f"rank={entry and entry.get('rank')}")

        # ---- 4. ops 切片 ----
        status, page = http_json(f"{base}/api/runs/{run_id}/cases/ex1/ops?limit=5&cursor=0")
        check(status == 200 and page.get("total") == 20 and page.get("returned") == 5
              and page.get("next_cursor") == 5, "ops 切片（total=20, limit=5, next=5）",
              f"{status} {page and page.get('total')}/{page and page.get('returned')}")
        status, tail = http_json(f"{base}/api/runs/{run_id}/cases/ex1/ops?since=70&limit=20000")
        check(status == 200 and tail.get("total", 0) >= 1
              and all(o["t"] >= 70 for o in tail.get("ops", [])),
              "ops since 过滤可用（since 含）",
              f"total={tail and tail.get('total')} ts={sorted({o['t'] for o in (tail or {}).get('ops', [])})}")

        # ---- 5. 负例：非法解 ----
        illegal = (REPO / "cases/ex1.out").read_text(encoding="utf-8")
        illegal = illegal.replace("140 0:0:comb 1:0:gemm", "100 0:0:comb 1:0:gemm", 1)  # comb 早于 gemm 结束
        status, body = http_json(f"{base}/api/evaluate", "POST", {"case": "ex1", "output": illegal})
        check(status == 200 and body.get("ok") is False and body.get("time") is None,
              "负例·非法解 200 + ok:false + time:null", f"{status} ok={body and body.get('ok')}")

        # ---- 6. 负例：11s 假 solver 超时 ----
        slow = work / "slow_solver.py"
        slow.write_text("import time\ntime.sleep(11)\n", encoding="utf-8")
        t0 = time.monotonic()
        proc = run_cli(["run", "--version", f"v-timeout-{stamp}", "--commit", "e2e",
                        "--cases", "ex1", "--solver", f"{sys.executable} {slow}",
                        "--url", base, "--json", "--wait-timeout", "60"], env, timeout=120)
        elapsed = time.monotonic() - t0
        view = json.loads(proc.stdout) if proc.stdout.strip() else {}
        case_state = {c.get("case"): c.get("state") for c in view.get("results", [])}
        errors = [e for e in (view.get("errors") or []) if e.get("case") == "ex1"]
        check(proc.returncode == 4 and view.get("state") == "timeout"
              and case_state.get("ex1") == "timeout" and errors and errors[0].get("category") == "timeout",
              "负例·11s 假 solver 记 timeout", f"exit={proc.returncode} {case_state} {errors[:1]}")
        check(9.0 < elapsed < 13.0, "超时在 10s 附近终止", f"elapsed={elapsed:.2f}s")

        # ---- 7. 负例：同 idempotency_key 重复提交只落一行 ----
        payload = {"version": f"v-idem-{stamp}", "commit": "e2e", "cases": ["ex1"],
                   "outputs": {"ex1": (REPO / "out/ex1.out").read_text(encoding="utf-8")},
                   "idempotency_key": f"idem-{stamp}"}
        s1, b1 = http_json(f"{base}/api/runs", "POST", payload)
        s2, b2 = http_json(f"{base}/api/runs", "POST", payload)
        idem_id = b1.get("run_id")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            _st, view = http_json(f"{base}/api/runs/{idem_id}")
            if view and view.get("state") in ("done", "failed", "timeout"):
                break
            time.sleep(0.05)
        before = _ledger_ids(runs_dir)
        after = _ledger_ids(runs_dir)
        check(s1 == 202 and s2 == 202 and b1.get("run_id") == b2.get("run_id")
              and {b1.get("created"), b2.get("created")} == {True, False}
              and after.count(idem_id) == 1 and len(after) - len(before) == 0,
              "负例·同 idempotency_key 只落一行",
              f"{s1}/{s2} id={idem_id} created={b1.get('created')},{b2.get('created')} rows={len(after)} 唯一={len(set(after))}")

        # ---- 8. headless Chrome 渲染 ui/ ----
        if args.skip_ui:
            skip("headless Chrome dump-dom", "--skip-ui")
        else:
            chrome = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
            if chrome is None:
                skip("headless Chrome dump-dom", "chrome 未安装")
            else:
                static_port = _free_port()
                static = Proc([sys.executable, "-m", "http.server", str(static_port), "--directory", "ui"],
                              env=env, log_path=work / "static.log")
                if not _wait_port(static_port):
                    fail("静态托管 ui/", "http.server 未就绪")
                else:
                    profile = work / "chrome-profile"
                    url = f"http://{LOOPBACK_HOST}:{static_port}/?base={base}&sse=0"
                    try:
                        dump = subprocess.run(
                            [chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
                             "--disable-dev-shm-usage", "--no-first-run", "--virtual-time-budget=8000",
                             f"--user-data-dir={profile}", "--dump-dom", url],
                            capture_output=True, text=True, timeout=90,
                        ).stdout
                    except subprocess.TimeoutExpired:
                        dump = ""
                    has_row = f'data-run="{run_id}"' in dump
                    m = re.search(r'id="vtime"[^>]*>([^<]*)<', dump)
                    vtime = (m.group(1).strip() if m else "")
                    check(has_row, "Chrome dump-dom 含该 run 的版本行", f"run_id={run_id}")
                    check(vtime == str(SOLVER_TIME["ex1"]),
                          "Chrome dump-dom 的 #vtime = 该 run 的 ex1 Time",
                          f"vtime={vtime!r}")
                    ledger_m = re.search(r'id="st-ledger"[^>]*>([^<]*)<', dump)
                    run_m = re.search(r'id="st-run"[^>]*>([^<]*)<', dump)
                    check(ledger_m is not None and ledger_m.group(1).strip().isdigit()
                          and int(ledger_m.group(1)) >= 1 and run_m is not None
                          and re.fullmatch(r"r-\d{4}", run_m.group(1).strip()) is not None,
                          "UI 已连上后端（账本条数/最后 run 来自 API）",
                          f"st-ledger={ledger_m and ledger_m.group(1)} st-run={run_m and run_m.group(1)}")

        # ---- 9. 外部映射地址（不可达 → SKIP）----
        try:
            status, body = http_json(f"{EXTERNAL_URL}/api/health", timeout=2.0)
            if status == 200 and body and body.get("service") == "judge":
                ok("外部映射地址 /api/health", EXTERNAL_URL)
                status, versions = http_json(f"{EXTERNAL_URL}/api/versions", timeout=5.0)
                check(status == 200 and isinstance(versions, list) and
                      all(v.get("score") is None or isinstance(v.get("score"), (int, float)) for v in versions),
                      "外部映射地址 /api/versions 可用", f"{len(versions or [])} 个版本")
            else:
                skip("外部映射地址", f"{EXTERNAL_URL} 返回 {status}")
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            skip("外部映射地址", f"{EXTERNAL_URL} 不可达（{type(exc).__name__}）")

        failed = [item for item in RESULTS if item[0] == "FAIL"]
        print(f"\n合计：PASS {sum(1 for r in RESULTS if r[0]=='PASS')} / "
              f"FAIL {len(failed)} / SKIP {sum(1 for r in RESULTS if r[0]=='SKIP')}")
        return 0 if not failed else 1
    finally:
        if service is not None:
            service.stop()
        if static is not None:
            static.stop()
        if args.keep:
            print(f"保留临时目录：{work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


def _ledger_ids(runs_dir: Path) -> list[str]:
    rows = [json.loads(line) for line in runs_dir.joinpath("ledger.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    return [row.get("run_id") for row in rows]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind((LOOPBACK_HOST, 0))
        return sock.getsockname()[1]


def _wait_port(port: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((LOOPBACK_HOST, port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.05)
    return False


if __name__ == "__main__":
    sys.exit(main())
