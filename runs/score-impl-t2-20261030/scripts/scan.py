"""单用例扫描（只读探针）：在给定 (P,V,ψ,MAP) 下扫 W × 变体 × 模式，找该配置的真实最优。

用法：
    PYTHONPATH=. python3 runs/score-impl-t2-20261030/scripts/scan.py \
        --case ../bigcases/battery/b12-compute-bound.in --P 8 --V 64 --modes prio --max-wall 25
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from solver import casein, formula, sched, solve  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True)
    ap.add_argument("--P", type=int, default=None)
    ap.add_argument("--V", type=int, default=None)
    ap.add_argument("--modes", default="prio,early")
    ap.add_argument("--windows", default=None, help="逗号分隔；默认 nmb/k, k=1..12")
    ap.add_argument("--max-wall", type=float, default=25.0)
    args = ap.parse_args()
    path = (ROOT / args.case) if not Path(args.case).is_absolute() else Path(args.case)
    case = casein.parse_case(path)
    configs, pmaps = solve.enumerate_configs(case)
    if args.P is not None and args.V is not None:
        cand = [c for c in configs if c.P == args.P and c.V == args.V]
        if not cand:
            print(json.dumps({"error": "config not found", "P": args.P, "V": args.V,
                              "available": sorted({(c.P, c.V) for c in configs})}))
            return 2
        cfg = min(cand, key=lambda c: c.lb)
    else:
        cfg = configs[0]
    plan = solve._plan(case, pmaps[cfg.P], cfg)
    if args.windows:
        windows = [int(x) for x in args.windows.split(",")]
    else:
        windows = sorted({max(1, case.nmb // k) for k in range(1, 13)}, reverse=True)
    modes = args.modes.split(",")
    began = time.monotonic()
    rows = []
    for W in windows:
        for mode in modes:
            for vi, variant in enumerate(sched.VARIANTS):
                if time.monotonic() - began > args.max_wall:
                    print(json.dumps({"truncated": True, "rows": rows}, ensure_ascii=False), file=sys.stdout)
                    return 0
                started = time.monotonic()
                res = sched.schedule(case, plan, W, variant, mode)
                spent = time.monotonic() - started
                if res is None:
                    continue
                ok, groups = sched.memory_usage(case, plan, res.start, res.end)
                rows.append({"W": W, "mode": mode, "variant": vi, "time": res.time,
                             "ratio": round(res.time / plan.lb, 4), "mem_ok": ok,
                             "peak": round(max(g.used / case.M for g in groups), 4),
                             "sec": round(spent, 3)})
    rows.sort(key=lambda r: (not r["mem_ok"], r["time"]))
    print(json.dumps({"case": path.name, "P": cfg.P, "V": cfg.V, "lb": plan.lb,
                      "top": rows[:12], "n": len(rows)}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
