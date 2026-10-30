"""HTTP 服务（CONTRACT §2）：stdlib ``http.server``，**只绑回环**。

路由
----
=========================================  ==================================
``POST /api/evaluate``                     纯评估（200 + ``ok``，非法解也是 200）
``POST /api/runs``                         入队（202 + ``run_id``，幂等）
``GET  /api/runs/{run_id}``                运行状态与进度
``GET  /api/runs/{run_id}/cases/{case}``   一个用例的全部展示字段
``GET  /api/runs/{run_id}/cases/{case}/ops``  ops 切片（``since/until/group/mb/limit/cursor``）
``GET  /api/versions``                     版本表（相对分几何平均 + 排名）
``GET  /api/events``                       SSE：``run.queued/running/done/failed/timeout``
``GET  /api/meta``                         服务地址/账本条数/最近一次 run（状态条用）
``GET  /api/cases``                        可用用例与基准值（跑批表单用）
=========================================  ==================================

错误语义严格按 CONTRACT §2.8：映射非法 → 200 + ``ok:false``；用例不存在 / JSON 坏 →
400；输出解析失败 → 422；运行中取结果 → 409。
"""

from __future__ import annotations

import json
import os
import queue as stdlib_queue
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlsplit

import judge
from judge.core import ParseError, evaluate, parse_case

from .config import Config, LOOPBACK_HOSTS
from .ledger import Ledger, compute_versions
from .queue import RunManager, SubmitSpec
from .sse import EventBus, format_sse

__all__ = ["ServiceApp", "JudgeHTTPServer", "create_server", "serve"]

#: 请求体上限（64 万条调度约 10 MB，留足余量）。
MAX_BODY_BYTES = 96 * 1024 * 1024

#: ops 单页上限（CONTRACT §2.5：必须支持切片，前端画不动全量）。
MAX_OPS_LIMIT = 20000
DEFAULT_OPS_LIMIT = 5000

RUN_RE = re.compile(r"^/api/runs/(?P<run>[A-Za-z0-9][A-Za-z0-9_.-]*)$")
CASE_RE = re.compile(r"^/api/runs/(?P<run>[A-Za-z0-9][A-Za-z0-9_.-]*)/cases/(?P<case>[A-Za-z0-9][A-Za-z0-9_.-]*)$")
OUTPUT_RE = re.compile(
    r"^/api/runs/(?P<run>[A-Za-z0-9][A-Za-z0-9_.-]*)/cases/(?P<case>[A-Za-z0-9][A-Za-z0-9_.-]*)/output$"
)
OPS_RE = re.compile(
    r"^/api/runs/(?P<run>[A-Za-z0-9][A-Za-z0-9_.-]*)/cases/(?P<case>[A-Za-z0-9][A-Za-z0-9_.-]*)/ops$"
)
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class _HttpError(Exception):
    """在 handler 内部抛出的“带状态码的响应”。"""

    def __init__(self, status: int, payload: dict) -> None:
        super().__init__(str(payload))
        self.status = status
        self.payload = payload


