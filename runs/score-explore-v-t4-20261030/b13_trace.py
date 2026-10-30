"""t4：用**冻结快照**复现 b13 的 4.2984846e16 候选，并记录它的完整构造参数 + 默认入口为何漏掉。

只读：源码快照来自 runs/score-explore-v-t4-20261030/snapshot/（SHA256SUMS 固定），
在该快照的进程内跑 monkeypatch（与 t1 的 b13_patch.py 等价，但不写生产文件）。

输出：
  * 每次被接受的改进：P/V/psi/窗口/variant/mode/Time/lb
  * 每个配置在被调用时的 lb、与当时 best 的关系（判断 _dominated_over 早退）
  * 最终输出的 P/V/psi/W/variant/mode 与官方 grader TIME

用法：PYTHONPATH=. python3 runs/score-explore-v-t4-20261030/b13_trace.py --early-window 20
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAP = ROOT / "runs/score-explore-v-t4-20261030/snapshot"
sys.path.insert(0, str(SNAP))
sys.path.insert(1, str(ROOT))
from solver import casein, sched, solve  # noqa: E402  —— 从冻结快照导入

WORK = ROOT / "runs/score-explore-v-t4-20261030"
CASE = ROOT / "bigcases/battery/b13-balanced-compute.in"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--early-window", type=int, default=0, help=">0 时把 early 的窗口钉成这个值")
    ap.add_argument("--budget", type=float, default=6.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace: list[dict] = []
    orig_schedule = sched.schedule
    orig_try = solve._try_config

    def traced_schedule(case, plan, window, variant, mode="prio", priority=None, comm_gap=0,
                        fill_gaps=False):
        if args.early_window and mode == "early":
            window = args.early_window
        res = orig_schedule(case, plan, window, variant, mode, priority=priority,
                            comm_gap=comm_gap, fill_gaps=fill_gaps)
        if res is not None:
            trace.append({"kind": "schedule", "P": plan.P, "V": plan.V, "psi": list(plan.psi),
                          "W": window, "mode": mode, "variant": list(variant),
                          "time": res.time, "lb": plan.lb})
        return res

    sched.schedule = traced_schedule
    budget_factor = {"v": 1.0}

    def traced_try(case, config, info, best, deadline, big, log, cost, debug=None, cheap_probe=False):
        budget_factor["v"] = getattr(traced_try, "budget_scale", 1.0)
        return orig_try(case, config, info, best, deadline, big, log, cost, debug, cheap_probe)

    _orig_scaled = traced_schedule

    def traced_schedule_scaled(case, plan, window, variant, mode="prio", priority=None, comm_gap=0,
                               fill_gaps=False):
        if args.early_window and mode == "early":
            window = args.early_window
        res = orig_schedule(case, plan, window, variant, mode, priority=priority,
                            comm_gap=comm_gap, fill_gaps=fill_gaps)
        if res is not None:
            trace.append({"kind": "schedule", "P": plan.P, "V": plan.V, "psi": list(plan.psi),
                          "W": window, "mode": mode, "variant": list(variant),
                          "time": res.time, "lb": plan.lb})
        return res

    sched.schedule = traced_schedule_scaled
    try:
        case = casein.parse_case(CASE)
        sol = solve.solve_case(case, budget=args.budget, log=lambda s: trace.append({"kind": "log", "msg": s}))
    finally:
        sched.schedule = orig_schedule

    accepted, best_so_far = [], None
    for item in trace:
        if item["kind"] != "schedule":
            continue
        if best_so_far is None or item["time"] < best_so_far:
            best_so_far = item["time"]
            accepted.append(item)
    # 每个配置第一次被尝试时的 lb 与当时 best 的关系（判断 _dominated_over / lb>=best 早退）
    seen_cfg, cfg_ctx = set(), []
    for item in trace:
        if item["kind"] != "schedule":
            continue
        key = (item["P"], item["V"])
        if key in seen_cfg:
            continue
        seen_cfg.add(key)
        cfg_ctx.append({"P": item["P"], "V": item["V"], "first_time": item["time"],
                        "lb": item["lb"], "lb_over_first": round(item["lb"] / item["time"], 3)})
    text = sol.text
    out_file = WORK / "out" / f"b13.trace-w{args.early_window or 'default'}.out"
    out_file.write_text(text)
    g = subprocess.run([sys.executable, str(ROOT / "official/extracted/Problem/grader.py"),
                        str(CASE), str(out_file)], capture_output=True, text=True)
    line = (g.stdout or "").strip().splitlines()
    grade = int(line[-1]) if line and line[-1].strip().isdigit() else None
    result = {"early_window": args.early_window or "default", "budget": args.budget,
              "final": {"P": sol.P, "V": sol.V, "K": sol.K, "psi": list(sol.psi),
                        "window": sol.window, "mode": sol.mode, "variant": list(sol.variant),
                        "time": sol.time, "lb": sol.lb},
              "grader_time": grade, "accepted_path": accepted, "configs_first_lb": cfg_ctx,
              "n_schedules": sum(1 for t in trace if t["kind"] == "schedule")}
    Path(args.out).write_text(json.dumps(result, indent=1, ensure_ascii=False))
    print(json.dumps({k: result[k] for k in ("early_window", "final", "grader_time", "n_schedules")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
