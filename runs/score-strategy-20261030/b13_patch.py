"""策略 1 的隔离实验（只读生产代码，不写缓存、不改文件）：

在**进程内**把 `sched.schedule` 收到的 `early` 窗口固定为 20，跑完整的 `solve_case(b13)`。
意图不是提解，而是证明"窗口候选"与"网格回退"的因果链：
`(P=64,V=8)` 用 W≈nmb/5 能算出 4.757e16 ⇒ `(P=32,V=16)` 才有机会进入搜索并胜出（4.298e16）。

（这份脚本是为了让 REPORT.md §7 的复现命令可点；它与当时跑出 b13-w20/b13.out 的
一次性命令等价。）

命令：PYTHONPATH=. python3 runs/score-strategy-20261030/b13_patch.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import solver.solve as solve
from solver import sched
from solver.casein import parse_case

OUT = Path("runs/score-strategy-20261030/b13-w20/b13.out")
FIXED_W = 20
original = sched.schedule


def patched(case, plan, window, variant, mode="prio", priority=None, comm_gap=0, fill_gaps=False):
    if mode == "early":
        window = FIXED_W
    return original(case, plan, window, variant, mode, priority, comm_gap, fill_gaps)


sched.schedule = patched
try:
    case = parse_case("bigcases/battery/b13-balanced-compute.in")
    solution = solve.solve_case(case, budget=6.0, log=lambda line: print(line, file=sys.stderr))
finally:
    sched.schedule = original

if solution is None:
    raise SystemExit("no legal solution")
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(solution.text)
print(f"solver_time={solution.time} V={solution.V} P={solution.P} "
      f"K={solution.K} window={solution.window} mode={solution.mode} -> {OUT}")
