# MoE 分块与重叠吞吐优化

赛题《满足内存约束的 MoE 分块与重叠吞吐优化》的完整实现：**判题核心 + 求解器 + 独立复算**，
并在官方评分集上给出可复现的成绩。

> **成绩（官方 50 用例，官方 `grader.py` 判分）**
> - **50/50 全部合法**，均值 `TIME` 较官方样例解 **降低 31.9%**（31,765,363 → 21,627,400），
>   几何平均比值 **0.716**，逐例更优
> - 官方 6 个样例**全部经 CP-SAT 证明为全局最优**（560 / 4880 / 6072 / 3200 / 416 / 1696）
> - 判题核心与官方 `grader.py` 在 50 例上**逐例 `TIME` 完全一致**
> - 墙钟：均值约 6.0 s、峰值 **7.6 s**（题面限 10 s），零超时
>
> 调度内核（事件驱动就绪前沿）已合入并默认开启；放置与 fill_boost 三项优化合计约 −0.8%，见
> [`docs/reports/report-placement-fillboost.md`](docs/reports/report-placement-fillboost.md)

**先读 [`docs/reports/solution-report.md`](docs/reports/solution-report.md)** —— 完整解题报告
（问题建模与 LaTeX 公式、搜索空间、调度内核、成绩、**被否决方案单独一章**）。

配套：
[`docs/reports/report-placement-fillboost.md`](docs/reports/report-placement-fillboost.md)（放置与 fill_boost 的细节）、
[`docs/reviews/eval-opt-placement-partition-20261030.md`](docs/reviews/eval-opt-placement-partition-20261030.md)（分支合入评估）、
[`docs/reports/reference-v5-and-python-port.md`](docs/reports/reference-v5-and-python-port.md)（C++ 参考实现
[`algorithm_v5/`](algorithm_v5/) 与它的 [Python 移植](py5/) 的对照实验）。
旧版报告已归档至 [`docs/reports/archive/`](docs/reports/archive/)。

## 目录

```
src/                  代码（注意：包在 src/ 下，命令都要带 PYTHONPATH=src，或用 make）
  judge/              判题核心 + HTTP 服务
    core/             解析 → 时长 → 依赖/引擎 → 内存 → makespan
    service/          队列、账本、SSE、自检
    tests/            66 个单测
  solver/             求解器（formula / psi / place / sched / solve / solve_all）
    selftests/        9 条回归（紧内存、空隙回填、窗口上限…）
  ui/                 只读视图（纯渲染，有自己的 lint）
tools/                脚本：CP-SAT 证明、独立穷举、下界分析、并行评测、用例生成
scripts/              e2e（起服务 + 浏览器 dump-dom 全链路）
cases/                七个官方样例（ex1–ex6 + mini）与期望值
data/
  official/           官方包：50 个用例、grader.py、题面、官方样例解、参考报告
  battery/            13 个自造大用例（最大 64 万 op，可用 tools/gen_battery.py 重新生成）
  opt/                CP-SAT 落盘的最优解
  refs/               题面引用的论文
docs/
  reports/            解题报告、方案、验收报告
  reviews/            判题/服务/求解器/UI 各层评审
  problem/            历版题面与样例输出
  patches/            已合入与已否决的补丁
  design/             UI 设计稿
  CONTRACT.md         三层契约（数据口径、错误分类、部署）
  rule-change-1029.md 2026-10-29 规则变更记录（含一处代价很大的坑）
  optimality.md       最优性证明与大用例残差分析
  BACKUP-NOTE.md      历史快照说明
Makefile              常用命令（见下）
```

## 快速开始

```bash
make six        # 六个官方样例：560 / 4880 / 6072 / 3200 / 416 / 1696
make check      # 全部校验：判题 7/7、求解器、服务自检、UI lint、独立复算 7/7
make test       # 单测：judge 66 + solver 9
make fast       # 官方 50 例的 12 例冒烟子集（并行，约 15 s）
make official   # 官方 50 例全量（并行，约 45 s）
make official-serial   # 同上但串行（约 6 分钟）—— 对外报成绩用这个
```

单例求解：

```bash
PYTHONPATH=src python3 src/solver/solve_all.py data/official/Problem/cases/x13_lr_twochunk_p8.txt out.txt
PYTHONPATH=src python3 -m judge eval data/official/Problem/cases/x13_lr_twochunk_p8.txt out.txt
```

> 代码放在 `src/` 下，所以要么带 `PYTHONPATH=src`，要么直接用 `make`。
> `src/solver/solve_all.py` 这类脚本自己能找到仓库根，单独跑也 OK。

## 六个官方样例的最优性

```bash
pip install --target .pylibs ortools          # 只有 CP-SAT 相关工具需要
PYTHONPATH=.pylibs:src python3 tools/cpsat_global.py cases/ex3.in    # → 6072 · OPTIMAL
PYTHONPATH=src python3 tools/ex3_verify.py                            # 不用 OR-Tools 的独立穷举复核
```

## 环境

Python 3.13+，**无第三方依赖**（`ortools` 只用于 `tools/cpsat_*`，装在 `.pylibs/`）。

## 说明

`data/official/` 下是赛题提供的评测材料（题面、50 个用例、官方 `grader.py`、官方样例解），
仅用于本地验证与复现，版权归赛题方所有。
