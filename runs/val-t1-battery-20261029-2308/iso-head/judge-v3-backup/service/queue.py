"""运行队列与 worker（CONTRACT §2.2 / §2.3）。

状态机：``queued → running → done | failed | timeout``。

* ``POST /api/runs`` 立刻返回 202 + ``queued``，真正的执行在这个 worker 线程里；
* **单用例 10 s**（题面 §5.4）：``Popen(..., start_new_session=True)`` 起 solver，超时
  ``killpg(SIGKILL)`` 杀**整个进程组**（solver 常自己再派生 ``judge eval`` 子进程，只杀
  直接子进程会留孤儿进程继续吃 CPU），该用例记 ``timeout``，其余用例继续；
* ``idempotency_key`` 命中 → 返回既有 ``run_id``，**不新增账本行**（含跨进程重启：启动
  时从账本回填 key→run_id）；
* 结束（终态）时把整次运行追加进账本，``fsync`` 之后才发布终态事件；
* 合法性判定**只调** ``judge.core``，这里不做任何题面公式。

solver 子进程约定（CONTRACT §2.2 B 式未细化，这里固定下来并写进文档）::

    <solver 命令> <cases/<case>.in> <runs/out/<run_id>/<case>.out>

命令原文整串记入账本 ``solver_cmd``（可复现硬要求）。若 solver 没写输出文件，则把它
的 stdout 当作输出；两者都没有则记该用例 ``failed``。
"""

from __future__ import annotations

import hashlib
import os
import queue as queue_module
import shlex
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from judge.core import ParseError, evaluate_detailed, parse_case

from .config import Config
from .ledger import Ledger
from .sse import EventBus

__all__ = [
    "CASE_PENDING",
    "CASE_RUNNING",
    "TERMINAL_STATES",
    "RunManager",
    "SubmitSpec",
    "utc_now",
]

