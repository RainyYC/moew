#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""frontier 内核的独立实验入口（t2 交付物，**默认不接入生产**）。

三件事：

1. **固定配置对照**：从一份基线合法输出（`--baseline-out`，含 ``V/P/K/ψ/MAP``）里
   取出配置，在**同一份配置**上跑新内核，输出与生产完全相同的映射文件；比较的是调度
   内核，不是网格/切层/放置的配置收益。
2. **消融**：``--strategy A|B|C`` 对应协议 §9 的 A/B/C 三组（A=同窗口/同优先规则的事件
   内核；B=去 `mb−W` 窗口、生命周期内存门控；C=有界前瞻）。``--compare-kernel`` 会把
   同一配置下基线列表调度的最好 Time 一并算出，便于 A 组等价性核对。
3. **独立微基准**：``--microbench`` 在合成规模（按 `nmb` 放大）上分别统计基线列表调度与
   frontier 的堆访问次数/耗时。计数用独立包装器（不改 `sched.py`），且**只用于剖析**，
   不进入任何正式墙钟成绩。

用法
----
::

    # 固定基线配置，跑 B 组
    PYTHONPATH=src python3 tools/frontier_solve.py cases/ex1.in /tmp/ex1.frontier.out \
        --baseline-out cases/ex1.out --strategy B --budget 3

    # 同时打印基线列表调度在同一配置下最好的 Time
    ... --compare-kernel

    # 微基准：nmb 放大后的堆访问/耗时（用 ex2 的配置，固定 V/P/ψ/MAP）
    PYTHONPATH=src python3 tools/frontier_solve.py cases/ex2.in --microbench \
        --nmb 16 64 256 1024

stdout 只有映射本身（与 `solve_all.py` 单例模式一致）；日志/统计走 stderr；
``--json`` 时把统计作为一行 JSON 打到 stderr。退出码 0 成功 / 1 无合法解 /
2 用法或输入错误 / 3 写输出失败。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from solver import casein, formula, frontier, sched, solve  # noqa: E402


def _load_config(case, args):
    """返回 ``(plan, map_rows, config_meta)``。

    优先用基线输出固定配置；否则取 ``lb`` 最小的枚举配置（只作为“没有基线输出时”的
    兜底，正式对照必须传 `--baseline-out`）。
    """
    if args.baseline_out:
        path = Path(args.baseline_out)
        config = frontier.parse_schedule_config(path.read_text(encoding="utf-8"), case)
        plan = formula.build_plan(
            case, config["V"], config["P"], 1, config["psi"], config["map_rows"]
        )
        return plan, config["map_rows"], {
            "source": str(path),
            "V": config["V"],
            "P": config["P"],
            "K": config["K"],
            "psi": list(config["psi"]),
        }
    configs, pmaps = solve.enumerate_configs(case)
    if not configs:
        raise SystemExit("没有可行配置（Mexp 已超内存）")
    if args.config:
        parts = args.config.split(",")
        if len(parts) != 2:
            raise SystemExit("--config 需要形如 V,P")
        V, P = int(parts[0]), int(parts[1])
        chosen = next((item for item in configs if item.V == V and item.P == P), None)
        if chosen is None:
            raise SystemExit(f"--config {V},{P} 不在候选集里")
    else:
        chosen = configs[0]
    info = pmaps[chosen.P]
    plan = solve._plan(case, info, chosen)
    return plan, info.rows, {
        "source": "config" if args.config else "auto-lb",
        "V": chosen.V,
        "P": chosen.P,
        "K": plan.K,
        "psi": list(plan.psi),
    }


def _baseline_kernel_best(case, plan, deadline=None):
    """同一配置上基线列表调度的最好 ``(Time, W, variant, mode)``（A 组对照）。"""
    best = None
    variants = sched._SMALL_VARIANTS if case.n_ops > 20_000 else sched.VARIANTS
    windows = frontier._default_windows(case, plan, 4)
    for window in windows:
        for variant in variants:
            for mode in ("prio", "early"):
                if deadline is not None and time.monotonic() > deadline:
                    return best
                result = sched.schedule(case, plan, window, variant, mode)
                if result is None:
                    continue
                if best is not None and result.time >= best[0]:
                    continue
                ok, _groups = sched.memory_usage(case, plan, result.start, result.end)
                if ok:
                    best = (result.time, window, variant, mode)
    return best


