"""把 direct 候选渲染成输出文本并交给 judge 独立判定。
用法: python3 emit_candidate.py <pkg_root> <case.in> <out_base>"""
import sys, json, subprocess, time
root, case_in, out_base = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, root)
from solver import sched as S, solve as SOLVE
from solver.casein import parse_case
case = parse_case(case_in)
configs, pmaps = SOLVE.enumerate_configs(case)
want = {  # (P, mode, priority_kind, fill)
    'b01-loose': [(1, 'prio', 'custom', True), (1, 'prio', 'custom', False), (1, 'early', 'v0', False)],
    'b12-compute-bound': [(8, 'prio', 'custom', True), (8, 'early', 'v0', False), (8, 'prio', 'v0', True), (4, 'prio', 'custom', True)],
}[case.name]
for cfg in configs:
    for (P, mode, kind, fill) in want:
        if cfg.P != P:
            continue
        plan = SOLVE._plan(case, pmaps[cfg.P], cfg)
        prio = [(int(op in (7, 9)), mb + (layer if op < 4 else 2 * case.L - layer), op)
                for mb in range(case.nmb) for layer in range(case.L) for op in range(10)] if kind == 'custom' else None
        r = S.schedule(case, plan, case.nmb, S.VARIANTS[0], mode, priority=prio, fill_gaps=fill)
        if r is None:
            print('None', flush=True); continue
        path = f'{out_base}_P{cfg.P}_{mode}_{kind}_fill{int(fill)}.out'
        open(path, 'w').write(S.render_output(case, plan, r, pmaps[cfg.P].rows))
        p = subprocess.run([sys.executable, '-m', 'judge', 'eval', case_in, path, '--json'],
                           cwd='/home/rainy/hackathon', capture_output=True, text=True)
        d = json.loads(p.stdout)
        g = d['groups']
        print(f"P={cfg.P} mode={mode} kind={kind} fill={int(fill)} solver_Time={r.time} judge_ok={d['ok']} judge_Time={d['time']} lb={d['lb']} max_mem={max(x['mexp']+x['movl']+x['mact'] for x in g)} errors={len(d['errors'])} path={path}", flush=True)
        break
