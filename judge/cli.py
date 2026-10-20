"""``python3 -m judge <子命令>``：agent 的主要入口（CONTRACT §4）。

============================  ==================================================
``eval <case.in> <out>``      纯评估，不写账本（``--json`` 给机器读）
``run --version V --cases …`` 提交一次运行并**阻塞到终态**，打印几行摘要
``ls [--case C] [--limit N]`` 打印账本摘要表（含相对分与排名）
``serve [--port 3081]``       起 HTTP 服务（只绑回环），Ctrl-C 干净退出
``acceptance``                7 个验收值（转调 ``judge.core.acceptance``）
``selftest``                  服务端语义自检（转调 ``judge.service.selftest``）
============================  ==================================================

退出码（CONTRACT §4）：``0`` 合法/成功；``1`` 映射非法；``2`` 解析错误；``3`` 服务或
队列错误；``4`` 超时。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from judge.core import ParseError, evaluate, parse_case

from .service.config import DEFAULT_URL, Config
from .service.ledger import Ledger, compute_versions
from .service.queue import SubmitSpec

__all__ = ["main", "build_parser"]

TERMINAL = {"done", "failed", "timeout"}


# --------------------------------------------------------------------------- #
# HTTP 小客户端
# --------------------------------------------------------------------------- #


class ServiceUnavailable(RuntimeError):
    """后端连不上（连接被拒 / DNS 失败 / 超时）。"""


def _http_json(
    method: str, url: str, payload: Optional[dict] = None, timeout: float = 30.0
) -> tuple[int, dict]:
    data: Optional[bytes] = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            try:
                return int(response.status), json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return int(response.status), {"raw": raw}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return int(exc.code), json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return int(exc.code), {"raw": raw}
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
        raise ServiceUnavailable(str(exc)) from exc


def _base_url(args: argparse.Namespace) -> str:
    return (args.url or os.environ.get("JUDGE_URL") or DEFAULT_URL).rstrip("/")


def _detect_commit(root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    value = (completed.stdout or "").strip()
    return value if completed.returncode == 0 and value else "unknown"


def _bases(config: Config) -> dict[str, int]:
    """基准值（``time/base`` 的 base），以 ``cases/expected.json`` 为唯一出处。"""
    path = config.cases_dir / "expected.json"
    data: Any = None
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
    if not isinstance(data, dict):
        try:
            from judge.core.acceptance import load_expected

            data = load_expected()
        except Exception:
            return {}
    return {
        str(name): int(entry["time"])
        for name, entry in data.items()
        if isinstance(entry, dict) and isinstance(entry.get("time"), int)
    }


# --------------------------------------------------------------------------- #
# eval
# --------------------------------------------------------------------------- #


def cmd_eval(args: argparse.Namespace) -> int:
    try:
        case = parse_case(args.input)
    except ParseError as exc:
        print(f"解析错误（输入）：{exc}", file=sys.stderr)
        return 2
    try:
        output_text = Path(args.output).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"解析错误（输出）：{exc}", file=sys.stderr)
        return 2
    try:
        result = evaluate(case, output_text)
    except ParseError as exc:
        print(f"解析错误（输出）：{exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["ok"]:
            print(f"合法 · Time={result['time']} · lb={result['lb']} · K={result['K']}")
            for group in result["groups"]:
                used = group["mexp"] + group["movl"] + group["mact"]
                print(
                    f"  卡组 {group['v']}: Mexp={group['mexp']} Movl={group['movl']} "
                    f"Mact={group['mact']} 合计 {used}/{group['limit']}"
                )
            for engine in result["engines"]:
                print(
                    f"  引擎 v{engine['v']}: 计算 {engine['comp']} · 通信 {engine['comm']} "
                    f"（通信首尾 {engine['comm_first']}..{engine['comm_last']}）"
                )
        else:
            print(f"非法 · {len(result['errors'])} 条错误 · 网格 {result['grid']} · K={result['K']}")
            for error in result["errors"][:10]:
                print(
                    f"  [{error['category']}] t={error['t']} at={error['at']} {error['message']}"
                )
    return 0 if result["ok"] else 1


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #


def _build_run_payload(args: argparse.Namespace, config: Config) -> tuple[Optional[dict], int]:
    cases = list(args.cases) if args.cases else config.available_cases()
    if not cases:
        print(f"没有可用用例：{config.cases_dir}", file=sys.stderr)
        return None, 3
    unknown = [name for name in cases if not config.case_input(name).is_file()]
    if unknown:
        print(f"用例不存在：{unknown}（cases 目录 {config.cases_dir}）", file=sys.stderr)
        return None, 2

    payload: dict[str, Any] = {
        "version": args.version,
        "commit": args.commit or _detect_commit(config.root),
        "cases": cases,
        "notes": args.notes or "",
        "origin": "cli",
        "actor": args.actor or ("solver" if args.solver else "baseline"),
    }
    if args.idempotency_key:
        payload["idempotency_key"] = args.idempotency_key

    if args.solver:
        payload["solver"] = args.solver
        return payload, 0

    # A 式：只登记输出。默认用 cases/<case>.out（题面样例输出），也可以用 --outputs 指定目录。
    directory = Path(args.outputs) if args.outputs else config.cases_dir
    outputs: dict[str, str] = {}
    for name in cases:
        path = directory / f"{name}.out"
        if not path.is_file():
            print(
                f"找不到输出文件 {path}；用 --outputs DIR 指定目录，或用 --solver 让服务端跑求解器",
                file=sys.stderr,
            )
            return None, 2
        outputs[name] = path.read_text(encoding="utf-8")
    payload["outputs"] = outputs
    return payload, 0


def _wait_local(manager: Any, run_id: str, timeout: float) -> Optional[dict]:
    return manager.wait(run_id, timeout=timeout)


def _wait_remote(url: str, run_id: str, timeout: float) -> Optional[dict]:
    deadline = time.monotonic() + timeout
    delay = 0.05
    while True:
        status, body = _http_json("GET", f"{url}/api/runs/{run_id}", timeout=10.0)
        if status == 200 and isinstance(body, dict):
            if body.get("state") in TERMINAL:
                return body
        if time.monotonic() >= deadline:
            return body if isinstance(body, dict) else None
        time.sleep(delay)
        delay = min(0.5, delay * 1.6)


def _run_errors_by_case(view: dict) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for error in view.get("errors") or []:
        grouped.setdefault(str(error.get("case")), []).append(error)
    return grouped


def _run_exit_code(view: dict) -> int:
    state = view.get("state")
    if state == "failed":
        return 3
    if state == "timeout":
        return 4
    results = view.get("results") or []
    failing = [item for item in results if not item.get("ok")]
    if not failing:
        return 0
    grouped = _run_errors_by_case(view)
    parse_cases = {
        str(item.get("case"))
        for item in failing
        if grouped.get(str(item.get("case")))
        and all(error.get("category") == "parse" for error in grouped[str(item.get("case"))])
    }
    return 2 if len(parse_cases) == len(failing) else 1


def _print_run_summary(view: dict, config: Config, *, local: bool, url: str) -> None:
    bases = _bases(config)
    results = view.get("results") or []
    total = view.get("total") or len(results)
    print(
        f"run {view.get('run_id')} · {view.get('state')} · {len(results)}/{total} 例"
        + (" · 本地队列" if local else f" · {url}")
    )
    print(
        f"版本 {view.get('version')} @ {view.get('commit')} · 来源 {view.get('origin')}/{view.get('actor')}"
        + (f" · solver {view.get('solver_cmd')}" if view.get("solver_cmd") else "")
    )
    grouped = _run_errors_by_case(view)
    for item in results:
        name = str(item.get("case"))
        base = bases.get(name)
        if item.get("ok"):
            ratio = None
            if isinstance(item.get("time"), int) and base:
                ratio = item["time"] / base
            extra = f"  base={base}  相对 {ratio:.3f}" if ratio is not None else ""
            print(f"  {name:<6s} ok   Time={item.get('time')}  lb={item.get('lb', '-')}{extra}")
        else:
            reasons = grouped.get(name) or []
            head = reasons[0]["message"] if reasons else "非法"
            category = reasons[0]["category"] if reasons else "?"
            print(f"  {name:<6s} 非法 [{category}] {head[:160]}")
    print(f"账本 {config.ledger_path} · {view.get('run_id')}")


def cmd_run(args: argparse.Namespace) -> int:
    config = Config.from_env()
    payload, code = _build_run_payload(args, config)
    if payload is None:
        return code

    url = _base_url(args)
    explicit_url = args.url is not None or bool(os.environ.get("JUDGE_URL"))
    wait_budget = float(args.wait_timeout or (60 + 12 * max(1, len(payload["cases"]))))

    local = bool(args.local)
    if not local:
        try:
            status, body = _http_json("POST", f"{url}/api/runs", payload, timeout=30.0)
        except ServiceUnavailable:
            if explicit_url and not args.local:
                print(f"后端未连接：{url}（先 python3 -m judge serve，或加 --local）", file=sys.stderr)
                return 3
            local = True
            print(f"提示：后端未连接（{url}），改用本地队列执行；账本仍写入 {config.ledger_path}")
        else:
            if status not in (200, 202):
                print(f"提交失败：HTTP {status} {json.dumps(body, ensure_ascii=False)}", file=sys.stderr)
                return 3
            run_id = str(body.get("run_id") or "")
            if not run_id:
                print(f"提交失败：响应里没有 run_id：{body}", file=sys.stderr)
                return 3
            if not body.get("created", True):
                print(f"幂等命中：沿用已存在的 {run_id}")
            view = _wait_remote(url, run_id, timeout=wait_budget)
            if view is None:
                print(f"等待超时：{run_id} 仍未到终态（{url}）", file=sys.stderr)
                return 3
            if args.json:
                print(json.dumps(view, ensure_ascii=False, indent=2))
            else:
                _print_run_summary(view, config, local=False, url=url)
            return _run_exit_code(view)

    # 本地模式：同一个队列/账本实现，只是不经过 HTTP
    from .service.server import ServiceApp

    app = ServiceApp(config)
    spec = SubmitSpec(
        version=payload["version"],
        commit=payload["commit"],
        cases=payload["cases"],
        solver_cmd=payload.get("solver"),
        outputs=payload.get("outputs"),
        notes=payload.get("notes") or "",
        idem=payload.get("idempotency_key"),
        origin="cli",
        actor=payload["actor"],
    )
    view, created = app.manager.submit(spec)
    if not created:
        print(f"幂等命中：沿用已存在的 {view['run_id']}")
    final = _wait_local(app.manager, view["run_id"], timeout=wait_budget)
    app.manager.shutdown()
    if final is None:
        print("等待超时：本地队列仍未到终态", file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps(final, ensure_ascii=False, indent=2))
    else:
        _print_run_summary(final, config, local=True, url=url)
    return _run_exit_code(final)


# --------------------------------------------------------------------------- #
# ls
# --------------------------------------------------------------------------- #


def cmd_ls(args: argparse.Namespace) -> int:
    config = Config.from_env()
    ledger = Ledger(config)
    rows = ledger.rows()
    entries = compute_versions(rows, _bases(config))
    if args.case:
        entries = [
            entry for entry in entries if args.case in (entry.get("cases") or {})
        ]
    # 摘要表看“最近几次运行”：按创建时间倒序取 limit 条（RANK/SCORE 仍是全局口径）
    entries.sort(key=lambda entry: str(entry.get("created_at") or ""), reverse=True)
    if args.limit:
        entries = entries[: int(args.limit)]
    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
        return 0
    if not entries:
        print(f"账本为空：{ledger.path}")
        return 0
    header = f"{'RANK':>4}  {'RUN':<8} {'CREATED':<20} {'VERSION':<14} {'COMMIT':<10} {'OK':<3} {'SCORE':>7}  CASES"
    print(header)
    for entry in entries:
        cases = entry.get("cases") or {}
        summary = " ".join(
            f"{name}={value.get('time') if value.get('ok') else '非法'}" for name, value in cases.items()
        )
        score = entry["score"]
        score_text = "null" if score is None else f"{score:.3f}"
        print(
            f"{entry['rank']:>4}  {str(entry['run_id']):<8} {str(entry['created_at']):<20} "
            f"{str(entry['version'])[:14]:<14} {str(entry['commit'])[:10]:<10} "
            f"{'yes' if entry['ok'] else 'no':<3} {score_text:>7}  {summary}"
        )
    print(f"\n账本 {ledger.path} · {len(rows)} 行")
    return 0


# --------------------------------------------------------------------------- #
# serve / acceptance / selftest
# --------------------------------------------------------------------------- #


def cmd_serve(args: argparse.Namespace) -> int:
    from .service.server import ServiceApp, serve

    config = Config.from_env()
    app = ServiceApp(config)
    try:
        return serve(app, args.host, args.port)
    except ValueError as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        return 3


def cmd_acceptance(args: argparse.Namespace) -> int:
    from judge.core.acceptance import run

    ok, results = run(verbose=not args.json)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def cmd_selftest(args: argparse.Namespace) -> int:
    from .service.selftest import main as selftest_main

    return selftest_main()


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m judge",
        description="MoE 分块与重叠吞吐优化 · 判题服务（CONTRACT v2）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    evaluate_parser = subparsers.add_parser("eval", help="纯评估一个输出文件，不写账本")
    evaluate_parser.add_argument("input", help="输入文件（cases/ex2.in）")
    evaluate_parser.add_argument("output", help="输出文件（out/ex2.out）")
    evaluate_parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    evaluate_parser.set_defaults(func=cmd_eval)

    run_parser = subparsers.add_parser("run", help="提交一次运行并阻塞到终态")
    run_parser.add_argument("--version", required=True, help="版本号（v0.5）")
    run_parser.add_argument("--commit", help="commit（缺省尝试 git rev-parse --short HEAD）")
    run_parser.add_argument("--cases", nargs="+", help="用例名（默认 cases/*.in 的全部）")
    run_parser.add_argument("--solver", help="让服务端逐用例执行的求解命令（10s/例超时）")
    run_parser.add_argument("--outputs", help="只登记输出的目录（默认 cases/，读 <case>.out）")
    run_parser.add_argument("--notes", help="备注")
    run_parser.add_argument("--actor", help="actor（默认 solver/baseline）")
    run_parser.add_argument("--idempotency-key", help="幂等键；同键重复提交返回既有 run_id")
    run_parser.add_argument("--url", help=f"服务地址（默认 {DEFAULT_URL}，或 $JUDGE_URL）")
    run_parser.add_argument("--local", action="store_true", help="不经 HTTP，直接用本地队列")
    run_parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    run_parser.add_argument("--wait-timeout", type=float, help="等待终态的上限秒数")
    run_parser.set_defaults(func=cmd_run)

    list_parser = subparsers.add_parser("ls", help="打印账本摘要表")
    list_parser.add_argument("--case", help="只看包含该用例的运行")
    list_parser.add_argument("--limit", type=int, default=20, help="最多显示多少行（默认 20）")
    list_parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    list_parser.set_defaults(func=cmd_ls)

    serve_parser = subparsers.add_parser("serve", help="起 HTTP 服务（只绑回环）")
    serve_parser.add_argument("--port", type=int, default=3081)
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.set_defaults(func=cmd_serve)

    acceptance_parser = subparsers.add_parser("acceptance", help="7 个验收值")
    acceptance_parser.add_argument("--json", action="store_true")
    acceptance_parser.set_defaults(func=cmd_acceptance)

    selftest_parser = subparsers.add_parser("selftest", help="服务端语义自检")
    selftest_parser.set_defaults(func=cmd_selftest)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
