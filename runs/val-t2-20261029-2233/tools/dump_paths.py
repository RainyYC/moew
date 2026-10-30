"""用 runpy 复刻 `python3 solver/solve_all.py <args>` 的模块解析结果（不执行求解）。
仅用于证明 t1 基线影子导入的实际效果。"""
import runpy, sys
sys.argv = ['solver/solve_all.py'] + sys.argv[1:]
# solve_all.py 顶部会把仓库根插入 sys.path[0]；这里执行到导入阶段即可观察解析结果
runpy.run_path('/home/rainy/hackathon/solver/solve_all.py', run_name='__not_main__')
import solver, solver.sched, solver.solve
print('solver       ->', solver.__file__)
print('solver.sched ->', solver.sched.__file__)
print('solver.solve ->', solver.solve.__file__)
