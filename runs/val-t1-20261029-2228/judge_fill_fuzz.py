#!/usr/bin/env python3
"""用**判题器**（python3 -m judge eval --json）独立验证 fill_gaps / 延后优先级路径的产物。

对每个小用例 × 若干 (V,P,ψ) 配置 × {fill_gaps 0/1} 生成输出文本，落盘后交 judge 判：
合法性、Time、内存三块。求解器自检（sched.check_schedule）只作为附带信息。
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path('/home/rainy/hackathon')
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from solver.casein import parse_case, parse_case_text  # noqa: E402
from solver.solve import enumerate_configs, _plan  # noqa: E402
from solver import sched  # noqa: E402


def judge(case_in: Path, out_path: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, '-m', 'judge', 'eval', str(case_in), str(out_path), '--json'],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    try:
        value = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {'ok': False, 'errors': ['judge-json-error', proc.stderr[-400:]]}
    return value


def make_random_case(index: int, rng: random.Random) -> Path:
    L = rng.choice([1, 2, 3, 4])
    nmb = rng.choice([1, 2, 3, 4])
    E = rng.choice([2, 4])
    S = rng.choice([1, 2, 4])
    N = rng.choice([1, 2])
    lines = [f'{N} {S} 100000000 {rng.choice([8,16,64])} {rng.choice([4,16])}',
             f'{L} {E} 0 {rng.choice([0,4])} {rng.choice([0,60])} {rng.choice([0,50])} '
             f'{rng.choice([1,2])} {nmb} {rng.choice([1,3])} {rng.choice([1,2,6])} '
             f'{rng.choice([1,2,7])} {rng.choice([0,1,3,10])} {rng.choice([0,1,5,10])}',
             f'{rng.choice([1,2])} {rng.choice([1,2])}']
    for _ in range(L):
        parts = []
        for _ in range(E):
            parts.append(str(rng.randrange(0, 5)))
        total = sum(int(x) for x in parts)
        lines.append(f'{total} ' + ' '.join(parts))
    text = '\n'.join(lines) + '\n'
    path = HERE / f'jfuzz{index}.in'
    path.write_text(text)
    return path


def main() -> int:
    rng = random.Random(777)
    cases = [ROOT / 'cases' / f'{n}.in' for n in ('ex5', 'mini')]
    cases += [HERE / f'jfuzz{i}.in' for i in range(8)]
    for i in range(8):
        make_random_case(i, rng)
    rows = []
    out_dir = HERE / 'judge-fill'
    out_dir.mkdir(exist_ok=True)
    for case_in in cases:
        try:
            case = parse_case(case_in)
            configs, pmaps = enumerate_configs(case)
        except Exception as exc:
            rows.append({'case': case_in.stem, 'error': repr(exc)})
            continue
        picks = []
        seen = set()
        for cfg in configs:
            if cfg.P in seen and len(picks) >= 3:
                continue
            seen.add(cfg.P)
            picks.append(cfg)
            if len(picks) >= 3:
                break
        for cfg in picks:
            plan = _plan(case, pmaps[cfg.P], cfg)
            priority = [
                (int(op in (7, 9)), mb + (layer if op < 4 else 2 * case.L - layer), op)
                for mb in range(case.nmb) for layer in range(case.L) for op in range(10)
            ] if case.n_ops <= 2000 else None
            variants = [(None, False), (None, True)]
            if priority is not None:
                variants += [('prio-custom', True), ('prio-custom', False)]
            for label, fill in variants:
                for mode in ('prio', 'early'):
                    kw = {}
                    if label == 'prio-custom':
                        kw['priority'] = priority
                        mode = 'prio'
                    res = sched.schedule(case, plan, case.nmb, sched.VARIANTS[0], mode,
                                         fill_gaps=fill, **kw)
                    tag = f'{case_in.stem}_V{cfg.V}P{cfg.P}_{label or "v0"}_{mode}_fill{int(fill)}'
                    if res is None:
                        rows.append({'tag': tag, 'result': 'None'})
                        continue
                    text = sched.render_output(case, plan, res, pmaps[cfg.P].rows)
                    path = out_dir / f'{tag}.out'
                    path.write_text(text)
                    verdict = judge(case_in, path)
                    rows.append({
                        'tag': tag, 'case': case_in.stem, 'V': cfg.V, 'P': cfg.P, 'lb': plan.lb,
                        'solver_time': res.time, 'solver_selfcheck_errors':
                            len(sched.check_schedule(case, plan, res)),
                        'judge_ok': verdict.get('ok'), 'judge_time': verdict.get('time'),
                        'judge_lb': verdict.get('lb'), 'n_errors': len(verdict.get('errors') or []),
                    })
    (HERE / 'judge-fill-fuzz.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    bad = [r for r in rows if r.get('judge_ok') is not True]
    mismatch = [r for r in rows if r.get('judge_ok') is True and r.get('solver_time') != r.get('judge_time')]
    print(f'rows={len(rows)} judge_fail={len(bad)} time_mismatch={len(mismatch)}')
    for r in bad[:10]:
        print('FAIL', json.dumps(r, ensure_ascii=False))
    return 0 if not bad and not mismatch else 1


if __name__ == '__main__':
    sys.exit(main())
