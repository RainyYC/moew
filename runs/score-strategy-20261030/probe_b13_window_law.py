"""只读探针：b13 的 8% 能不能被"容器无关"的规则拿到。

已确认（`probe_b13_ab.json`）：b13 的最优是 `early` + **中等窗口 W≈nmb/5**（4.757e16），
而不是生产保留的 `W=nmb`（5.191e16），也不是 `W=nmb/8`（5.789e16）。`prio` 在这个用例上
任何窗口都差 5–8 倍。问题：这条规律能不能从**输入特征**推出来，而不是硬编码 W？

本探针对同一 (P,V,ψ,MAP) 扫一组窗口 × {prio, early}，输出整条曲线，并给出
"最优窗口 / nmb" 与几个可观测特征（`peak_act/nmb`、`Time/lb`、`seg` 构成）的关系。

命令：
    PYTHONPATH=. python3 runs/score-strategy-20261030/probe_b13_window_law.py \
        > runs/score-strategy-20261030/probe_b13_window_law.json
"""
import json
import sys

from solver import formula, sched
from solver.casein import parse_case
from solver.solve import _plan, enumerate_configs

case = parse_case("bigcases/battery/b13-balanced-compute.in")
configs, pmaps = enumerate_configs(case)
cfg = configs[0]
plan = _plan(case, pmaps[cfg.P], cfg)
comp = sum(sum(plan.durations[l][i] for i in formula.COMP_OPS) for l in plan.layers_of_group[0])
comm = sum(sum(plan.durations[l][i] for i in formula.COMM_OPS) for l in plan.layers_of_group[0])
rows = []
for W in sorted({102, 85, 68, 51, 42, 34, 30, 26, 22, 20, 18, 16, 14, 12, 10, 8, 6, 4, 2, 1}):
    for mode in ("early", "prio"):
        res = sched.schedule(case, plan, W, sched.VARIANTS[0], mode, fill_gaps=True)
        if res is None:
            continue
        ok, groups = sched.memory_usage(case, plan, res.start, res.end)
        rows.append({"W": W, "mode": mode, "time": res.time, "mem_ok": ok,
                     "ratio_to_lb": res.time / plan.lb,
                     "peak_act": max(g.peak_act for g in groups)})
best = min((r for r in rows if r["mem_ok"]), key=lambda r: r["time"])
json.dump({
    "case": "b13-balanced-compute", "P": cfg.P, "V": cfg.V, "nmb": case.nmb,
    "layers_per_group": len(plan.layers_of_group[0]),
    "comp_per_group": comp, "comm_per_group": comm,
    "seg": max(comp, comm), "lb": plan.lb, "nmb_x_seg": case.nmb * max(comp, comm),
    "production_time": 51910524000000000,
    "best": best, "best_W_over_nmb": best["W"] / case.nmb,
    "rows": rows,
}, sys.stdout, ensure_ascii=False, indent=1)
