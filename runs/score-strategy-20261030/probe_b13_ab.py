"""只读 A/B：b13 的收益到底来自"窗口"还是"填隙/出堆模式"。

对 b13（P=64, V=8, K=8）在 W=102（生产保留值）与 W≈nmb/5 上分别跑
{prio, early} × {fill_gaps=False, True}，并同时报内存，回答：
  * 生产代码为什么只拿到 W=102 early 的 5.191e16；
  * W=20 early 的 4.757e16 是"窗口"给的，还是"填隙"给的。

命令：PYTHONPATH=. python3 runs/score-strategy-20261030/probe_b13_ab.py \
        > runs/score-strategy-20261030/probe_b13_ab.json
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
rows = []
for W in (102, 51, 20):
    for mode in ("early", "prio"):
        for fill in (False, True):
            res = sched.schedule(case, plan, W, sched.VARIANTS[0], mode, fill_gaps=fill)
            if res is None:
                continue
            ok, groups = sched.memory_usage(case, plan, res.start, res.end)
            rows.append({"W": W, "mode": mode, "fill_gaps": fill, "time": res.time,
                         "mem_ok": ok, "peak_act": max(g.peak_act for g in groups),
                         "peak_comm": max(g.peak_comm for g in groups)})
rows.sort(key=lambda r: (not r["mem_ok"], r["time"]))
json.dump({"case": "b13-balanced-compute", "P": cfg.P, "V": cfg.V, "nmb": case.nmb,
           "production_time": 51910524000000000, "rows": rows}, sys.stdout,
          ensure_ascii=False, indent=1)
