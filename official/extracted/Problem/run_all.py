#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run a submission on all 50 cases and print TIME and CPU time per case.

Usage
-----
    python3 run_all.py
    python3 run_all.py --cmd "python3 solution.py"
    python3 run_all.py --cmd "python3 solution.py --budget 9.5"
    python3 run_all.py --cmd "python3 solution.py {case}" --timeout 10

The solver command is appended with the case path unless it contains ``{case}``.
The wall-clock limit is 10 seconds by default; the grader's own time is not
counted.  CPU time is the solver's child-process CPU time (user + system).
"""

import argparse
import os
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    import resource
except ImportError:  # pragma: no cover - Windows fallback
    resource = None

ROOT = Path(__file__).resolve().parent
DEFAULT_CMD = '{} sample_solution.py --budget 9.0'.format(shlex.quote(sys.executable))


def child_cpu():
    """Cumulative CPU seconds of all reaped children, or None."""
    if resource is None:
        return None
    r = resource.getrusage(resource.RUSAGE_CHILDREN)
    return r.ru_utime + r.ru_stime


def as_text(value):
    if value is None:
        return ''
    if isinstance(value, bytes):
        return value.decode('utf-8', 'replace')
    return value


def build_command(template, case):
    if '{case}' in template:
        return shlex.split(template.replace('{case}', str(case)))
    return shlex.split(template) + [str(case)]


def grade(case, output):
    with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False,
                                     encoding='utf-8') as f:
        f.write(output)
        path = f.name
    try:
        r = subprocess.run(
            [sys.executable, str(ROOT / 'grader.py'), str(case), path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=10,
        )
        text = (r.stdout or '').strip()
        line = text.splitlines()[-1].strip() if text else ''
        if r.returncode == 0 and line.isdigit():
            return int(line), ''
        return None, line or (r.stderr or '').strip()[:120]
    except Exception as e:
        return None, str(e)[:120]
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def run_case(cmd_template, case, timeout):
    cmd = build_command(cmd_template, case)
    before = child_cpu()
    t0 = time.perf_counter()
    status = 'OK'
    stdout = stderr = ''
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, timeout=timeout)
        stdout, stderr = p.stdout or '', p.stderr or ''
        if p.returncode != 0:
            status = 'ERROR'
    except subprocess.TimeoutExpired as e:
        status = 'TO'
        stdout = as_text(e.stdout)
        stderr = as_text(e.stderr)
    except Exception as e:
        status = 'ERROR'
        stderr = str(e)
    wall = time.perf_counter() - t0
    after = child_cpu()
    cpu = None if before is None or after is None else max(0.0, after - before)

    value = None
    detail = ''
    if status == 'OK':
        value, detail = grade(case, stdout)
        if value is None:
            status = 'INVALID'
    return {
        'case': case.name,
        'status': status,
        'time': value,
        'cpu': cpu,
        'wall': wall,
        'detail': detail,
        'stderr': stderr[-160:],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--cmd', default=DEFAULT_CMD,
                    help='solver command; case path is appended unless {case} is present')
    ap.add_argument('--timeout', type=float, default=10.0,
                    help='wall-clock limit per case in seconds (default: 10)')
    ap.add_argument('--cases', default=str(ROOT / 'cases'),
                    help='directory containing the input .txt files')
    args = ap.parse_args(argv)

    case_dir = Path(args.cases)
    cases = sorted(case_dir.glob('*.txt'))
    if not cases:
        print('No .txt cases found in {}'.format(case_dir), file=sys.stderr)
        return 2
    if len(cases) != 50:
        print('warning: expected 50 cases, found {}'.format(len(cases)),
              file=sys.stderr)

    print('solver: {}'.format(args.cmd))
    print('cases:  {} ({} files)'.format(case_dir, len(cases)))
    print('limit:  {:.1f} s per case (solver only; grader time excluded)'.format(args.timeout))
    print()
    print('{:<42} {:>9} {:>10} {:>9} {:>9}'.format(
        'case', 'status', 'TIME', 'CPU(s)', 'wall(s)'))
    print('-' * 84)

    rows = []
    for case in cases:
        row = run_case(args.cmd, case, args.timeout)
        rows.append(row)
        print('{:<42} {:>9} {:>10} {:>9} {:>9}'.format(
            row['case'][:42],
            row['status'],
            '-' if row['time'] is None else str(row['time']),
            '-' if row['cpu'] is None else '{:.3f}'.format(row['cpu']),
            '{:.3f}'.format(row['wall']),
        ))
        if row['status'] not in ('OK', 'TO'):
            reason = (row['detail'] or row['stderr']).strip()
            if reason:
                print('  {}: {}'.format(row['status'], reason.replace('\n', ' ')[:120]))

    print()
    valid = [r for r in rows if r['status'] == 'OK']
    counts = {}
    for r in rows:
        counts[r['status']] = counts.get(r['status'], 0) + 1
    print('summary: ' + ', '.join('{}={}'.format(k, counts[k]) for k in sorted(counts)))
    if valid:
        times = [r['time'] for r in valid]
        cpus = [r['cpu'] for r in valid if r['cpu'] is not None]
        print('TIME: valid={}/{}  mean={:.1f}  min={}  max={}'.format(
            len(valid), len(rows), sum(times) / len(times), min(times), max(times)))
        if cpus:
            print('CPU(s): mean={:.3f}  max={:.3f}'.format(
                sum(cpus) / len(cpus), max(cpus)))
    return 0 if len(valid) == len(rows) else 1


if __name__ == '__main__':
    sys.exit(main())
