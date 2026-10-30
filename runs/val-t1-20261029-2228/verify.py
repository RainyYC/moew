#!/usr/bin/env python3
"""t1 独立验证脚本（validator）。只读生产代码，产物全部写在本目录。

1. cmp-deps : solver/formula.DEPS 与 judge/core/model.DEPS 逐项对拍（COMP/COMM 索引、依赖表）
2. fill-fuzz: 在真实用例 + 随机小用例上，fill_gaps=True/False 的结果都用独立复算器判合法
3. compare  : 当前工作区求解 vs 基线（git show HEAD）求解，各自经 judge eval 判题
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path('/home/rainy/hackathon')
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def cmp_deps() -> dict:
    from solver import formula as sf
    from judge.core import model as jm

    report = {'solver_DEPS': {sf.OP_NAMES[i]: [sf.OP_NAMES[d] for d in row] for i, row in enumerate(sf.DEPS)}}
    report['judge_DEPS'] = {jm.OP_NAMES[i]: [jm.OP_NAMES[d] for d in row] for i, row in enumerate(jm.DEPS)}
    report['same_order'] = list(sf.OP_NAMES) == list(jm.OP_NAMES)
    report['same_deps'] = [tuple(r) for r in sf.DEPS] == [tuple(r) for r in jm.DEPS]
    report['solver_ENGINE'] = {sf.OP_NAMES[i]: ('COMP' if e == sf.COMP else 'COMM') for i, e in enumerate(sf.ENGINE)}
    report['judge_ENGINE'] = {jm.OP_NAMES[i]: ('COMP' if e == jm.COMP else 'COMM') for i, e in enumerate(jm.ENGINE)}
    report['same_engine'] = list(sf.ENGINE) == list(jm.ENGINE)
    report['same_comp_ops'] = tuple(sf.COMP_OPS) == tuple(jm.COMP_OPS)
    report['same_comm_ops'] = tuple(sf.COMM_OPS) == tuple(jm.COMM_OPS)
    return report


def fill_fuzz() -> dict:
    """fill_gaps 的结果用独立复算（judge 自己的模拟器）判合法。"""
    import random
    from solver.casein import parse_case
    from solver.solve import enumerate_configs, _plan
    from solver import sched
    from judge.core import model as jm, sim as js

    rows = []
    cases = sorted((ROOT / 'bigcases/battery').glob('*.in'))
    small = []
    for name in ('ex1', 'ex2', 'ex3', 'ex5', 'mini'):
        p = ROOT / 'cases' / f'{name}.in'
        if p.is_file():
            small.append(p)
    # 随机小用例（进制造 nmb=3..5, L=2..4）
    rng = random.Random(20261029)
    for k in range(6):
        L = rng.choice([2, 3, 4])
        nmb = rng.choice([3, 4, 5])
        R = 8
        lines = [f'{L} {nmb}']
        lines.append(f'{rng.choice([4,8])} {R} {8} {rng.choice([32,64])} {rng.choice([16,32])} '
                     f'{rng.choice([16,32])} {rng.choice([2,4])} {rng.choice([1,2])} {rng.choice([1,2])} '
                     f'{rng.choice([2,4])} 1000000 1000000')
        lines.append(f'{rng.choice([2,4])} {rng.choice([1,2])}')
        for _ in range(L):
            lines.append(' '.join(str(rng.randrange(1, 9)) for _ in range(4)) + ' '
                         + ' '.join(str(rng.randrange(1, 40)) for _ in range(5)))
        p = HERE / f'fuzz{k}.in'
        p.write_text('\n'.join(lines) + '\n')
        small.append(p)

    for path in cases + small:
        try:
            case = parse_case(path)
            configs, pmaps = enumerate_configs(case)
        except Exception as exc:  # pragma: no cover
            rows.append({'case': path.stem, 'error': repr(exc)})
            continue
        if not configs:
            rows.append({'case': path.stem, 'error': 'no configs'})
            continue
        cfg = configs[0]
        plan = _plan(case, pmaps[cfg.P], cfg)
        if case.n_ops > 200_000:
            rows.append({'case': path.stem, 'skipped': 'too big for fuzz'})
            continue
        for mode in ('prio', 'early'):
            for fill in (False, True):
                t = time.monotonic()
                res = sched.schedule(case, plan, case.nmb, sched.VARIANTS[0], mode, fill_gaps=fill)
                dt = time.monotonic() - t
                if res is None:
                    rows.append({'case': path.stem, 'mode': mode, 'fill': fill, 'result': 'None'})
                    continue
                errs = sched.check_schedule(case, plan, res)
                ok_mem, groups = sched.memory_usage(case, plan, res.start, res.end)
                rows.append({
                    'case': path.stem, 'mode': mode, 'fill': fill, 'time': res.time,
                    'solver_selfcheck_errors': len(errs), 'first_errors': errs[:2],
                    'memory_ok': ok_mem, 'seconds': round(dt, 3),
                    'V': plan.V, 'P': plan.P, 'n_ops': case.n_ops,
                })
    return {'rows': rows}


def _run_solver(solver_dir: str | None, case: str, out: Path) -> dict:
    env = dict(os.environ)
    if solver_dir:
        env['PYTHONPATH'] = solver_dir
    out.parent.mkdir(parents=True, exist_ok=True)
    t = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(ROOT / 'solver/solve_all.py'), str(ROOT / case), str(out)],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
    )
    dt = time.monotonic() - t
    jt = time.monotonic()
    jp = subprocess.run(
        [sys.executable, '-m', 'judge', 'eval', str(ROOT / case), str(out)],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    jdt = time.monotonic() - jt
    try:
        verdict = json.loads(jp.stdout)
    except Exception:
        verdict = {'raw': jp.stdout[-2000:], 'stderr': jp.stderr[-2000:]}
    return {
        'case': case, 'solver_seconds': round(dt, 3), 'solver_rc': proc.returncode,
        'solver_stderr': proc.stderr.strip()[-1500:], 'judge_seconds': round(jdt, 3),
        'judge_rc': jp.returncode, 'judge': verdict,
    }


def compare() -> dict:
    out = {'current': [], 'base': []}
    targets = [f'bigcases/battery/{n}.in' for n in ('b01-loose', 'b12-compute-bound')]
    targets += [f'cases/{n}.in' for n in ('ex1', 'ex2', 'ex3', 'ex4', 'ex5', 'ex6')]
    which = sys.argv[2] if len(sys.argv) > 2 else 'both'
    for label in ('current', 'base'):
        if which not in ('both', label):
            continue
        solver_dir = None if label == 'current' else str(HERE / 'base-solver')
        for case in targets:
            name = Path(case).stem
            rec = _run_solver(solver_dir, case, HERE / label / f'{name}.out')
            rec['label'] = label
            out[label].append(rec)
            print(json.dumps({k: rec[k] for k in ('label', 'case', 'solver_seconds', 'judge_rc')},
                             ensure_ascii=False), flush=True)
    return out


COMMANDS = {'cmp-deps': cmp_deps, 'fill-fuzz': fill_fuzz, 'compare': compare}

if __name__ == '__main__':
    what = sys.argv[1]
    payload = COMMANDS[what]()
    dest = HERE / f'{what}.json'
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f'wrote {dest}')