def _counted(call, module):
    """给 ``module.heappush/heappop`` 套计数包装器，返回 ``(result, pushes, pops, seconds)``。

    只在独立剖析里使用；计数本身有开销，所以同时报告的是**包装后的耗时**，不用于正式
    墙钟比较。`sched.py` 里是 ``from heapq import heappush, heappop``，因此替换它的模块
    级名字即可计数，不必改源码。
    """
    original_push = module.heappush
    original_pop = module.heappop
    counter = {"push": 0, "pop": 0}

    def push(heap, item):
        counter["push"] += 1
        return original_push(heap, item)

    def pop(heap):
        counter["pop"] += 1
        return original_pop(heap)

    module.heappush = push
    module.heappop = pop
    try:
        started = time.perf_counter()
        result = call()
        elapsed = time.perf_counter() - started
    finally:
        module.heappush = original_push
        module.heappop = original_pop
    return result, counter["push"], counter["pop"], elapsed


def _microbench(case, args) -> int:
    plan_base, _rows, config = _load_config(case, args)
    print(
        f"microbench case={case.name} L={case.L} V={config['V']} P={config['P']} "
        f"base_nmb={case.nmb}（计数用独立包装器，耗时含计数开销，不作正式成绩）",
        file=sys.stderr,
    )
    print(
        f"{'nmb':>6} {'ops':>9} {'kernel':>22} {'time_s':>9} "
        f"{'pushes':>9} {'pops':>9} {'repush':>7} {'Time':>14}",
        file=sys.stderr,
    )
    for nmb in args.nmb:
        scaled = replace(case, nmb=nmb)
        variants = sched._SMALL_VARIANTS if scaled.n_ops > 20_000 else sched.VARIANTS
        window = nmb
        variant = variants[0]
        for label, call in (
            ("sched(prio)", lambda: sched.schedule(scaled, plan_base, window, variant, "prio")),
            ("sched(early)", lambda: sched.schedule(scaled, plan_base, window, variant, "early")),
            (
                "frontier(time,zf)",
                lambda: frontier.schedule(
                    scaled, plan_base, window=window, variant=variant,
                    gating=False, zero_free=True, order="time",
                ),
            ),
            (
                "frontier(priority)",
                lambda: frontier.schedule(
                    scaled, plan_base, window=window, variant=variant,
                    gating=False, zero_free=True, order="priority",
                ),
            ),
            (
                "frontier(lazy_early)",
                lambda: frontier.schedule(
                    scaled, plan_base, window=window, variant=variant,
                    gating=False, zero_free=False, order="lazy_early",
                ),
            ),
        ):
            if label.startswith("sched"):
                result, pushes, pops, elapsed = _counted(call, sched)
                repush = -1
            else:
                stats = frontier.Stats()
                started = time.perf_counter()
                if "lazy_early" in label:
                    result = frontier.schedule(
                        scaled, plan_base, window=window, variant=variant,
                        gating=False, zero_free=False, order="lazy_early", stats=stats,
                    )
                else:
                    result = frontier.schedule(
                        scaled, plan_base, window=window, variant=variant,
                        gating=False, zero_free=True,
                        order="time" if "time" in label else "priority",
                        stats=stats,
                    )
                elapsed = time.perf_counter() - started
                pushes, pops, repush = stats.pushes, stats.pops, stats.repushes
            print(
                f"{nmb:>6} {scaled.n_ops:>9} {label:>22} {elapsed:>9.4f} "
                f"{pushes:>9} {pops:>9} {repush:>7} "
                f"{(result.time if result is not None else 'None'):>14}",
                file=sys.stderr,
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="frontier 事件内核独立实验入口")
    parser.add_argument("case_in", help="输入文件（题面 §2 格式）")
    parser.add_argument("case_out", nargs="?", help="输出文件（省略时只写 stdout）")
    parser.add_argument(
        "--baseline-out",
        help="基线合法输出，用来固定 V/P/K/ψ/MAP（避免混入配置收益）",
    )
    parser.add_argument("--config", help="显式 V,P（不在候选集里则报错）")
    parser.add_argument("--strategy", choices=("A", "B", "C", "auto"), default="B")
    parser.add_argument("--budget", type=float, default=3.0, help="内核搜索墙钟预算（秒）")
    parser.add_argument("--seed", type=int, default=20261020)
    parser.add_argument("--window", type=int, default=None, help="仅 A 组：显式窗口 W")
    parser.add_argument("--compare-kernel", action="store_true", help="打印基线列表调度最好 Time")
    parser.add_argument("--json", action="store_true", help="stderr 打一行 JSON 统计")
    parser.add_argument("--microbench", action="store_true", help="微基准模式（不写输出）")
    parser.add_argument(
        "--nmb", type=int, nargs="+", default=[16, 64, 256],
        help="微基准的 nmb 列表（默认 16 64 256）",
    )
    args = parser.parse_args(argv)

    try:
        case = casein.parse_case(args.case_in)
    except casein.InputError as exc:
        print(f"[frontier] 输入解析失败：{exc}", file=sys.stderr)
        return 2
    try:
        plan, map_rows, config = _load_config(case, args)
    except (OSError, ValueError, SystemExit) as exc:
        print(f"[frontier] 配置解析失败：{exc}", file=sys.stderr)
        return 2

    if args.microbench:
        return _microbench(case, args)

    started = time.monotonic()
    deadline = started + max(0.05, args.budget)
    stats = frontier.Stats()
    best_meta = None
    if args.strategy == "A" and args.window is not None:
        variants = sched._SMALL_VARIANTS if case.n_ops > 20_000 else sched.VARIANTS
        variant = variants[0]
        result = frontier.schedule(
            case, plan, window=args.window, variant=variant, gating=False,
            zero_free=True, order="time", seed=args.seed, deadline=deadline, stats=stats,
        )
        best_meta = {"window": args.window, "variant": list(variant), "order": "time"}
    else:
        result = frontier.search(
            case, plan, strategy=args.strategy, deadline=deadline, seed=args.seed,
            stats=stats,
        )
    elapsed = time.monotonic() - started
    if result is None:
        print("[frontier] 预算内没有合法完整解", file=sys.stderr)
        return 1

    problems = sched.check_schedule(case, plan, result)
    if problems:
        print(f"[frontier] 自检失败：{problems[:3]}", file=sys.stderr)
        return 1
    ok, groups = sched.memory_usage(case, plan, result.start, result.end)
    if not ok:
        print(
            f"[frontier] 内存超限：{[(g.v, g.used) for g in groups]} M={case.M}",
            file=sys.stderr,
        )
        return 1
    text = sched.render_output(case, plan, result, map_rows)
    if args.case_out:
        try:
            out_path = Path(args.case_out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(text, encoding="utf-8")
        except OSError as exc:
            print(f"[frontier] 写输出失败：{exc}", file=sys.stderr)
            return 3
    sys.stdout.write(text)
    sys.stdout.flush()

    baseline = None
    if args.compare_kernel:
        baseline = _baseline_kernel_best(
            case, plan, deadline=time.monotonic() + max(0.5, args.budget)
        )
    payload = {
        "case": case.name,
        "config": config,
        "strategy": args.strategy,
        "solver_time": result.time,
        "lb": plan.lb,
        "window": result.window,
        "variant": list(result.variant),
        "memory_ok": ok,
        "groups": [
            {"v": g.v, "mexp": g.mexp, "movl": g.movl, "mact": g.mact,
             "peak_comm": g.peak_comm, "peak_act": g.peak_act, "used": g.used}
            for g in groups
        ],
        "stats": stats.as_dict(),
        "baseline_kernel": None if baseline is None else {
            "time": baseline[0], "window": baseline[1],
            "variant": list(baseline[2]), "mode": baseline[3],
        },
        "best_meta": best_meta,
        "elapsed": round(elapsed, 4),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    else:
        print(
            f"[frontier] {case.name}: strategy={args.strategy} Time={result.time} "
            f"(lb={plan.lb}) V={plan.V} P={plan.P} K={plan.K} "
            f"peak=({[(g.peak_comm, g.peak_act) for g in groups]}) "
            f"pop/push={stats.pops}/{stats.pushes} repush={stats.repushes} "
            f"elapsed={elapsed:.2f}s",
            file=sys.stderr,
        )
        if baseline is not None:
            print(
                f"[frontier] 基线列表调度（同配置）：Time={baseline[0]} "
                f"W={baseline[1]} variant={baseline[2]} mode={baseline[3]}",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
