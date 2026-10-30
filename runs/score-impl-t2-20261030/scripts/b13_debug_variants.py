"""只读诊断：在 b13 上按生产路径重放"探窗之后"的变体扫描，看每个 (W, mode, variant) 的时间。

回答：探窗定位到 W=20/early 之后，变体扫描到底扫了哪些组合、最好的为什么仍是 1.186×lb。
用法：PYTHONPATH=. python3 runs/score-impl-t2-20261030/scripts/b13_debug_variants.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from solver import casein, sched, solve  # noqa: E402

case = casein.parse_case(ROOT / "bigcases/battery/b13-balanced-compute.in")
configs, pmaps = solve.enumerate_configs(case)
cfg = configs[0]
plan = solve._plan(case, pmaps[cfg.P], cfg)
rows = []
for W in (20, 51, 102, 34):
    for mode in ("early", "prio"):
        for vi, variant in enumerate(sched.VARIANTS):
            if mode == "early" and W >= 68 and vi > 2:
                continue
            res = sched.schedule(case, plan, W, variant, mode)
            ok, groups = sched.memory_usage(case, plan, res.start, res.end)
            rows.append({"W": W, "mode": mode, "variant": vi, "time": res.time,
                         "ratio": round(res.time / plan.lb, 4), "mem_ok": ok})
rows.sort(key=lambda r: (not r["mem_ok"], r["time"]))
print(json.dumps({"lb": plan.lb, "top": rows[:10]}, indent=1))
