"""只读探针：二维切分（V 个卡组、每卡组 c 层）能否比"V=L、每卡组 1 层"更低。

题面 §3.1：PSI 只要求切点严格**递增**，块长不必相等，K=V 时一块对应一个卡组。
当 `nmb` 小、单层段长 `seg` 大时，流水线按 mb 推进，`Time ≈ (nmb+V−1)·seg`。
把 V 减小成 c 层/卡组，通常是 `Time ≈ (nmb+V−1)·c·seg` —— **更差**；
但若逐层时长被取整主导（层太轻），多层共卡会摊薄取整损失，所以逐个实测。

只跑两组 V（V=L 与 V=L/2），且只跑 prio 模式（early 在 nmb 大时单次 5–20 s，不在预算内）。

命令：
    PYTHONPATH=. python3 runs/score-strategy-20261030/probe_psi_2d.py \
        > runs/score-strategy-20261030/probe_psi_2d.json
"""
import json, sys, time as clk
from solver import formula, sched
from solver.casein import parse_case
from solver.solve import _pmap, p_candidates

CASES = ["b02-m512", "b03-m256", "b10-high-k", "b07-mixed", "b08-narrow", "b12-compute-bound"]
CUR = {"b02-m512": 542157603132750, "b03-m256": 811784777827320, "b10-high-k": 179346953034600,
       "b07-mixed": 3492805460668064, "b08-narrow": 1569450570466152,
       "b12-compute-bound": 83843497367000000}

out = []
for name in CASES:
    case = parse_case(f"bigcases/battery/{name}.in")
    rows = []
    for P in p_candidates(case):
        info = _pmap(case, P)
        per_layer = (case.E // P) * case.Z + case.Zs
        for V in sorted({64, 32, 16}):
            if V > case.L or V * P > case.R or case.L % V:
                continue
            c = case.L // V
            cuts = tuple(c * i for i in range(1, V))
            layers = [list(range((cuts[i - 1] if i else 0), (cuts[i] if i < V - 1 else case.L)))
                      for i in range(V)]
            if any(len(g) * per_layer > case.M for g in layers):
                continue
            plan = formula.build_plan_from_parts(case, V, P, 1, cuts, info.rows, info.m,
                                                 info.x, info.payload, info.durations)
            best = None
            for W in sorted({case.nmb, max(1, case.nmb // 2), max(1, case.nmb // 8)}):
                t0 = clk.monotonic()
                res = sched.schedule(case, plan, W, sched.VARIANTS[0], "prio", fill_gaps=True)
                el = clk.monotonic() - t0
                if res is None:
                    continue
                ok, _ = sched.memory_usage(case, plan, res.start, res.end)
                row = {"W": W, "time": res.time, "mem_ok": ok, "sec": round(el, 3),
                       "V": V, "P": P, "c": c, "lb": plan.lb}
                if best is None or (row["mem_ok"] and not best["mem_ok"]) or (
                        row["mem_ok"] == best["mem_ok"] and row["time"] < best["time"]):
                    best = row
            if best:
                rows.append(best)
    rows.sort(key=lambda r: (not r["mem_ok"], r["time"]))
    out.append({"case": name, "nmb": case.nmb, "current_time": CUR[name], "rows": rows[:8]})
    sys.stderr.write(f"done {name}\n")
    sys.stderr.flush()
json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
