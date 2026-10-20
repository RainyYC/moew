#!/usr/bin/env python3
"""批量求解 + 用判题核心复核（agent 的主要交付入口）。

用法
----
**单例模式（服务端 `POST /api/runs` B 式的逐用例调用，固定接口）**::

    python3 solver/solve_all.py cases/<case>.in runs/out/<run_id>/<case>.out

即 ``argv[1]`` = 输入路径、``argv[2]`` = 输出路径。映射同时写入该文件并打到 **stdout**
（服务端没拿到文件时就把它当输出内容）；**stdout 只有映射本身**，所有日志/摘要走
stderr。退出码：`0` 成功 / `1` 没有合法解 / `2` 输入解析失败或**用法错误**（`--budget`
缺值、非数字、非正时只打用法提示到 stderr，不抛 traceback）/ `3` 写输出失败。也可以只给
输入路径（映射只上 stdout）。

**批量模式**::

    python3 solver/solve_all.py                      # 求 6 个官方样例，写 out/<case>.out
    python3 solver/solve_all.py --check              # 再调 `python3 -m judge eval` 复核 + 退化形态
    python3 solver/solve_all.py --cases ex1 mini     # 指定用例
    python3 solver/solve_all.py --out out --budget 9 # 输出目录 / 逐例求解墙钟预算
    python3 solver/solve_all.py --json                # 机器可读摘要
    python3 solver/solve_all.py --exact --check       # 追加精确搜索（nmb=2 单层 stage）后再复核

纪律（任务书 / CONTRACT §9）
---------------------------
* 每例求解墙钟 ≤ 10 s（题面 §5.4），默认预算 8.5 s，留 1.5 s 余量给落盘与抖动；
* 候选解写入 ``out/<case>.out`` **之后**才用 ``python3 -m judge eval`` 判定合法性；
* 与 judge 的交互只走子进程（`solver/judgebridge.py`），不 import `judge.core`。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:  # 允许 `python3 solver/solve_all.py` 直接运行
    sys.path.insert(0, str(_ROOT))

from solver import casein, judgedbridge, solve  # noqa: E402

#: CONTRACT §7 冻结的 6 个官方样例目标（题面原文值；求解要求 Time ≤ 该值）。
TARGETS: dict[str, int] = {
    "ex1": 592,
    "ex2": 4880,
    "ex3": 4000,
    "ex4": 3200,
    "ex5": 416,
    "ex6": 1744,
}

#: 题面 §5.4 的单例墙钟上限（秒）。
SOLVE_LIMIT_S = 10.0


def _format_variant(variant: tuple[bool, bool, bool, bool]) -> str:
    fwd, mb_desc, l_desc, l_major = variant
    return (
        f"fwd={'asc' if fwd else 'bwd'}-first/"
        f"mb={'desc' if mb_desc else 'asc'}/"
        f"l={'desc' if l_desc else 'asc'}/"
        f"{'l-major' if l_major else 'mb-major'}"
    )


def solve_one(
    name: str,
    cases_dir: Path,
    out_dir: Path,
    budget: float,
    check: bool,
    verbose: bool,
    exact: bool = False,
) -> dict:
    """求解 + 落盘（+ 可选 judge 复核），返回一条汇总记录。"""
    in_path = cases_dir / f"{name}.in"
    record: dict = {"case": name, "in": str(in_path), "ok": False}
    if not in_path.is_file():
        record["error"] = f"找不到输入 {in_path}"
        return record
    case = casein.parse_case(in_path)
    started = time.monotonic()
    solution = solve.solve_case(case, budget=budget, exact=exact)
    solve_s = time.monotonic() - started
    record["solve_s"] = round(solve_s, 3)
    if solution is None:
        record["error"] = "没有找到合法映射（搜索失败）"
        return record
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}.out"
    out_path.write_text(solution.text, encoding="utf-8")
    record.update(
        {
            "out": str(out_path),
            "grid": {"V": solution.V, "P": solution.P, "D": solution.D},
            "K": solution.K,
            "psi": list(solution.psi),
            "window": solution.window,
            "variant": _format_variant(solution.variant),
            "mode": solution.mode,
            "solver_time": solution.time,
            "solver_lb": solution.lb,
            "exact": solution.exact_stats,
            "memory": [
                {
                    "v": group.v,
                    "mexp": group.mexp,
                    "movl": group.movl,
                    "mact": group.mact,
                    "limit": case.M,
                }
                for group in solution.groups
            ],
        }
    )
    if check:
        try:
            verdict = judgedbridge.judge_eval(in_path, out_path)
        except judgedbridge.JudgeError as exc:
            record["error"] = str(exc)
            return record
        record["judge"] = {
            "ok": bool(verdict.get("ok")),
            "time": verdict.get("time"),
            "lb": verdict.get("lb"),
            "exit": verdict.get("_exit"),
            "errors": verdict.get("errors") or [],
        }
        record["ok"] = bool(verdict.get("ok"))
    else:
        record["ok"] = True
    if name in TARGETS:
        record["target"] = TARGETS[name]
        if record["ok"] and check:
            record["meets_target"] = int(verdict.get("time", 0)) <= TARGETS[name]
        else:
            record["meets_target"] = record["solver_time"] <= TARGETS[name]
    record["within_10s"] = solve_s <= SOLVE_LIMIT_S
    if verbose:
        judge_part = ""
        if "judge" in record:
            judge_part = (
                f"  judge={'ok' if record['judge']['ok'] else 'INVALID'}"
                f" time={record['judge']['time']} lb={record['judge']['lb']}"
            )
            if not record["judge"]["ok"]:
                judge_part += f" errors={record['judge']['errors'][:2]}"
        target_part = ""
        if "target" in record:
            mark = "OK" if record["meets_target"] else "MISS"
            target_part = f"  target≤{record['target']} [{mark}]"
        grid = record["grid"]
        exact_part = ""
        stats = record.get("exact")
        if stats:
            gain = stats.get("improved")
            exact_part = (
                f"  exact=space {stats.get('space')}/enum {stats.get('enumerated')}"
                f"/{stats.get('elapsed', 0):.2f}s"
                + (f"→{gain}" if gain else "/无改进")
            )
        print(
            f"  {name:5s} V={grid['V']} P={grid['P']} D={grid['D']} "
            f"psi={record['psi']} K={record['K']} W={record['window']}"
            f"  solver_time={record['solver_time']} (lb={record['solver_lb']})"
            f"{judge_part}{target_part}{exact_part}  solve={record['solve_s']}s"
        )
    return record


def run_single(
    case_in: str, case_out: str | None, budget: float, exact: bool = False
) -> int:
    """单例模式：``solve_all.py <case.in> [case.out]``（服务端逐用例调用的固定形态）。

    映射写到 ``case_out``（给了的话）**并且**原样打到 stdout，保证「不写文件时 stdout 也
    被当输出内容」这条约定成立。stdout 不混任何日志；摘要写 stderr。
    退出码：0 成功 / 1 没有合法解 / 2 输入解析失败。
    """
    in_path = Path(case_in)
    out_path = Path(case_out) if case_out else None
    try:
        case = casein.parse_case(in_path)
    except casein.InputError as exc:
        print(f"[solve] 输入解析失败：{exc}", file=sys.stderr)
        return 2
    started = time.monotonic()
    solution = solve.solve_case(case, budget=budget, exact=exact)
    elapsed = time.monotonic() - started
    if solution is None:
        print(f"[solve] {case.name}: 没有找到合法映射", file=sys.stderr)
        return 1
    if out_path is not None:
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(solution.text, encoding="utf-8")
        except OSError as exc:
            print(f"[solve] 写输出失败：{exc}", file=sys.stderr)
            return 3
    sys.stdout.write(solution.text)
    sys.stdout.flush()
    grid = f"V={solution.V} P={solution.P} D={solution.D}"
    print(
        f"[solve] {case.name}: {grid} psi={list(solution.psi)} K={solution.K} "
        f"Time={solution.time} (lb={solution.lb}) solve={elapsed:.2f}s",
        file=sys.stderr,
    )
    return 0


def run_selftests(verbose: bool) -> bool:
    """跑 `solver/selftests/run.py`（退化形态），返回是否全绿。"""
    script = Path(__file__).resolve().parent / "selftests" / "run.py"
    if not script.is_file():
        print(f"  [selftests] 找不到 {script}", file=sys.stderr)
        return False
    import subprocess

    command = [sys.executable, str(script)] + ([] if verbose else ["--quiet"])
    proc = subprocess.run(command, cwd=str(_ROOT), capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
    return proc.returncode == 0


_SINGLE_USAGE = (
    "用法：python3 solver/solve_all.py <case.in> [case.out] [--budget 秒]\n"
    "  <case.in>   输入路径（题面 §2 格式）\n"
    "  case.out    输出路径（省略时映射只写到 stdout）\n"
    "  --budget N  单例求解墙钟预算（秒，正数；默认 8.5，题面硬上限 10）\n"
    "              **按输入规模自动下调**：op 数 > 20000 时默认 6.5，> 200000 时 5.0，\n"
    "              显式给 --budget 则以其为准（上限仍 9.5）\n"
    "  --exact     追加精确搜索（nmb=2 且每 stage 单层；默认关闭）\n"
    "批量模式见 --help"
)


#: 求解墙钟预算：题面硬上限 10 s，按 op 规模递减以留出渲染/落盘/进程启动的余量。
BUDGET_BY_OPS: tuple[tuple[int, float], ...] = ((200_000, 5.0), (20_000, 6.5), (0, 8.5))


def auto_budget(n_ops: int) -> float:
    """按 op 数给默认预算：大用例缩短，避免撞 10 s 硬上限。"""
    for threshold, budget in BUDGET_BY_OPS:
        if n_ops > threshold:
            return budget
    return BUDGET_BY_OPS[-1][1]


def _parse_single_budget(raw: list[str]) -> tuple[float, int]:
    """从单例模式的参数里取出 ``--budget``：缺值/非数字都按**用法错误**处理（返回 2）。

    调用方（服务端队列）会把「求解失败」和「用法错误」分开记，所以这里不能抛 traceback
    （那会退 1，被误当成「没有合法解」）。成功时返回 ``(budget, 0)``。
    """
    budget = 8.5
    if "--budget" not in raw:
        return budget, 0  # 0 表示"未显式指定"，调用方会换成 auto_budget(n_ops)
    position = raw.index("--budget")
    if position + 1 >= len(raw):
        print(f"--budget 缺少取值。\n{_SINGLE_USAGE}", file=sys.stderr)
        return budget, 2
    text = raw[position + 1]
    try:
        budget = float(text)
    except ValueError:
        print(f"--budget 需要数字，得到 {text!r}。\n{_SINGLE_USAGE}", file=sys.stderr)
        return budget, 2
    if budget != budget or budget <= 0 or budget == float("inf"):  # NaN / 非正 / 无穷
        print(f"--budget 需要正的有限秒数，得到 {text!r}。\n{_SINGLE_USAGE}", file=sys.stderr)
        return budget, 2
    del raw[position : position + 2]
    return budget, 0


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    # 单例模式：第一个参数不是选项（服务端调用形态 solve_all.py <case.in> <out>）
    if raw and not raw[0].startswith("-"):
        budget, status = _parse_single_budget(raw)
        if status != 0:
            return status
        exact = "--exact" in raw
        if exact:
            raw = [item for item in raw if item != "--exact"]
        if len(raw) > 2:
            print(_SINGLE_USAGE, file=sys.stderr)
            return 2
        if status == 0 and "--budget" not in sys.argv:  # 未显式指定 → 按规模自动
            try:
                case = casein.parse_case(raw[0])
                budget = auto_budget(case.n_ops)
            except Exception:  # 输入读不了就交给 run_single 报错
                budget = 8.5
        return run_single(raw[0], raw[1] if len(raw) > 1 else None, budget, exact)

    parser = argparse.ArgumentParser(description="MoE 映射求解器（报告 §2 复原）+ judge 复核")
    parser.add_argument("--cases", nargs="+", default=list(TARGETS), help="用例名（不含扩展名）")
    parser.add_argument("--cases-dir", default=str(_ROOT / "cases"), help="输入目录")
    parser.add_argument("--out", default=str(_ROOT / "out"), help="输出目录")
    parser.add_argument("--budget", type=float, default=8.5, help="单例求解墙钟预算（秒）")
    parser.add_argument(
        "--exact",
        action="store_true",
        help="对 nmb=2 且每 stage 单层的形状追加精确搜索（通信交错穷举 + 计算顺序枚举）",
    )
    parser.add_argument("--check", action="store_true", help="用 python3 -m judge eval 复核 + 跑退化形态")
    parser.add_argument("--skip-selftests", action="store_true", help="--check 时跳过退化形态")
    parser.add_argument("--json", action="store_true", help="只输出机器可读 JSON")
    parser.add_argument("--quiet", action="store_true", help="不打印逐例明细")
    args = parser.parse_args(argv)

    cases_dir = Path(args.cases_dir)
    out_dir = Path(args.out)
    verbose = not args.json and not args.quiet
    if not args.json:
        print(
            f"求解 {len(args.cases)} 个用例：budget={args.budget}s/例，"
            f"输出目录 {out_dir}，judge 复核={'开' if args.check else '关'}"
        )
    records = [
        solve_one(name, cases_dir, out_dir, args.budget, args.check, verbose, args.exact)
        for name in args.cases
    ]

    all_ok = all(record.get("ok") for record in records)
    all_time = all(record.get("within_10s") for record in records)
    all_target = all(record.get("meets_target", True) for record in records)
    selftests_ok = True
    if args.check and not args.skip_selftests:
        if not args.json:
            print("退化形态自测（solver/selftests/）：")
        selftests_ok = run_selftests(verbose)
        if not args.json:
            print(f"  退化形态：{'全部合法' if selftests_ok else '有失败'}")

    overall = all_ok and all_time and all_target and selftests_ok
    checked_selftests = bool(args.check and not args.skip_selftests)
    payload = {
        "ok": overall,
        "solved": all_ok,
        "within_10s": all_time,
        "meets_target": all_target,
        "selftests_ok": selftests_ok,
        "budget_s": args.budget,
        "out_dir": str(out_dir),
        "cases": records,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        tail = f" / 退化形态 {'通过' if selftests_ok else '失败'}" if checked_selftests else ""
        print(
            f"合计：合法 {'是' if all_ok else '否'} / 10s 内 {'是' if all_time else '否'} / "
            f"不劣于题面值 {'是' if all_target else '否'}{tail}"
        )
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
