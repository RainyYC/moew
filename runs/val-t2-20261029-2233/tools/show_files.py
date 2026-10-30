import os, sys
from solver import sched, solve, solve_all, formula, casein
for m in (sched, solve, solve_all, formula, casein):
    print(f"{m.__name__:18s} {m.__file__}")
print("cwd =", os.getcwd())
print("sys.path[:3] =", sys.path[:3])
