#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t4 固定配置消融驱动：同一 ``V/P/K/ψ/MAP`` 下比较构造器与搜索。

对每个用例：

1. **同拓扑单候选**（同一 ``W=nmb``、同一 ``variant``）：基线 `sched.schedule` 的
   ``prio`` / ``early`` vs frontier 的 ``time(zero_free=0/1)`` / ``priority`` /
   ``lazy_early``。记录 Time、构造墙钟、逐卡组峰值、合法性——用来区分：
   * 工程加速：Time 相同、构造更快；
   * 派发规则差异：Time 不同；
   * 零时长零等待：``zero_free`` 两态之差。
2. **frontier 搜索曲线**：B 组候选按固定顺序逐个构造，记录 N=1/4/10/全部 的
   best Time 与累计墙钟；用于区分“算法收益”与“多搜几个候选的收益”。
3. **门控是否绑定**：记 ``memory_caps`` 与 best 解的 ``peak_comm/peak_act``，
   判断 B 的收益是否可能来自生命周期门控（而不是优先级/候选集）。
4. **基线端到端参照**：从 t3 冻结产物读官方 Time（只读，不覆盖）。

输出 JSON（逐例 + 汇总）到 `--out`。本工具**不 import judge.core**，合法性用
`sched.check_schedule` / `sched.memory_usage` 自检；官方 Time 只从 t3 产物读取。

用法::

    python3 tools/frontier_ablate.py --baseline-dir runs/frontier/baseline/baseline-official50 \
        --cases-fast12 --out runs/frontier/experiments/t4/fixed-fast12.json

    python3 tools/frontier_ablate.py --baseline-dir ... --cases <case.in> ... --out ...
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from solver import casein, formula, frontier, sched  # noqa: E402

FAST12 = (
    "r16_p4_trap", "r24_p4_block", "r32_p8_ramp", "r64_v2_c2",
    "r64_v8_c8d", "r128_v8_c8a", "r256_v4_c4",
    "x03_lr_trap_p3", "x05_lr_tight_p6", "x13_lr_twochunk_p8",
    "x18_vl_tight_small", "x19_vl_trap4_fs4",
)
K2V_EXTRA = (
    "r20_p2_flat", "r24_p3_flat", "x01_lr_block_p2",
    "x06_lr_trap_p7", "x10_lr_tight_p8", "x15_lr_twochunk_p10",
)
BATTERY5 = ("b03-m256", "b05-maxmb", "b06-maxmb-tight", "b08-narrow", "b13-balanced-compute")
SAMPLES = ("ex1", "ex2", "ex3", "ex4", "ex5", "ex6")


def _baseline_out(baseline_dir: Path, name: str) -> Path | None:
    for candidate in (baseline_dir / f"{name}.out", baseline_dir / f"{name}.grader.out"):
        if candidate.is_file():
            return candidate
    return None


def _official_time(baseline_dir: Path, name: str) -> int | None:
    grader = baseline_dir / f"{name}.grader.out"
    if grader.is_file():
        try:
            return int(grader.read_text(encoding="utf-8").strip().splitlines()[-1])
        except (ValueError, IndexError):
            return None
    record = baseline_dir / f"{name}.json"
    if record.is_file():
        try:
            payload = json.loads(record.read_text(encoding="utf-8"))
            official = payload.get("official") or {}
            if isinstance(official.get("time"), int):
                return official["time"]
        except (ValueError, OSError):
            pass
    log = baseline_dir / f"{name}.out.log"
    if log.is_file():
        import re
        match = re.search(r"Time=(\d+)", log.read_text(encoding="utf-8", errors="replace"))
        if match:
            return int(match.group(1))
    return None


def _measure(case, plan, result, wall: float, full: bool = True) -> dict:
    """记录一份调度的 Time / 墙钟 / 合法性 / 峰值。

    ``full=False`` 只记 Time/墙钟：640k op 上 `check_schedule` + `memory_usage` 单次就要
    数秒，不能对每个候选都做；**每个新 best 仍会单独做一次完整复核**。
    """
    info = {"wall": round(wall, 5), "time": None, "valid": None,
            "check_problems": None, "peaks": [], "used": None}
    if result is None:
        return info
    if not full:
        info["time"] = result.time
        return info
    problems = sched.check_schedule(case, plan, result)
    ok, groups = sched.memory_usage(case, plan, result.start, result.end)
    info.update(
        time=result.time,
        valid=bool(ok and not problems),
        check_problems=len(problems),
        peaks=[[g.peak_comm, g.peak_act] for g in groups],
        used=max((g.used for g in groups), default=0),
    )
    return info


