"""只读探针：b13 的窗口扫描在 W=51 → W=25 之间单调，而生产代码的候选集里没有 W=52/53。

动机：`solve._try_config` 的中等规模分支只探 `nmb//1, nmb//8, nmb//32`（= 102, 12, 3）三个窗口，
随后只保留**最好那个**（实测是 102），于是 W≈nmb/2 这一段**从来没被看到**。
本探针把 b13（P=64, V=8）在 W ∈ {51…54, 25…26, 12, 3} 上逐个重放，给出真实最优窗口。

命令：
    PYTHONPATH=. python3 runs/score-strategy-20261030/probe_b13_window52_54.py \
        > runs/score-strategy-20261030/probe_b13_window52_54.json
"""
import json
import sys

from solver import sched
from solver.casein import parse_case
from solver.solve import _plan, enumerate_configs

case = parse_case("bigcases/battery/b13-balanced-compute.in")
configs, pmaps = enumerate_configs(case)
cfg = configs[0]
plan = _plan(case, pmaps[cfg.P], cfg)
out = []
for W in (54, 53, 52, 51, 45, 40, 30, 26, 25, 24, 21, 20, 17, 13, 12, 6, 3, 1):
    for mode in ("early", "prio"):
        res = sched.schedule(case, plan, W, sched.VARIANTS[0], mode, fill_gaps=True)
        if res is None:
            continue
        ok, groups = sched.memory_usage(case, plan, res.start, res.end)
        out.append({"W": W, "mode": mode, "time": res.time, "mem_ok": ok,
                    "peak_act": max(g.peak_act for g in groups),
                    "peak_comm": max(g.peak_comm for g in groups),
                    "limit": case.M, "mexp": groups[0].mexp})
best = min((r for r in out if r["mem_ok"]), key=lambda r: r["time"])
json.dump({"case": "b13-balanced-compute", "P": cfg.P, "V": cfg.V, "nmb": case.nmb,
           "production_time": 51910524000000000, "best": best, "rows": out},
          sys.stdout, ensure_ascii=False, indent=1)