class ServiceApp:
    """服务进程的共享状态（路由层只做参数校验，语义都在这里与 core）。"""

    def __init__(self, config: Config, *, timeout: Optional[float] = None) -> None:
        self.config = config
        self.ledger = Ledger(config)
        self.bus = EventBus()
        self.manager = RunManager(config, self.ledger, self.bus, timeout=timeout)
        self.bases = self._load_bases()
        self.cases = config.available_cases()

    # -- 元数据 -----------------------------------------------------------
    def _load_bases(self) -> dict[str, int]:
        """基准值（``time/base`` 的 base）：以 ``cases/expected.json`` 为唯一出处。"""
        expected = self.config.cases_dir / "expected.json"
        data: Any = None
        if expected.is_file():
            try:
                data = json.loads(expected.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = None
        if not isinstance(data, dict):
            try:  # 兜底：核心自带的读取器（同一份文件）
                from judge.core.acceptance import load_expected

                data = load_expected()
            except Exception:
                return {}
        bases: dict[str, int] = {}
        for name, entry in data.items():
            if isinstance(entry, dict) and isinstance(entry.get("time"), int):
                bases[str(name)] = int(entry["time"])
        return bases

    def versions(self) -> list[dict]:
        return compute_versions(self.ledger.rows(), self.bases)

    def cases_payload(self) -> list[dict]:
        return [{"case": name, "base": self.bases.get(name)} for name in self.cases]

    def health(self) -> dict:
        """``GET /api/health``：状态条要的最小事实（不读文件的视图用）。"""
        rows = self.ledger.rows()
        return {
            "ok": True,
            "service": "judge",
            "version": judge.__version__,
            "ledger_lines": len(rows),
            "versions": len(compute_versions(rows, self.bases)),
            "sse_clients": self.bus.subscriber_count,
            "active_runs": len(self.manager.active()),
            "case_timeout_seconds": self.config.case_timeout,
        }

    def meta(self) -> dict:
        rows = self.ledger.rows()
        last = rows[-1] if rows else None
        active = self.manager.active()
        return {
            "service": "judge",
            "version": judge.__version__,
            "ledger_path": str(self.config.ledger_path),
            "runs_dir": str(self.config.runs_dir),
            "cases_dir": str(self.config.cases_dir),
            "ledger_lines": len(rows),
            "cases": self.cases,
            "active_runs": [
                {
                    "run_id": view["run_id"],
                    "state": view["state"],
                    "done": view["done"],
                    "total": view["total"],
                }
                for view in active
                if view is not None
            ],
            "last_run": (
                {
                    "run_id": last.get("run_id"),
                    "state": last.get("state"),
                    "version": last.get("version"),
                    "commit": last.get("commit"),
                    "created_at": last.get("created_at"),
                }
                if last
                else None
            ),
            "sse_subscribers": self.bus.subscriber_count,
            "case_timeout_seconds": self.config.case_timeout,
        }


class JudgeHTTPServer(ThreadingHTTPServer):
    """线程化 HTTP 服务（``daemon_threads`` 保证 Ctrl-C 能干净退出）。"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], app: ServiceApp) -> None:
        self.app = app
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = f"judge/{judge.__version__}"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = 60

    # -- 基础设施 ---------------------------------------------------------
    @property
    def app(self) -> ServiceApp:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        if os.environ.get("JUDGE_HTTP_LOG"):
            super().log_message(fmt, *args)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store")

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise _HttpError(400, {"error": "bad-request", "detail": "Content-Length 非法"}) from None
        if length <= 0:
            raise _HttpError(400, {"error": "bad-json", "detail": "请求体为空"})
        if length > MAX_BODY_BYTES:
            raise _HttpError(413, {"error": "too-large", "detail": f"请求体超过 {MAX_BODY_BYTES} 字节"})
        raw = self.rfile.read(length)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise _HttpError(400, {"error": "bad-json", "detail": "请求体不是 UTF-8"}) from None
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise _HttpError(400, {"error": "bad-json", "detail": str(exc)}) from None
        if not isinstance(payload, dict):
            raise _HttpError(400, {"error": "bad-request", "detail": "请求体必须是 JSON 对象"})
        return payload

    # -- 路由 -------------------------------------------------------------
    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self._cors()
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        path = unquote(urlsplit(self.path).path)
        try:
            if path == "/api/evaluate":
                return self._evaluate()
            if path == "/api/runs":
                return self._submit_run()
            raise _HttpError(404, {"error": "not-found", "detail": path})
        except _HttpError as exc:
            self._send_json(exc.status, exc.payload)

    def do_GET(self) -> None:  # noqa: N802
        parts = urlsplit(self.path)
        path = unquote(parts.path)
        query = parse_qs(parts.query, keep_blank_values=True)
        try:
            if path == "/api/events":
                return self._events()
            if path == "/api/versions":
                return self._send_json(200, self.app.versions())
            if path == "/api/meta":
                return self._send_json(200, self.app.meta())
            if path == "/api/health":
                return self._send_json(200, self.app.health())
            if path == "/api/cases":
                return self._send_json(200, self.app.cases_payload())
            match = OUTPUT_RE.match(path)
            if match:
                status, payload = self.app.manager.output_view(match.group("run"), match.group("case"))
                return self._send_json(status, payload)
            match = OPS_RE.match(path)
            if match:
                return self._ops(match.group("run"), match.group("case"), query)
            match = CASE_RE.match(path)
            if match:
                status, payload = self.app.manager.case_view(match.group("run"), match.group("case"))
                return self._send_json(status, payload)
            match = RUN_RE.match(path)
            if match:
                view = self.app.manager.view(match.group("run"))
                if view is None:
                    raise _HttpError(404, {"error": "run-not-found"})
                return self._send_json(200, view)
            if path == "/":
                return self._send_json(
                    200,
                    {
                        "service": "judge",
                        "version": judge.__version__,
                        "endpoints": [
                            "POST /api/evaluate",
                            "POST /api/runs",
                            "GET /api/runs/{run_id}",
                            "GET /api/runs/{run_id}/cases/{case}",
                            "GET /api/runs/{run_id}/cases/{case}/ops",
                            "GET /api/versions",
                            "GET /api/events",
                            "GET /api/health",
                            "GET /api/meta",
                            "GET /api/cases",
                            "GET /api/runs/{run_id}/cases/{case}/output",
                        ],
                    },
                )
            raise _HttpError(404, {"error": "not-found", "detail": path})
        except _HttpError as exc:
            self._send_json(exc.status, exc.payload)

    # -- POST /api/evaluate ----------------------------------------------
    def _evaluate(self) -> None:
        payload = self._json_body()
        case_name = payload.get("case")
        output = payload.get("output")
        if not isinstance(case_name, str) or not isinstance(output, str):
            raise _HttpError(
                400,
                {"error": "bad-request", "detail": "需要 {case: string, output: string}"},
            )
        case_path = self._case_path(case_name)
        try:
            case = parse_case(case_path)
        except ParseError as exc:
            raise _HttpError(422, {"error": "parse", "detail": f"用例输入：{exc}"}) from None
        try:
            result = evaluate(case, output)
        except ParseError as exc:
            raise _HttpError(422, {"error": "parse", "detail": str(exc)}) from None
        # 映射非法同样是 200 + ok:false（CONTRACT §2.8）
        self._send_json(200, result)

    def _case_path(self, case_name: str) -> Path:
        if not SAFE_NAME.match(case_name):
            raise _HttpError(400, {"error": "case-not-found", "case": case_name})
        path = self.app.config.case_input(case_name)
        if not path.is_file():
            raise _HttpError(400, {"error": "case-not-found", "case": case_name})
        return path

    # -- POST /api/runs ---------------------------------------------------
    def _submit_run(self) -> None:
        payload = self._json_body()
        version = payload.get("version")
        if not isinstance(version, str) or not version.strip():
            raise _HttpError(400, {"error": "bad-request", "detail": "需要 version: string"})
        commit = payload.get("commit")
        if commit is None:
            commit = "unknown"
        if not isinstance(commit, str):
            raise _HttpError(400, {"error": "bad-request", "detail": "commit 必须是 string"})

        cases = payload.get("cases")
        if not isinstance(cases, list) or not cases:
            raise _HttpError(400, {"error": "bad-request", "detail": "cases 必须是非空数组"})
        names: list[str] = []
        for name in cases:
            if not isinstance(name, str):
                raise _HttpError(400, {"error": "bad-request", "detail": "cases 的元素必须是 string"})
            self._case_path(name)  # 不存在 → 400 case-not-found
            names.append(name)
        if len(set(names)) != len(names):
            raise _HttpError(400, {"error": "bad-request", "detail": "cases 有重复项"})

        solver = payload.get("solver")
        outputs = payload.get("outputs")
        if solver is not None and not isinstance(solver, str):
            raise _HttpError(400, {"error": "bad-request", "detail": "solver 必须是 string"})
        if outputs is not None and not isinstance(outputs, dict):
            raise _HttpError(400, {"error": "bad-request", "detail": "outputs 必须是对象"})
        if bool(solver) == bool(outputs):
            raise _HttpError(
                400,
                {"error": "bad-request", "detail": "solver 与 outputs 必须二选一"},
            )
        if outputs is not None:
            for key, value in outputs.items():
                if not isinstance(value, str):
                    raise _HttpError(400, {"error": "bad-request", "detail": f"outputs[{key!r}] 必须是 string"})
            missing = [name for name in names if name not in outputs]
            if missing:
                raise _HttpError(
                    400,
                    {"error": "missing-output", "detail": f"outputs 缺少用例 {missing}"},
                )

        idem = payload.get("idempotency_key")
        if idem is None:
            idem = payload.get("idem")
        if idem is not None and not isinstance(idem, str):
            raise _HttpError(400, {"error": "bad-request", "detail": "idempotency_key 必须是 string"})
        notes = payload.get("notes") or ""
        origin = payload.get("origin") or "api"
        actor = payload.get("actor") or "agent"
        if not isinstance(notes, str) or not isinstance(origin, str) or not isinstance(actor, str):
            raise _HttpError(400, {"error": "bad-request", "detail": "notes/origin/actor 必须是 string"})

        spec = SubmitSpec(
            version=version,
            commit=commit,
            cases=names,
            solver_cmd=solver or None,
            outputs=dict(outputs) if outputs is not None else None,
            notes=notes,
            idem=idem or None,
            origin=origin,
            actor=actor,
        )
        view, created = self.app.manager.submit(spec)
        self._send_json(
            202,
            {"run_id": view["run_id"], "state": view["state"], "created": created, "total": view["total"]},
        )

    # -- GET /api/runs/…/ops ---------------------------------------------
    def _ops(self, run_id: str, case_name: str, query: dict[str, list[str]]) -> None:
        since = _int_param(query, "since")
        until = _int_param(query, "until")
        group = _int_param(query, "group")
        mb = _int_param(query, "mb")
        limit = _int_param(query, "limit", default=DEFAULT_OPS_LIMIT)
        cursor = _int_param(query, "cursor", default=0)
        assert limit is not None and cursor is not None
        limit = max(0, min(limit, MAX_OPS_LIMIT))
        cursor = max(0, cursor)
        status, payload = self.app.manager.ops_view(
            run_id,
            case_name,
            since=since,
            until=until,
            group=group,
            mb=mb,
            limit=limit,
            cursor=cursor,
        )
        self._send_json(status, payload)

    # -- GET /api/events --------------------------------------------------
    def _events(self) -> None:
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        channel = self.app.bus.subscribe()
        try:
            self.wfile.write(b": connected\n\n")
            active = self.app.manager.active()
            self.wfile.write(
                format_sse(
                    {
                        "type": "hello",
                        "service": "judge",
                        "runs": [
                            {"run_id": view["run_id"], "state": view["state"], "done": view["done"], "total": view["total"]}
                            for view in active
                            if view is not None
                        ],
                    }
                )
            )
            self.wfile.flush()
            while True:
                try:
                    event = channel.get(timeout=5.0)
                except stdlib_queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                self.wfile.write(format_sse(event))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.app.bus.unsubscribe(channel)


def _int_param(
    query: dict[str, list[str]], name: str, *, default: Optional[int] = None
) -> Optional[int]:
    values = query.get(name)
    if not values:
        return default
    raw = values[-1]
    if raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise _HttpError(400, {"error": "bad-request", "detail": f"{name} 需要整数"}) from None


def create_server(app: ServiceApp, host: str = "127.0.0.1", port: int = 3081) -> JudgeHTTPServer:
    """建服务；拒绝非回环地址（CONTRACT §2.0）。"""
    if host not in LOOPBACK_HOSTS:
        raise ValueError(f"只允许监听回环地址（得到 {host!r}）；CONTRACT §2.0 禁止绑 0.0.0.0")
    return JudgeHTTPServer((host, port), app)


def serve(
    app: ServiceApp,
    host: str = "127.0.0.1",
    port: int = 3081,
    *,
    ready: Optional[threading.Event] = None,
) -> int:
    """前台跑服务，Ctrl-C 干净退出。返回进程退出码。"""
    server = create_server(app, host, port)
    actual_host, actual_port = server.server_address[0], server.server_address[1]
    print(
        f"judge serve · http://{actual_host}:{actual_port} · 账本 {app.config.ledger_path}",
        flush=True,
    )
    if ready is not None:
        ready.set()
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("\n收到 Ctrl-C，正在停止…", flush=True)
    finally:
        server.server_close()
        app.manager.shutdown()
    print("judge serve 已停止", flush=True)
    return 0