def _time_call(call) -> tuple[object, float]:
    started = time.perf_counter()
    result = call()
    return result, time.perf_counter() - started


def _single_candidates(case, plan, variant, window):
    """同拓扑单候选：基线 prio/early 与 frontier 各路径。

    ``early`` 在大规模上单次就可能几十秒（sched.py 自己的上限是 200k），因此
    ``n_ops > 100k`` 时跳过 ``base_early`` / ``frontier_lazy``，并在记录里标
    ``skipped_big``；其余路径仍按同一候选集比较。
    """
    rows: dict[str, dict] = {}
    big = case.n_ops > 100_000
    full = case.n_ops <= 120_000
    result, wall = _time_call(lambda: sched.schedule(case, plan, window, variant, "prio"))
    rows["base_prio"] = _measure(case, plan, result, wall, full=full)
    if big:
        rows["base_early"] = {"skipped_big": True, "wall": 0.0, "time": None,
                              "valid": None, "peaks": []}
    else:
        result, wall = _time_call(lambda: sched.schedule(case, plan, window, variant, "early"))
        rows["base_early"] = _measure(case, plan, result, wall, full=full)
    for label, kwargs in (
        ("frontier_time_zf0", dict(order="time", zero_free=False, gating=False)),
        ("frontier_time_zf1", dict(order="time", zero_free=True, gating=False)),
        ("frontier_priority", dict(order="priority", zero_free=False, gating=False)),
        ("frontier_lazy", dict(order="lazy_early", zero_free=False, gating=False)),
        ("frontier_gated_time", dict(order="time", zero_free=True, gating=True)),
    ):
        if big and label == "frontier_lazy":
            rows[label] = {"skipped_big": True, "wall": 0.0, "time": None,
                           "valid": None, "peaks": []}
            continue
        result, wall = _time_call(
            lambda kwargs=kwargs: frontier.schedule(
                case, plan, window=window, variant=variant, **kwargs
            )
        )
        rows[label] = _measure(case, plan, result, wall, full=full)
    return rows


def _value(row: dict, path: str):
    node = row
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _frontier_search(case, plan, max_ops_search: int):
    """B 组候选曲线：按固定顺序逐个构造，记录 best-of-N。"""
    variants = [None] + list(sched._SMALL_VARIANTS if case.n_ops > 20_000 else sched.VARIANTS)
    policies = ("auto", "comm1") if case.n_ops <= 20_000 else ("auto",)
    if case.n_ops > max_ops_search:
        variants = [None, sched.VARIANTS[0], sched.VARIANTS[4]]
        policies = ("auto",)
    candidates = []
    started = time.perf_counter()
    full = case.n_ops <= 120_000
    for policy in policies:
        for variant in variants:
            result, wall = _time_call(
                lambda variant=variant, policy=policy: frontier.schedule(
                    case, plan, window=None, variant=variant, gating=True,
                    zero_free=True, policy=policy, order="time",
                )
            )
            candidates.append(
                {
                    "variant": None if variant is None else list(variant),
                    "policy": policy,
                    "wall": round(wall, 5),
                    "measure": _measure(case, plan, result, wall, full=full),
                }
            )
    total_wall = time.perf_counter() - started
    curve = []
    best = None
    for index, item in enumerate(candidates, 1):
        info = item["measure"]
        if info["time"] is not None and (best is None or info["time"] < best):
            best = info["time"]
        if index in (1, 4, 10, len(candidates)):
            curve.append({"n": index, "best": best, "cum_wall": round(
                sum(c["wall"] for c in candidates[:index]), 5)})
    caps = frontier.memory_caps(case, plan, policy="auto")
    best_info = None
    best_item = None
    for item in candidates:
        info = item["measure"]
        if info["time"] is not None and info.get("valid") is not False:
            if best_info is None or info["time"] < best_info["time"]:
                best_info = info
                best_item = item
    # 每个新 best 单独做一次完整可行性复核（640k op 也不对每个候选做）。
    if best_item is not None and not full:
        # 需要重跑该候选才能拿到 start/end；重跑一次是 O(n log n)，可接受。
        variant = None if best_item["variant"] is None else tuple(best_item["variant"])
        result, wall = _time_call(
            lambda: frontier.schedule(
                case, plan, window=None, variant=variant, gating=True,
                zero_free=True, policy=best_item["policy"], order="time",
            )
        )
        best_info = _measure(case, plan, result, wall, full=True)
    gating_binding = None
    if caps and best_info:
        binding = []
        for group, (peaks, cap) in enumerate(zip(best_info["peaks"], caps)):
            demand = case.nmb * len(plan.layers_of_group[group])
            act_bound = cap.cap_act < demand and peaks[1] >= cap.cap_act
            comm_bound = cap.cap_comm < 2 and peaks[0] >= cap.cap_comm
            if act_bound or comm_bound:
                binding.append(group)
        gating_binding = bool(binding)
    return {
        "candidates": candidates,
        "curve": curve,
        "total_wall": round(total_wall, 5),
        "best": None if best_info is None else best_info["time"],
        "best_info": best_info,
        "caps": [
            {"cap_comm": c.cap_comm, "cap_act": c.cap_act,
             "need_act": c.need_act, "has_zero_comm": c.has_zero_comm}
            for c in (caps or [])
        ],
        "gating_binding": gating_binding,
    }