TERMINAL_STATES = frozenset({"done", "failed", "timeout"})
#: ``active()`` 只算这两种状态（``queued`` / ``running``）；终态 run 仍可被 ``view()`` 读回。
ACTIVE_STATES = frozenset({"queued", "running"})
CASE_PENDING = "pending"
CASE_RUNNING = "running"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _shift(stamp: str, seconds: float) -> str:
    """把 ``YYYY-MM-DDTHH:MM:SSZ`` 往后推 ``seconds`` 秒（用于 deadline_at）。"""
    try:
        base = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:  # pragma: no cover - 自产时间戳不会坏
        return stamp
    return (base + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class SubmitSpec:
    """一次 ``POST /api/runs`` 的输入（A 式给 outputs，B 式给 solver，二选一）。"""

    version: str
    commit: str
    cases: list[str]
    solver_cmd: Optional[str] = None
    outputs: Optional[dict[str, str]] = None
    notes: str = ""
    idem: Optional[str] = None
    origin: str = "api"
    actor: str = "agent"

    @property
    def mode(self) -> str:
        return "solver" if self.solver_cmd else "outputs"


@dataclass
class _CaseRecord:
    """一个用例的结果（既进账本，也直接用于 HTTP 视图）。"""

    name: str
    state: str = CASE_PENDING
    ok: bool = False
    time: Optional[int] = None
    lb: Optional[int] = None
    solve_ms: int = 0
    output_sha256: Optional[str] = None
    grid: Optional[dict] = None
    K: Optional[int] = None
    psi: list = field(default_factory=list)
    groups: list = field(default_factory=list)
    engines: list = field(default_factory=list)
    ops_path: Optional[str] = None
    output_path: Optional[str] = None
    ops_total: int = 0
    errors: list = field(default_factory=list)

    def ledger_entry(self) -> dict:
        """账本 ``cases[]`` 的一项（CONTRACT §3）。"""
        return {
            "case": self.name,
            "state": self.state,
            "ok": self.ok,
            "time": self.time,
            "lb": self.lb,
            "solve_ms": self.solve_ms,
            "output_sha256": self.output_sha256,
            "grid": self.grid,
            "K": self.K,
            "psi": self.psi,
            "groups": self.groups,
            "engines": self.engines,
            "ops_path": self.ops_path,
            "output_path": self.output_path,
            "ops_total": self.ops_total,
            "errors": self.errors,
        }

    def detail(self, run_id: str) -> dict:
        """CONTRACT §2.4 的全部展示字段。"""
        return {
            "run_id": run_id,
            "case": self.name,
            "state": self.state,
            "ok": self.ok,
            "time": self.time,
            "lb": self.lb,
            "groups": self.groups,
            "engines": self.engines,
            "grid": self.grid,
            "K": self.K,
            "psi": self.psi,
            "errors": self.errors,
            "solve_ms": self.solve_ms,
            "output_sha256": self.output_sha256,
            "ops_total": self.ops_total,
            "ops_path": self.ops_path,
            "output_path": self.output_path,
        }


@dataclass
class _Run:
    run_id: str
    version: str
    commit: str
    cases: list[str]
    mode: str
    solver_cmd: Optional[str]
    outputs: Optional[dict[str, str]]
    notes: str
    idem: Optional[str]
    origin: str
    actor: str
    created_at: str
    state: str = "queued"
    started_at: Optional[str] = None
    deadline_at: Optional[str] = None
    finished_at: Optional[str] = None
    done: int = 0
    records: dict[str, _CaseRecord] = field(default_factory=dict)


def _error(category: str, message: str, **extra: object) -> dict:
    item: dict = {"category": category, "message": message, "t": None, "at": None}
    item.update(extra)
    return item


class RunManager:
    """队列 + worker + 账本写入 + 视图（线程安全）。"""

    def __init__(
        self,
        config: Config,
        ledger: Ledger,
        bus: EventBus,
        *,
        timeout: Optional[float] = None,
    ) -> None:
        self.config = config
        self.ledger = ledger
        self.bus = bus
        self.timeout = float(timeout if timeout is not None else config.case_timeout)
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._runs: dict[str, _Run] = {}
        self._order: list[str] = []
        self._idem: dict[str, str] = {}
        self._queue: queue_module.Queue = queue_module.Queue()
        self._worker = threading.Thread(target=self._loop, name="judge-worker", daemon=True)
        self._worker.start()
        self._restore_idempotency()

    # ------------------------------------------------------------------ #
    # 提交
    # ------------------------------------------------------------------ #
    def submit(self, spec: SubmitSpec) -> tuple[dict, bool]:
        """入队；返回 ``(run 视图, 是否新建)``。幂等命中时不新增账本行。"""
        with self._cond:
            if spec.idem:
                existing = self._idem.get(spec.idem)
                if existing is not None:
                    view = self._view_locked(existing)
                    if view is None:
                        row = self._row_for(existing)
                        view = self._view_from_row(row) if row is not None else None
                    if view is not None:
                        return view, False
            run_id = self._allocate_id_locked()
            run = _Run(
                run_id=run_id,
                version=spec.version,
                commit=spec.commit,
                cases=list(spec.cases),
                mode=spec.mode,
                solver_cmd=spec.solver_cmd,
                outputs=dict(spec.outputs) if spec.outputs is not None else None,
                notes=spec.notes,
                idem=spec.idem,
                origin=spec.origin,
                actor=spec.actor,
                created_at=utc_now(),
            )
            self._runs[run_id] = run
            self._order.append(run_id)
            if spec.idem:
                self._idem[spec.idem] = run_id
            self._queue.put(run_id)
            view = self._view_locked(run_id)
        self._publish("run.queued", run)
        assert view is not None
        return view, True

    def _allocate_id_locked(self) -> str:
        candidate = self.ledger.next_id()
        while candidate in self._runs:
            number = int(candidate.split("-")[1]) + 1
            candidate = f"r-{number:04d}"
        return candidate

    def _restore_idempotency(self) -> None:
        """启动时从账本回填 key→run_id（跨重启仍然幂等）。"""
        try:
            rows = self.ledger.rows()
        except OSError:  # pragma: no cover - 账本不可读时不阻塞启动
            return
        for row in rows:
            key = row.get("idem")
            run_id = row.get("run_id")
            if key and run_id:
                self._idem.setdefault(str(key), str(run_id))

    # ------------------------------------------------------------------ #
    # worker
    # ------------------------------------------------------------------ #
    def _loop(self) -> None:
        while True:
            run_id = self._queue.get()
            if run_id is None:
                self._queue.task_done()
                return
            try:
                self._execute(run_id)
            except Exception as exc:  # pragma: no cover - 兜底，不让 worker 死掉
                self._fail(run_id, exc)
            finally:
                self._queue.task_done()

    def _execute(self, run_id: str) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            run.state = "running"
            run.started_at = utc_now()
            run.deadline_at = _shift(run.started_at, self.timeout * max(1, len(run.cases)))
        self._publish("run.running", run)

        for case_name in run.cases:
            with self._lock:
                run.state = "running"
            self._publish("run.running", run)
            record = self._process_case(run, case_name)
            with self._lock:
                run.records[case_name] = record
                run.done += 1
                self._cond.notify_all()
            self._publish("run.running", run)

        with self._lock:
            final_state = self._final_state(run)
            run.finished_at = utc_now()
            row = self._ledger_row(run, state=final_state)
        self.ledger.append(row)  # flock + fsync：账本落盘之后终态才对读者可见
        with self._lock:
            run.state = final_state
            self._cond.notify_all()
        self._publish(f"run.{final_state}", run)

    def _final_state(self, run: _Run) -> str:
        records = list(run.records.values())
        if any(record.state == "failed" for record in records):
            return "failed"
        if any(record.state == "timeout" for record in records):
            return "timeout"
        return "done"

    def _fail(self, run_id: str, exc: BaseException) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            run.finished_at = utc_now()
            for name in run.cases:
                if name not in run.records:
                    record = _CaseRecord(name=name, state="failed")
                    record.errors = [_error("internal", f"worker 异常：{exc}")]
                    run.records[name] = record
                    run.done += 1
            row = self._ledger_row(run, state="failed")
        self.ledger.append(row)  # flock + fsync
        with self._lock:
            run.state = "failed"
            self._cond.notify_all()
        self._publish("run.failed", run)

    # ------------------------------------------------------------------ #
    # 单用例
    # ------------------------------------------------------------------ #
    def _process_case(self, run: _Run, case_name: str) -> _CaseRecord:
        record = _CaseRecord(name=case_name, state=CASE_RUNNING)
        case_path = self.config.case_input(case_name)
        if not case_path.is_file():
            record.state = "failed"
            record.errors = [_error("case", f"用例不存在：{case_path}")]
            return record

        text: Optional[str] = None
        if run.mode == "solver":
            text, record.solve_ms, timed_out, failure = self._run_solver(run, case_name, case_path)
            if timed_out:
                record.state = "timeout"
                record.errors = [
                    _error(
                        "timeout",
                        f"solver 超过 {self.timeout:g}s 上限，已 kill（题面 §5.4 / CONTRACT §2.2）",
                        limit_ms=int(self.timeout * 1000),
                    )
                ]
                return record
            if failure is not None:
                record.state = "failed"
                record.errors = [_error("solver", failure)]
                return record
        else:
            text = (run.outputs or {}).get(case_name)
            if text is None:
                record.state = "failed"
                record.errors = [_error("missing-output", f"outputs 里没有用例 {case_name} 的输出")]
                return record
            record.solve_ms = 0

        assert text is not None
        record.output_sha256 = sha256_text(text)
        record.output_path = self._persist_output(run, case_name, text)
        try:
            case = parse_case(case_path)
        except ParseError as exc:
            record.state = "failed"
            record.errors = [_error("parse-input", f"用例输入无法解析：{exc}")]
            return record

        try:
            result, ops = evaluate_detailed(case, text)
        except ParseError as exc:
            record.state = "done"
            record.ok = False
            record.errors = [_error("parse", f"输出解析失败：{exc}")]
            return record

        record.ok = bool(result.get("ok"))
        record.time = result.get("time")
        record.lb = result.get("lb")
        record.grid = result.get("grid")
        record.K = result.get("K")
        record.psi = result.get("psi") or []
        record.groups = result.get("groups") or []
        record.engines = result.get("engines") or []
        record.errors = result.get("errors") or []
        record.ops_path = self.ledger.write_ops(run.run_id, case_name, ops)
        record.ops_total = len(ops)
        record.state = "done"
        return record

    def _persist_output(self, run: _Run, case_name: str, text: str) -> str:
        """把该用例的输出原文存档到 ``runs/out/<run_id>/<case>.out``（编辑器预览用）。"""
        directory = self.config.runs_dir / "out" / run.run_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{case_name}.out"
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
        return self.ledger.relpath(path)

    def _run_solver(
        self, run: _Run, case_name: str, case_path: Path
    ) -> tuple[Optional[str], int, bool, Optional[str]]:
        """跑一次 solver 子进程，返回 ``(输出文本, 用时 ms, 是否超时, 失败原因)``。

        ``start_new_session=True`` 让 solver 自成**进程组**；超时用 ``killpg(SIGKILL)`` 整组
        杀掉——solver 内部常常再派生 ``python3 -m judge eval``，只 kill 直接子进程会留下
        孤儿进程继续吃 CPU，进而污染后续用例的 10 s 预算。
        """
        command = (run.solver_cmd or "").strip()
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            return None, 0, False, f"solver 命令无法解析：{exc}"
        if not argv:
            return None, 0, False, "solver 命令为空"

        out_dir = self.config.runs_dir / "out" / run.run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{case_name}.out"
        if out_path.exists():
            out_path.unlink()

        argv = argv + [str(case_path), str(out_path)]
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                argv,
                cwd=str(self.config.root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace",
                start_new_session=True,
            )
        except OSError as exc:
            return None, 0, False, f"无法执行 solver：{exc}"

        try:
            stdout, stderr = process.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            self._kill_process_group(process)
            try:
                process.communicate(timeout=5.0)
            except subprocess.TimeoutExpired:  # pragma: no cover - SIGKILL 之后不应发生
                pass
            return None, int((time.monotonic() - started) * 1000), True, None
        elapsed_ms = int((time.monotonic() - started) * 1000)

        if out_path.is_file():
            return out_path.read_text(encoding="utf-8"), elapsed_ms, False, None
        if stdout:
            return stdout, elapsed_ms, False, None
        detail = (stderr or "").strip().splitlines()
        tail = detail[-1] if detail else ""
        return (
            None,
            elapsed_ms,
            False,
            f"solver 退出码 {process.returncode}，且没有输出文件或标准输出"
            + (f"（stderr 末行：{tail[:300]}）" if tail else ""),
        )

    @staticmethod
    def _kill_process_group(process: "subprocess.Popen[str]") -> None:
        """超时后整组 kill（含 solver 派生的孙进程）；进程组已消失时退化 kill 直接子进程。"""
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                process.kill()
            except OSError:  # pragma: no cover - 已退出
                pass

    # ------------------------------------------------------------------ #
    # 账本行
    # ------------------------------------------------------------------ #
    def _ledger_row(self, run: _Run, *, state: Optional[str] = None) -> dict:
        return {
            "run_id": run.run_id,
            "created_at": run.created_at,
            "started_at": run.started_at,
            "deadline_at": run.deadline_at,
            "finished_at": run.finished_at,
            "state": state or run.state,
            "origin": run.origin,
            "actor": run.actor,
            "version": run.version,
            "commit": run.commit,
            "solver_cmd": run.solver_cmd,
            "mode": run.mode,
            "idem": run.idem,
            "notes": run.notes,
            "cases": [run.records[name].ledger_entry() for name in run.cases if name in run.records],
        }

    # ------------------------------------------------------------------ #
    # 视图（GET）
    # ------------------------------------------------------------------ #
    def view(self, run_id: str) -> Optional[dict]:
        with self._lock:
            view = self._view_locked(run_id)
        if view is not None:
            return view
        row = self._row_for(run_id)
        return self._view_from_row(row) if row is not None else None

    def _view_locked(self, run_id: str) -> Optional[dict]:
        run = self._runs.get(run_id)
        if run is None:
            return None
        finished = [name for name in run.cases if name in run.records]
        return {
            "run_id": run.run_id,
            "state": run.state,
            "done": run.done,
            "total": len(run.cases),
            "created_at": run.created_at,
            "started_at": run.started_at,
            "deadline_at": run.deadline_at,
            "finished_at": run.finished_at,
            "version": run.version,
            "commit": run.commit,
            "solver_cmd": run.solver_cmd,
            "mode": run.mode,
            "idem": run.idem,
            "notes": run.notes,
            "origin": run.origin,
            "actor": run.actor,
            "results": [
                {
                    "case": name,
                    "ok": run.records[name].ok,
                    "time": run.records[name].time,
                    "lb": run.records[name].lb,
                    "solve_ms": run.records[name].solve_ms,
                    "state": run.records[name].state,
                }
                for name in finished
            ],
            "case_states": {name: (run.records[name].state if name in run.records else "pending") for name in run.cases},
            "errors": [
                {"case": name, **error}
                for name in finished
                for error in run.records[name].errors
            ],
        }

    def _row_for(self, run_id: str) -> Optional[dict]:
        for row in self.ledger.rows():
            if str(row.get("run_id")) == str(run_id):
                return row
        return None

    def _view_from_row(self, row: dict) -> dict:
        cases = [item for item in (row.get("cases") or []) if isinstance(item, dict)]
        total = len(cases)
        deadline_at = row.get("deadline_at")
        if not deadline_at:
            # 老账本行没有 deadline_at：按 started_at + case_timeout × len(cases) 重算
            anchor = row.get("started_at") or row.get("created_at")
            if anchor:
                deadline_at = _shift(str(anchor), self.timeout * max(1, total))
        return {
            "run_id": row.get("run_id"),
            "state": row.get("state") or "done",
            "done": total,
            "total": total,
            "created_at": row.get("created_at"),
            "started_at": row.get("started_at"),
            "deadline_at": deadline_at,
            "finished_at": row.get("finished_at"),
            "version": row.get("version"),
            "commit": row.get("commit"),
            "solver_cmd": row.get("solver_cmd"),
            "mode": row.get("mode"),
            "idem": row.get("idem"),
            "notes": row.get("notes"),
            "origin": row.get("origin"),
            "actor": row.get("actor"),
            "results": [
                {
                    "case": item.get("case"),
                    "ok": bool(item.get("ok")),
                    "time": item.get("time"),
                    "lb": item.get("lb"),
                    "solve_ms": item.get("solve_ms"),
                    "state": item.get("state") or "done",
                }
                for item in cases
            ],
            "case_states": {str(item.get("case")): (item.get("state") or "done") for item in cases},
            "errors": [
                {"case": item.get("case"), **error}
                for item in cases
                for error in (item.get("errors") or [])
            ],
        }

    def case_view(self, run_id: str, case_name: str) -> tuple[int, dict]:
        """``GET /api/runs/{id}/cases/{case}``：``(HTTP 状态码, 响应体)``。"""
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                if case_name not in run.cases:
                    return 404, {"error": "case-not-found"}
                record = run.records.get(case_name)
                if record is None:
                    return 409, {"error": "not-ready", "state": run.state}
                return 200, record.detail(run_id)
        row = self._row_for(run_id)
        if row is None:
            return 404, {"error": "run-not-found"}
        for item in row.get("cases") or []:
            if isinstance(item, dict) and item.get("case") == case_name:
                return 200, {
                    "run_id": run_id,
                    "case": case_name,
                    "state": item.get("state") or "done",
                    "ok": bool(item.get("ok")),
                    "time": item.get("time"),
                    "lb": item.get("lb"),
                    "groups": item.get("groups") or [],
                    "engines": item.get("engines") or [],
                    "grid": item.get("grid"),
                    "K": item.get("K"),
                    "psi": item.get("psi") or [],
                    "errors": item.get("errors") or [],
                    "solve_ms": item.get("solve_ms"),
                    "output_sha256": item.get("output_sha256"),
                    "ops_total": item.get("ops_total") or 0,
                    "ops_path": item.get("ops_path"),
                    "output_path": item.get("output_path"),
                }
        return 404, {"error": "case-not-found"}

    def ops_view(
        self,
        run_id: str,
        case_name: str,
        *,
        since: Optional[int] = None,
        until: Optional[int] = None,
        group: Optional[int] = None,
        mb: Optional[int] = None,
        limit: int = 5000,
        cursor: int = 0,
    ) -> tuple[int, dict]:
        """``GET /api/runs/{id}/cases/{case}/ops``：切片视图。

        ``limit < 1`` 直接 ``400 bad-request``：空页若回 ``next_cursor == cursor``，客户端按
        ``next_cursor`` 循环会原地死循环（复核 F4）。
        """
        if limit < 1:
            return 400, {"error": "bad-request", "detail": "limit 必须 ≥ 1"}
        if cursor < 0:
            return 400, {"error": "bad-request", "detail": "cursor 必须 ≥ 0"}
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                if case_name not in run.cases:
                    return 404, {"error": "case-not-found"}
                record = run.records.get(case_name)
                if record is None:
                    return 409, {"error": "not-ready", "state": run.state}
                ops_path = record.ops_path
                if not ops_path:
                    return 200, {"total": 0, "returned": 0, "next_cursor": None, "ops": []}
                return 200, self.ledger.read_ops_slice(
                    ops_path, since=since, until=until, group=group, mb=mb, limit=limit, cursor=cursor
                )
        row = self._row_for(run_id)
        if row is None:
            return 404, {"error": "run-not-found"}
        for item in row.get("cases") or []:
            if isinstance(item, dict) and item.get("case") == case_name:
                ops_path = item.get("ops_path")
                if not ops_path:
                    return 200, {"total": 0, "returned": 0, "next_cursor": None, "ops": []}
                return 200, self.ledger.read_ops_slice(
                    str(ops_path), since=since, until=until, group=group, mb=mb, limit=limit, cursor=cursor
                )
        return 404, {"error": "case-not-found"}

    def output_view(self, run_id: str, case_name: str) -> tuple[int, dict]:
        """``GET /api/runs/{id}/cases/{case}/output``：该用例输出原文（UI 预览用）。"""
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                if case_name not in run.cases:
                    return 404, {"error": "case-not-found"}
                record = run.records.get(case_name)
                if record is None or not record.output_path:
                    return 409, {"error": "not-ready", "state": run.state}
                return self._read_output(record.output_path, case_name)
        row = self._row_for(run_id)
        if row is None:
            return 404, {"error": "run-not-found"}
        for item in row.get("cases") or []:
            if isinstance(item, dict) and item.get("case") == case_name:
                path = item.get("output_path")
                if not path:
                    return 404, {"error": "output-not-found"}
                return self._read_output(str(path), case_name)
        return 404, {"error": "case-not-found"}

    def _read_output(self, stored_path: str, case_name: str) -> tuple[int, dict]:
        path = self.ledger.resolve(stored_path)
        if not path.is_file():
            return 404, {"error": "output-not-found"}
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover - 磁盘问题
            return 500, {"error": "output-unreadable", "detail": str(exc)}
        return 200, {"case": case_name, "text": text, "path": stored_path}

    def active(self) -> list[dict]:
        """**活动中的** run（``queued`` / ``running``）；终态 run 不算活动。

        ``/api/health.active_runs``、``/api/meta.active_runs`` 与 SSE ``hello.runs`` 都用
        这个视图（CONTRACT §5.3「运行态可见」）。只过滤视图，不动 ``_runs``/``_order``，
        所以 ``view()`` / ``case_view()`` / ``ops_view()`` 仍能读回已完成的 run。
        """
        with self._lock:
            views: list[dict] = []
            for run_id in self._order:
                run = self._runs.get(run_id)
                if run is None or run.state not in ACTIVE_STATES:
                    continue
                view = self._view_locked(run_id)
                if view is not None:
                    views.append(view)
            return views

    def wait(self, run_id: str, timeout: float = 900.0) -> Optional[dict]:
        """阻塞到终态（或超时），返回运行视图。"""
        deadline = time.monotonic() + timeout
        while True:
            with self._cond:
                run = self._runs.get(run_id)
                if run is None:
                    view = self.view(run_id)
                    return view
                if run.state in TERMINAL_STATES:
                    return self._view_locked(run_id)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return self._view_locked(run_id)
                self._cond.wait(min(remaining, 0.25))

    # ------------------------------------------------------------------ #
    def _publish(self, kind: str, run: _Run) -> None:
        with self._lock:
            event = {
                "type": kind,
                "run_id": run.run_id,
                "state": run.state,
                "done": run.done,
                "total": len(run.cases),
                "version": run.version,
                "commit": run.commit,
                "at": utc_now(),
            }
        self.bus.publish(event)

    def shutdown(self) -> None:
        self._queue.put(None)
        self._worker.join(timeout=5.0)
