import sys
from solver import sched, solve, solve_all, formula
for m in (sched, solve, solve_all, formula):
    print(f"{m.__name__:18s} {m.__file__}")
print("cwd =", __import__('os').getcwd())
print("sys.path[:3] =", sys.path[:3])