def _lookahead(case, plan, variant=None, policy="auto"):
    started = time.perf_counter()
    stats = frontier.Stats()
    result = frontier.schedule(
        case, plan, window=None, variant=variant, gating=True, zero_free=True,
        policy=policy, mode="lookahead", lookahead=4, stats=stats,
    )
    wall = time.perf_counter() - started
    return {
        "measure": _measure(case, plan, result, wall, full=case.n_ops <= 120_000),
        "wall": round(wall, 5),
        "rollouts": stats.lookahead_rollouts,
        "degraded": stats.degraded,
        "notes": stats.notes[-3:],
    }


def run_case(name: str, case_path: Path, baseline_dir: Path, max_ops_search: int) -> dict:
    case = casein.parse_case(case_path)
    out_path = _baseline_out(baseline_dir, name)
    if out_path is None:
        return {"case": name, "error": f"缺少基线输出 {baseline_dir}/{name}.out"}
    text = out_path.read_text(encoding="utf-8")
    if out_path.name.endswith(".grader.out"):
        # 只有 TIME 数字，不能提供配置：回退到同名 .out。
        fallback = baseline_dir / f"{name}.out"
        if fallback.is_file():
            text = fallback.read_text(encoding="utf-8")
        else:
            return {"case": name, "error": "只有 grader.out，缺少映射输出"}
    config = frontier.parse_schedule_config(text, case)
    plan = formula.build_plan(
        case, config["V"], config["P"], 1, config["psi"], config["map_rows"]
    )
    variants = sched._SMALL_VARIANTS if case.n_ops > 20_000 else sched.VARIANTS
    variant = variants[0]
    window = case.nmb
    started = time.perf_counter()
    single = _single_candidates(case, plan, variant, window)
    single_wall = time.perf_counter() - started
    search_b = _frontier_search(case, plan, max_ops_search)
    look = None
    if case.n_ops <= max_ops_search and search_b["best_info"] is not None:
        best_meta = None
        for item in search_b["candidates"]:
            info = item["measure"]
            if info["time"] == search_b["best"] and info["valid"]:
                best_meta = item
                break
        variant = None if best_meta is None or best_meta["variant"] is None else tuple(best_meta["variant"])
        policy = "auto" if best_meta is None else best_meta["policy"]
        look = _lookahead(case, plan, variant, policy)
    return {
        "case": name,
        "n_ops": case.n_ops,
        "L": case.L,
        "nmb": case.nmb,
        "V": plan.V,
        "K": plan.K,
        "is_k2v": plan.K == 2 * plan.V,
        "lb": plan.lb,
        "baseline_official_time": _official_time(baseline_dir, name),
        "single": single,
        "single_wall": round(single_wall, 5),
        "search_b": search_b,
        "lookahead": look,
    }


