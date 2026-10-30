"""只读实验：W=20（≈nmb/5）在中等规模用例上的普适性 + 隔离副本里验证 b13 的收益。

两件事：
1. 对 b02/b03/b07/b08/b10/b12 在 W=nmb 与 W≈nmb/5 各跑一次（prio 与 early），看是否普遍更好；
2. 在**不改生产文件**的前提下，用 monkeypatch 把 `sched.schedule` 收到的 early 窗口
   固定为 20，跑一次完整的 `solve_case`（这会改变搜索轨迹，不只是单个点），把输出写到
   本目录供官方 judge 复核。

命令：
    PYTHONPATH=. python3 runs/score-strategy-20261030/probe_b13_w20.py \
        > runs/score-strategy-20261030/probe_b13_w20.json
"""
import json
import sys

from solver import sched
from solver.casein import parse_case
from solver.solve import _plan, enumerate_configs

CASES = ["b02-m512", "b03-m256", "b07-mixed", "b08-narrow", "b10-high-k", "b12-compute-bound",
         "b04-m96", "b11-short-l"]
out = []
for name in CASES:
    case = parse_case(f"bigcases/battery/{name}.in")
    configs, pmaps = enumerate_configs(case)
    cfg = configs[0]
    plan = _plan(case, pmaps[cfg.P], cfg)
    row = {"case": name, "P": cfg.P, "V": cfg.V, "nmb": case.nmb, "variants": []}
    for W in sorted({case.nmb, max(1, case.nmb // 5)}):
        for mode in ("early", "prio"):
            if mode == "early" and case.n_ops > 200_000:
                continue  # 实测 64 万 op 上 early 单次 2.6–21.6 s，不进 10 s 预算
            res = sched.schedule(case, plan, W, sched.VARIANTS[0], mode, fill_gaps=True)
            if res is None:
                continue
            ok, groups = sched.memory_usage(case, plan, res.start, res.end)
            row["variants"].append({"W": W, "mode": mode, "time": res.time, "mem_ok": ok,
                                    "peak_act": max(g.peak_act for g in groups)})
    out.append(row)
    sys.stderr.write(f"done {name}\n")
json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
