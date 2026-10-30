"""Process-local 追踪 solve._try_config：进/出、cost.est、best.time、返回值。
用法: python3 trace_tryconfig.py <pkg_root> <case.in> [budget]
不修改任何生产文件；仅在本进程内包装函数。"""
import sys, time
root, case_in = sys.argv[1], sys.argv[2]
budget = float(sys.argv[3]) if len(sys.argv) > 3 else 6.5
sys.path.insert(0, root)
from solver import solve as SOLVE, sched as S
from solver.casein import parse_case

orig = SOLVE._try_config
t00 = time.monotonic()
def wrapped(case, config, info, best, deadline, big, log, cost):
    t = time.monotonic() - t00
    print(f"[{t:6.2f}s] -> _try_config P={config.P} V={config.V} lb={config.lb} best={best.time if best else None} est={cost.get('est'):.3f} deadline_in={deadline-t00:.2f}s", flush=True)
    out = orig(case, config, info, best, deadline, big, log, cost)
    t = time.monotonic() - t00
    print(f"[{t:6.2f}s] <- _try_config P={config.P} V={config.V} best_now={out.time if out else None} mode={out.mode if out else None} (best_changed={out is not best})", flush=True)
    return out
SOLVE._try_config = wrapped
print("provenance solve=", SOLVE.__file__, " sched=", S.__file__, flush=True)
case = parse_case(case_in)
sol = SOLVE.solve_case(case, budget=budget, log=lambda line: print(f"  log {time.monotonic()-t00:6.2f}s {line[:120]}", flush=True))
print("FINAL", sol.P, sol.V, sol.time, sol.lb, sol.mode, flush=True)