def _summary(rows: list[dict]) -> dict:
    def total(path):
        return sum(
            value for value in (_value(row, path) for row in rows) if isinstance(value, int)
        )

    def count_better(path_a, path_b):
        better = worse = same = 0
        for row in rows:
            a = _value(row, path_a)
            b = _value(row, path_b)
            if not isinstance(a, int) or not isinstance(b, int):
                continue
            if a < b:
                better += 1
            elif a > b:
                worse += 1
            else:
                same += 1
        return {"better": better, "worse": worse, "same": same}

    labels = (
        "base_prio", "base_early", "frontier_time_zf0", "frontier_time_zf1",
        "frontier_priority", "frontier_lazy", "frontier_gated_time",
    )
    return {
        "cases": len(rows),
        "k2v_cases": sum(1 for row in rows if row.get("is_k2v")),
        "baseline_official_sum": total("baseline_official_time"),
        "frontier_b_sum": total("search_b.best"),
        "frontier_c_sum": total("lookahead.measure.time"),
        "single_walls": {
            label: round(sum(
                _value(row, f"single.{label}.wall") or 0.0 for row in rows
            ), 4)
            for label in labels
        },
        "single_times": {label: total(f"single.{label}.time") for label in labels},
        "single_time_equal": {
            "frontier_lazy_vs_base_early": count_better(
                "single.frontier_lazy.time", "single.base_early.time"
            ),
            "frontier_time_vs_base_early": count_better(
                "single.frontier_time_zf0.time", "single.base_early.time"
            ),
            "frontier_priority_vs_base_prio": count_better(
                "single.frontier_priority.time", "single.base_prio.time"
            ),
        },
        "best_counts": {
            "frontier_b_vs_baseline_official": count_better(
                "search_b.best", "baseline_official_time"
            ),
            "frontier_c_vs_baseline_official": count_better(
                "lookahead.measure.time", "baseline_official_time"
            ),
        },
        "invalid_schedules": sum(
            1 for row in rows
            for label in labels
            if isinstance(_value(row, f"single.{label}.time"), int)
            and _value(row, f"single.{label}.valid") is False
        ),
        "gating_binding_cases": sum(
            1 for row in rows if row.get("search_b", {}).get("gating_binding")
        ),
    }


def _case_paths(args) -> list[tuple[str, Path]]:
    paths: list[tuple[str, Path]] = []
    if args.cases:
        for raw in args.cases:
            path = Path(raw)
            paths.append((path.stem, path))
    if args.set == "fast12":
        for name in FAST12:
            paths.append((name, _ROOT / "data/official/Problem/cases" / f"{name}.txt"))
    elif args.set == "samples7":
        for name in SAMPLES + ("mini",):
            paths.append((name, _ROOT / "cases" / f"{name}.in"))
        even = _ROOT / "runs/frontier/cases/mini-even/mini-even.in"
        if even.is_file():
            paths.append(("mini-even", even))
    elif args.set == "k2v6":
        for name in K2V_EXTRA:
            paths.append((name, _ROOT / "data/official/Problem/cases" / f"{name}.txt"))
    elif args.set == "battery5":
        battery = Path("/home/rainy/hackathon/data/battery/bigcases/battery")
        for name in BATTERY5:
            paths.append((name, battery / f"{name}.in"))
    seen: set[str] = set()
    unique = []
    for name, path in paths:
        if name in seen:
            continue
        seen.add(name)
        unique.append((name, path))
    return unique


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="t4 固定配置消融驱动")
    parser.add_argument("--baseline-dir", required=True)
    parser.add_argument("--set", choices=("fast12", "samples7", "k2v6", "battery5", "custom"),
                        default="custom")
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--max-ops-search", type=int, default=120_000)
    args = parser.parse_args(argv)

    baseline_dir = Path(args.baseline_dir)
    rows = []
    for name, path in _case_paths(args)[: args.max_cases or None]:
        if not path.is_file():
            rows.append({"case": name, "error": f"找不到输入 {path}"})
            print(f"SKIP {name}: 找不到 {path}", file=sys.stderr)
            continue
        row = run_case(name, path, baseline_dir, args.max_ops_search)
        rows.append(row)
        if "error" in row:
            print(f"ERROR {name}: {row['error']}", file=sys.stderr)
            continue
        print(
            f"{name:18s} n_ops={row['n_ops']:6d} K2V={int(row['is_k2v'])} "
            f"base={row['baseline_official_time']} B={row['search_b']['best']} "
            f"C={None if row['lookahead'] is None else row['lookahead']['measure']['time']} "
            f"B_wall={row['search_b']['total_wall']:.2f}s "
            f"bind={row['search_b']['gating_binding']}",
            flush=True,
        )
    summary = _summary(rows)
    payload = {"rows": rows, "summary": summary}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
