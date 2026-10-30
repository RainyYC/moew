"""在隔离目录直接调用 sched.schedule（绕过 _try_config），对比 P=1 组合候选。
用法: python3 direct_p1.py <pkg_root> <case.in>"""
import sys, time
root, case_in = sys.argv[1], sys.argv[2]
sys.path.insert(0, root)
from solver import sched as S, solve as SOLVE
from solver.casein import parse_case
print("provenance sched=", S.__file__, " solve=", SOLVE.__file__, flush=True)
case = parse_case(case_in)
configs, pmaps = SOLVE.enumerate_configs(case)
has_fill = 'fill_gaps' in __import__('inspect').signature(S.schedule).parameters
print("fill_gaps available:", has_fill, flush=True)
for cfg in configs[:3]:
    plan = SOLVE._plan(case, pmaps[cfg.P], cfg)
    prio = [(int(op in (7, 9)), mb + (layer if op < 4 else 2 * case.L - layer), op)
            for mb in range(case.nmb) for layer in range(case.L) for op in range(10)]
    def run(label, **kw):
        t = time.monotonic()
        r = S.schedule(case, plan, case.nmb, S.VARIANTS[0], kw.pop('mode', 'prio'), **kw)
        dt = time.monotonic() - t
        if r is None:
            print(f"  P={cfg.P} V={cfg.V} {label}: None", flush=True); return
        ok, groups = S.memory_usage(case, plan, r.start, r.end)
        print(f"  P={cfg.P} V={cfg.V} lb={plan.lb} {label}: Time={r.time} mem_ok={ok} maxmem={max(g.used for g in groups)} errs={len(S.check_schedule(case, plan, r))} {dt:.3f}s", flush=True)
    run("custom prio (fill=0)", priority=prio)
    run("custom prio (fill=1)", priority=prio, fill_gaps=True) if has_fill else print("  (fill_gaps unavailable)", flush=True)
    run("variant0 (fill=0)")
    run("variant0 (fill=1)", fill_gaps=True) if has_fill else None
