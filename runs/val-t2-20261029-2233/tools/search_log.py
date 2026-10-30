"""在**隔离**目录里跑 solve_case（带 log 回调），记录搜索轨迹。
用法: python3 search_log.py <pkg_root> <case.in> [budget]
pkg_root 下必须有 solver/ 包。"""
import sys, time
root, case_in = sys.argv[1], sys.argv[2]
budget = float(sys.argv[3]) if len(sys.argv) > 3 else 6.5
sys.path.insert(0, root)
import solver.sched as S, solver.solve as SOLVE, solver.solve_all as SA, solver.casein as CI
from solver.casein import parse_case
print(f"provenance sched={S.__file__} solve={SOLVE.__file__} solve_all={SA.__file__} casein={CI.__file__}", flush=True)
case = parse_case(case_in)
configs, pmaps = SOLVE.enumerate_configs(case)
print("n_ops", case.n_ops, "nconfigs", len(configs), flush=True)
print("configs[0]:", f"P={configs[0].P} V={configs[0].V} lb={configs[0].lb} lb*fill={configs[0].lb*(case.nmb+configs[0].V-1)//case.nmb}", flush=True)
print("configs[1]:", f"P={configs[1].P} V={configs[1].V} lb={configs[1].lb}", flush=True)
byp = {}
for c in configs:
    byp.setdefault(c.P, [1 << 62, 0, 0])
    byp[c.P][0] = min(byp[c.P][0], c.lb); byp[c.P][1] = max(byp[c.P][1], c.lb); byp[c.P][2] += 1
print("per-P lb(min,max,#cfg):", {k: v for k, v in sorted(byp.items())}, flush=True)
print("sorted key of configs[0]:", configs[0].lb * max(1, case.nmb + configs[0].V - 1) // case.nmb, flush=True)
print("min raw lb over all configs:", min(c.lb for c in configs), flush=True)
print("min raw lb over configs[1:]:", min(c.lb for c in configs[1:]), flush=True)
tag = []
t0 = time.monotonic()
sol = SOLVE.solve_case(case, budget=budget, log=lambda line: (print(f"  {time.monotonic()-t0:6.2f}s {line}", flush=True), tag.append(line)))
print(f"solve wall {time.monotonic()-t0:.2f}s", flush=True)
print("RESULT grid P=%s V=%s Time=%s lb=%s mode=%s window=%s" % (sol.P, sol.V, sol.time, sol.lb, sol.mode, sol.window), flush=True)
print("log lines:", len(tag), flush=True)
