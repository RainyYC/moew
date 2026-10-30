# frontier 冻结基线报告（t3）

> 基线对象：`/home/rainy/hackathon/work-frontier-baseline`（detached `c558d9be025b4825ce00fdb8ff343da6392272b8`）。
> 对照工具：`tools/frontier_bench.py`（本任务交付，最终 SHA-256 `e53c1d3ebb002856...`）。
> 口径：`docs/reports/frontier-protocol.md`（t1 冻结，未改写）；本报告只补 t3 的实测与三处澄清。

## 0. 结论摘要

| 集合 | 官方输入合格 | 官方合法（eligible 内） | TIME 均值 / 范围 | 最大 solver wall |
| --- | --- | --- | --- | --- |
| 官方 50 例 | 50/50（事后 `--audit-inputs` 复核） | **50/50** | 均值 **21,900,063**；中位 16,848,111；1,808,324–106,581,594 | **7.25 s** |
| fast12（预注册覆盖子集） | 12/12 | 12/12 | — | 7.27 s |
| 六样例+mini | 6/7（mini 输入被官方拒绝） | **6/6** | 560 / 4880 / 6072 / 3200 / 416 / 1696 | 0.87 s |
| battery 13 例 | 13/13 | **13/13** | 均值 1.148e16；5.90e12–8.38e16 | 6.71 s |
| 留出集 v1（seed 424242） | 8/8 | 7/8 | — | 7.67 s |
| 留出集 v2（seed 424243 + 必要可行性过滤） | 8/8 | **8/8** | — | 7.07 s |
| mini-even 派生夹具 | 1/1 | 1/1 | 280 = lb | 0.09 s |

- 当前基线在官方 50 例上 **50/50 合法、无超时**，均值 `21,900,063` 与旧 README 的 `21,900,063` 一致；相对官方 `sample_solution` 均值 `31,765,363` **低 31.06%**，且 **50/50 逐例更优**（几何均值比 0.7288）。
- 基线并非处处可解：seed 424242 的 `h02` 因**生成器的 M 模型漏算通信缓冲/激活**而输入层面不可行（见 §5.5），不是 solver 回归；修正过滤后的 seed 424243 留出集 8/8 合法。
- `cases/mini` 被官方 grader 在**输入解析**阶段拒绝（`nmb=1` 违反 §4.7 第 5 条），只能作本地回归；t5 的官方统计应排除它并单列 N/A，用派生的 `mini-even` 覆盖"零反向时长"形态。
- 正式 A/B 必须用**最终版工具**；官方 50 例批次由 t3 早期工具执行（Time 测量路径未变，资格由事后审计独立确认）。

## 1. 目的与范围

- 在**不改任何 solver / judge / 官方输入 / grader** 的前提下，用冻结基线提交建立可复现的成绩与 wall/CPU 基线。
- 交付一个可复用的对照工具：串行、逐例独立进程、求解子进程硬超时 10 s、官方 grader 与本地 judge 双验、原始证据全留。
- 本报告**只**记录本次实测；历史 `solution-report.md` / `optimality.md` / `large-cases.md` 的结论**未在本冻结代码+输入+grader 下复验，故不作当前最优性证据**，也不据此反推其数值错误。
- **主比较对象**是冻结基线本身（t4 的 A/B 对照基线）；官方 `sample_solution` 的 `report_python.txt` 只作上下文参考，不作为"最优"或"目标值"。
- 未安装依赖、未起服务、未调用其他模型；未改动其他 agent 的 worktree。

## 2. 冻结身份与环境

| 项 | 值 |
| --- | --- |
| 基线 worktree | `/home/rainy/hackathon/work-frontier-baseline` |
| git HEAD | `c558d9be025b4825ce00fdb8ff343da6392272b8`（detached，运行前后 `git status --porcelain` 为空） |
| Python | 3.14.6（`/usr/bin/python3`） |
| 机器 | Linux-6.18.16-aosc-main-x86_64-with-glibc2.42，12 核，共享 |
| grader | `/home/rainy/hackathon/work-frontier-sgs/data/official/Problem/grader.py`，SHA-256 `c42d5f0675e33cbfc1d40bdcafbb8aa40b6d0a4e26377e69405cdbb2b167cfbc` |
| solver 文件集合 | 10 个文件聚合 SHA-256 `d4230654dcffaf21070828142e45f5721333778b356180fae584540002377070` |
| tool（本批） | `b8e792df19ab8305706a6dcff5f1d003b2fcc0c410f4aa896bbd0df0c6571502`（早期版；最终版见 §3） |
| 官方 50 例输入审计 | `runs/frontier/baseline/baseline-official50/input-audit.json` → 50/50 eligible |

完整逐文件哈希见 `runs/frontier/manifest.json`；基线 worktree 与 `c558d9b` 的 solver/judge/grader 逐字节一致（t1 已核）。

## 3. 对照工具 `tools/frontier_bench.py`

### 3.1 行为

- **串行**：`jobs=1`，一次只启动一个求解进程；每个用例独立子进程，求解 wall/CPU 用 `perf_counter` 与 `RUSAGE_CHILDREN` 差值单独测量。
- **硬超时**：求解默认 `--timeout 10`（题面墙钟上限），超时记 `TO`，**不计成功**；非零退出记 `ERROR`，缺输出记 `ERROR`。
- **预算**：显式传 `--budget B`，`B=auto_budget(n_ops)` 与 `solve_all.py` 同表（≤20k→7.6 s、≤200k→7.2 s、>200k→6.2 s），逐例写入 record/meta；A/B 两边由同一函数计算，天然同预算。
- **环境隔离**：`PYTHONPATH=<worktree>/src`、`PYTHONDONTWRITEBYTECODE=1`；基线 worktree 运行后仍 `git status` 干净。**不 import** solver/judge。
- **双判分**：先跑官方 `grader.py`（成绩权威），再跑 `python3 -m judge eval ... --json`（更严格的第二道闸）；判题 wall/CPU 独立记录，不占求解预算。
- **资格判定**：`probe_official_input()` 只 import 官方 `grader` 并调用其 `parse_instance`，**独立于 solver 输出与报错字符串**。`eligible=false` 的用例记 `INPUT_REJECT`，报告为 N/A，不计 solver 失败、也不计官方成功；官方合格用例上的超时/非法/错误退出照常计失败。
- **证据**：每例落盘 `.out`、`.stdout`（与 `.out` 相同时只留说明）、`.stderr`、`.grader.out/.err`、`.judge.json`、`<case>.json`；批次落盘 `meta.json`、`cmd.txt`、`env.txt`、`summary.json/md`。run 目录**追加不覆盖**（已存在非空目录直接拒绝，除非 `--force`）。

> **为什么不用 `tools/run_official.py` 记成绩**：它默认 8 路并行、超时 30 s；注释声称 `TIME` 与串行逐位相同，
> 但求解器受墙钟预算截断，并行争用 CPU 会改变截断点，墙钟与分数都不稳定。本报告的正式分数/墙钟一律走
> 本工具的串行路径；`data/official/Problem/run_all.py` 是串行 10 s 的官方口径，本工具已逐例调用同一个
> 官方 `grader.py`，故未额外重复跑 `run_all.py`。

### 3.2 工具自测（防止把失败记成成功）

`python3 tools/frontier_bench.py --selftest` 用四个假 solver 验证四条路径（证据：`runs/frontier/selftest-20261030-130027/`）：

| 假 solver | 期望 | 实测 |
| --- | --- | --- |
| 直接抄官方样例输出 | `OK`（双判分器一致） | OK |
| 写非法映射 | `INVALID` | INVALID（`grader_reject`） |
| sleep 5 s（超时 1 s） | `TO` | TO（`solver_timeout`） |
| `exit 3` | `ERROR` | ERROR（`solver_exit_3`） |

最终版 SHA-256：`e53c1d3ebb0028564f5c376d6d8a934f6b1ba181c25eaad28f516d63a02af574`。
t3 期间工具迭代过几次（加资格探针、绝对路径、本地 judge 恒跑、留出集可行性过滤、`--audit-inputs`）。
**求解计时路径未改**；官方 50 例批次的 Time 仍由同一 solver + 同一 grader 产生，资格由事后审计补确认。

### 3.3 如何复用到候选 A/B

```bash
# A：冻结基线
python3 tools/frontier_bench.py --label A1 --set official50 \
  --solver /home/rainy/hackathon/work-frontier-baseline/src/solver/solve_all.py \
  --worktree /home/rainy/hackathon/work-frontier-baseline \
  --out runs/frontier/experiments/<id>/A1

# B：候选（同一 worktree 的 src 即候选代码）
python3 tools/frontier_bench.py --label B1 --set official50 \
  --solver /home/rainy/hackathon/work-frontier-sgs/src/solver/solve_all.py \
  --worktree /home/rainy/hackathon/work-frontier-sgs \
  --out runs/frontier/experiments/<id>/B1

# ABBA：A1 → B1 → B2(--reverse) → A2(--reverse)；逐例比较用 summary.json 的 records
```

## 4. 判分口径与已知差异（本报告只记录，不修改任何一边）

1. **零时长通信缓冲**：官方 `grader.py` 统计 `Movl` 时跳过 `duration<=0` 的通信；本地 judge `ZERO_LEN_COMM_COUNTS=True` 保守计入。`ex5`（P=1）本地 `Movl=2`、官方口径 0；`mini` 本地 3、官方口径 1；`Time` 与合法性不变。工具用 `zero_len_comm_suspect` 标记 P=1 / H=0 / Fio=0 的用例，供 A/B 时单列。
2. **`cases/mini` 输入不合格**：`nmb=1`（奇数）违反题面 §4.7 第 5 条，官方 `grader.py` 在输入解析阶段返回 `INVALID: input: n_mb must be even`。官方 50 例的"全合法"要求不受影响；**mini 不计入官方成功率/TIME，只作本地回归**。t3 未修改 `cases/mini` 或 grader。
3. **`mini-even` 派生夹具**（`runs/frontier/cases/mini-even/`）：`cases/mini.in` 仅把 `nmb` 1→2，其余字节不变；官方 `parse_instance` 确认合法（`input-audit.json`）。基线解 `Time=280=lb`，官方与本地都判合法；本地 `Movl=5`、官方口径 `Movl=2`（零反向时长在 `t=280` 叠了 4 个零长度通信），是零时长口径差异的实测样本。
4. 历史文档中的"最优/下界"（含 ex3=6072）**未在本次冻结条件下复验**，本报告只记录本次实测 `ex3=6072`，不宣称最优性，也不额外跑全局 oracle。

## 5. 基线结果

### 5.1 官方 50 例（主成绩）

命令（t3 实际执行）：

```bash
python3 tools/frontier_bench.py --label baseline-official50 --set official50 \
  --solver /home/rainy/hackathon/work-frontier-baseline/src/solver/solve_all.py \
  --worktree /home/rainy/hackathon/work-frontier-baseline \
  --out runs/frontier/baseline/baseline-official50
```

- 状态：`OK=50/50`，无 `TO`/`INVALID`/`ERROR`，无 `zero_len_comm_suspect` 用例。
- 总墙钟 313.4 s（loadavg 2.90→3.42）；求解 wall 均值 5.972 s、最大 **7.250 s**；CPU 均值 5.968 s、最大 7.244 s。
- 官方 grader wall 均值 0.109 s、最大 0.609 s；本地 judge wall 均值 0.183 s、最大 0.744 s（**均不占求解预算**）。
- 几何结构：`K=2V` 的用例 **20/50**，`K=V` 30/50 —— `K=2V` 不是边角形态，t2/t5 必须覆盖。
- 与官方 `sample_solution`（`report_python.txt`，均值 31,765,363）比：**50/50 逐例更优**，均值改善 **31.06%**，几何均值比 0.7288；最接近的 `x19_vl_trap4_fs4` 仍优 1.05%，最好的 `r32_p8_ramp` 优 59.5%。

| case | TIME | vs sample | wall(s) | V/P/K | flags |
| --- | ---: | ---: | ---: | --- | --- |
| r128_v4_c4a | 24,003,060 | -17.8% | 4.85 | 8/16/8 | - |
| r128_v8_c4 | 24,363,545 | -15.7% | 5.58 | 15/8/15 | - |
| r128_v8_c8a | 12,166,030 | -15.5% | 1.55 | 16/8/16 | - |
| r128_v8_c8b | 5,796,525 | -11.1% | 4.61 | 15/8/15 | - |
| r16_p4_trap | 21,869,220 | -46.8% | 7.06 | 4/4/8 | - |
| r20_p2_flat | 31,321,175 | -35.3% | 7.06 | 10/2/20 | - |
| r24_p3_flat | 25,591,468 | -41.7% | 7.20 | 8/3/16 | - |
| r24_p4_block | 51,491,190 | -55.8% | 7.25 | 6/4/12 | - |
| r256_v4_c4 | 64,625,020 | -21.2% | 4.72 | 7/32/7 | - |
| r256_v8_c16 | 53,309,912 | -17.4% | 4.32 | 15/16/15 | - |
| r256_v8_c4 | 40,346,335 | -25.0% | 6.05 | 15/16/15 | - |
| r256_v8_c8a | 29,258,410 | -17.6% | 4.21 | 15/16/15 | - |
| r32_p8_ramp | 17,096,182 | -59.5% | 7.06 | 4/8/8 | - |
| r64_v2_c2 | 2,600,248 | -9.2% | 2.99 | 3/16/3 | - |
| r64_v2_c4 | 5,046,076 | -8.2% | 7.03 | 3/16/3 | - |
| r64_v4_c4a | 2,831,948 | -14.0% | 6.34 | 8/8/8 | - |
| r64_v4_c4b | 5,579,036 | -23.2% | 7.03 | 7/8/7 | - |
| r64_v4_c4c | 10,272,990 | -18.2% | 4.85 | 7/8/7 | - |
| r64_v4_c4d | 24,317,861 | -16.1% | 6.26 | 7/8/7 | - |
| r64_v4_c4e | 36,876,336 | -15.4% | 4.62 | 7/8/7 | - |
| r64_v8_c16a | 6,473,240 | -14.2% | 7.10 | 15/4/15 | - |
| r64_v8_c16b | 106,581,594 | -17.1% | 4.07 | 15/4/15 | - |
| r64_v8_c16c | 40,430,360 | -26.1% | 5.78 | 15/4/15 | - |
| r64_v8_c8a | 5,282,831 | -15.8% | 4.62 | 16/4/16 | - |
| r64_v8_c8b | 3,388,464 | -9.8% | 7.15 | 15/4/15 | - |
| r64_v8_c8c | 7,206,270 | -16.1% | 4.66 | 15/4/15 | - |
| r64_v8_c8d | 5,239,340 | -22.0% | 4.77 | 15/4/15 | - |
| r64_v8_c8e | 16,600,040 | -11.0% | 5.24 | 15/4/15 | - |
| r64_v8_c8f | 20,964,124 | -13.1% | 4.12 | 15/4/15 | - |
| r64_v8_c8g | 40,667,662 | -19.0% | 4.87 | 15/4/15 | - |
| x01_lr_block_p2 | 2,922,720 | -29.9% | 7.06 | 6/2/12 | - |
| x02_lr_ramp_c16 | 21,741,644 | -44.8% | 7.05 | 4/4/8 | - |
| x03_lr_trap_p3 | 12,421,204 | -43.4% | 7.06 | 9/2/18 | - |
| x04_lr_inter_p5 | 30,855,400 | -37.2% | 7.08 | 10/2/20 | - |
| x05_lr_tight_p6 | 16,417,874 | -46.2% | 7.05 | 8/3/16 | - |
| x06_lr_trap_p7 | 10,283,160 | -48.4% | 7.06 | 14/2/28 | - |
| x07_lr_flat_p10 | 20,213,550 | -58.7% | 7.10 | 6/5/12 | - |
| x08_lr_lowb_p4 | 8,861,148 | -27.4% | 7.06 | 8/4/16 | - |
| x09_lr_skew_p6 | 20,304,192 | -42.3% | 7.05 | 9/4/18 | - |
| x10_lr_tight_p8 | 19,842,661 | -28.5% | 7.08 | 10/4/20 | - |
| x11_lr_deep_p3 | 14,168,516 | -21.9% | 7.11 | 16/3/32 | - |
| x12_lr_close_p10 | 32,992,560 | -24.3% | 7.08 | 12/5/24 | - |
| x13_lr_twochunk_p8 | 14,937,492 | -52.0% | 7.06 | 6/4/12 | - |
| x14_lr_twochunk_p15 | 87,190,476 | -34.2% | 7.07 | 10/3/20 | - |
| x15_lr_twochunk_p10 | 17,099,568 | -40.2% | 7.06 | 8/5/16 | - |
| x16_vl_trap4_ramp | 4,325,802 | -6.4% | 7.07 | 16/8/16 | - |
| x17_vl_tight_block | 6,298,808 | -12.4% | 7.10 | 15/8/15 | - |
| x18_vl_tight_small | 1,808,324 | -8.8% | 1.26 | 8/8/8 | - |
| x19_vl_trap4_fs4 | 8,283,726 | -1.1% | 7.06 | 20/6/20 | - |
| x20_vl_flat_control | 2,437,848 | -11.6% | 7.07 | 12/8/12 | - |

统计明细：

```json
{
 "official_time_stats": {
  "count": 50,
  "sum": 1095003165,
  "mean": 21900063.3,
  "median": 16848111.0,
  "min": 1808324,
  "max": 106581594
 },
 "solver_wall_stats": {
  "count": 50,
  "sum": 298.5919,
  "mean": 5.971838,
  "median": 7.0501000000000005,
  "min": 1.2587,
  "max": 7.2502
 },
 "solver_cpu_stats": {
  "count": 50,
  "sum": 298.3892,
  "mean": 5.967784,
  "median": 7.0466,
  "min": 1.2581,
  "max": 7.2444
 },
 "official_grader_wall_stats": {
  "count": 50,
  "sum": 5.4677,
  "mean": 0.10935399999999999,
  "median": 0.0555,
  "min": 0.0264,
  "max": 0.6086
 },
 "local_judge_wall_stats": {
  "count": 50,
  "sum": 9.1723,
  "mean": 0.183446,
  "median": 0.13140000000000002,
  "min": 0.0994,
  "max": 0.744
 }
}
```

### 5.2 fast12（预注册覆盖子集）与两趟稳定性

fast12 是 `tools/run_official.py --subset fast` 既有的 12 例集合（计算主导/通信主导/填充/偏斜/紧内存/twochunk/对称形态），**在任何 t3 结果之前就已固定**，作为探索期的官方形态覆盖子集；`official50` 全量是冻结验证集，生成种子留出集只用于复核、不参与调参。

| case | pass1 TIME | pass2 TIME | delta | wall1 | wall2 |
| --- | ---: | ---: | ---: | ---: | ---: |
| r128_v8_c8a | 12,166,030 | 12,166,030 | +0.00% | 1.73 | 1.58 |
| r16_p4_trap | 21,869,220 | 21,869,220 | +0.00% | 7.08 | 7.06 |
| r24_p4_block | 51,491,190 | 51,491,190 | +0.00% | 7.27 | 7.24 |
| r256_v4_c4 | 64,856,102 | 64,625,020 | -0.36% | 4.72 | 4.83 |
| r32_p8_ramp | 17,096,182 | 17,096,182 | +0.00% | 7.07 | 7.06 |
| r64_v2_c2 | 2,600,248 | 2,600,248 | +0.00% | 3.37 | 2.93 |
| r64_v8_c8d | 5,239,340 | 5,239,340 | +0.00% | 4.89 | 4.84 |
| x03_lr_trap_p3 | 12,421,204 | 12,421,204 | +0.00% | 7.05 | 7.05 |
| x05_lr_tight_p6 | 16,417,874 | 16,417,874 | +0.00% | 7.04 | 7.05 |
| x13_lr_twochunk_p8 | 14,937,492 | 14,937,492 | +0.00% | 7.08 | 7.06 |
| x18_vl_tight_small | 1,808,324 | 1,808,324 | +0.00% | 1.31 | 1.28 |
| x19_vl_trap4_fs4 | 8,283,726 | 8,283,726 | +0.00% | 7.07 | 7.07 |

- 两趟共 11/12 例 `TIME` 完全一致；唯一差异 `r256_v4_c4`：64,856,102 → 64,625,020（-0.36%），发生在 wall 4.72/4.83 s、loadavg 4.6→5.3 的争用下。
- 这正是 anytime 搜索受**墙钟截断**的表现：同输入、同 seed、同预算，但机器负载不同会截在不同迭代前缀。**不是随机性 bug**；正式 A/B 用 ABBA 并如实报告这种量级。
- 两趟 wall 均值 5.47/5.42 s，最大 7.27/7.24 s。

### 5.3 六样例 + mini

| case | 官方状态 | 官方 TIME | 本地 TIME | wall(s) | flags |
| --- | --- | ---: | ---: | ---: | --- |
| ex1 | OK | 560 | 560 | 0.06 | - |
| ex2 | OK | 4,880 | 4,880 | 0.75 | - |
| ex3 | OK | 6,072 | 6,072 | 0.65 | - |
| ex4 | OK | 3,200 | 3,200 | 0.06 | - |
| ex5 | OK | 416 | 416 | 0.52 | zero_len_comm_suspect |
| ex6 | OK | 1,696 | 1,696 | 0.87 | - |
| mini | INPUT_REJECT | - | 164 | 0.60 | grader_reject,local_accepts_official_reject,official_input_invalid |

- 6 个官方样例全部合法；`ex3` 本次实测 **6072**（只记录数值，不作最优性结论）。
- `mini`：官方输入解析拒绝（N/A）；本地 judge 判合法 `Time=164`，与 `cases/expected.json` 一致。t5 的官方成功率分母应排除 mini。

### 5.4 battery 13 例（题面 §6 规模，主工作树只读引用）

| case | TIME | wall(s) | V/P/K | flags |
| --- | ---: | ---: | --- | --- |
| b01-loose | 5,904,000,000,000 | 6.45 | 64/1/64 | zero_len_comm_suspect |
| b02-m512 | 542,157,603,132,750 | 6.67 | 64/2/64 | - |
| b03-m256 | 811,784,777,827,320 | 6.64 | 64/4/64 | - |
| b04-m96 | 946,917,900,211,470 | 6.37 | 64/8/64 | - |
| b05-maxmb | 49,008,000,000,000 | 4.49 | 64/1/64 | zero_len_comm_suspect |
| b06-maxmb-tight | 5,229,861,932,305,704 | 6.46 | 64/4/64 | - |
| b07-mixed | 3,492,805,460,668,064 | 6.61 | 64/2/64 | - |
| b08-narrow | 1,569,450,570,466,152 | 6.71 | 64/4/64 | - |
| b09-small-e | 49,008,000,000,000 | 3.32 | 64/1/64 | zero_len_comm_suspect |
| b10-high-k | 179,346,953,034,600 | 3.73 | 64/4/64 | - |
| b11-short-l | 4,934,667,467,641,224 | 4.27 | 4/4/4 | - |
| b12-compute-bound | 83,843,497,367,000,000 | 6.63 | 64/8/64 | - |
| b13-balanced-compute | 47,572,895,000,000,000 | 6.06 | 8/64/8 | - |

- 13/13 官方合法；最大 wall 6.71 s；总墙钟 124.4 s（loadavg 3.19→5.03）。
- `b01/b05/b09` 为 `P=1`、通信零时长，标记 `zero_len_comm_suspect`（本地 `Movl` 更保守）；Time 与合法性两边一致。
- 4 个 640k-op 用例（`b05/b06/b07/b09`）用 6.2 s 预算，其余按表 7.2 s。

### 5.5 固定 seed 留出集

**v1：seed=424242（原始生成，未加可行性过滤）**

| case | TIME | wall(s) | V/P/K | flags |
| --- | ---: | ---: | --- | --- |
| h00 | 25,432 | 3.29 | 16/2/16 | - |
| h01 | 51,698,252,424 | 7.06 | 2/1/4 | zero_len_comm_suspect |
| h02 | - | 7.67 | None/None/None | solver_exit_1 |
| h03 | 2,240,272 | 0.58 | 4/1/4 | zero_len_comm_suspect |
| h04 | 16,384 | 0.15 | 1/1/1 | zero_len_comm_suspect |
| h05 | 81,920,000 | 0.06 | 1/4/1 | - |
| h06 | 1,200 | 0.06 | 1/4/1 | - |
| h07 | 1,179,000,000 | 4.60 | 4/1/4 | zero_len_comm_suspect |

- 8/8 输入被官方解析接受；7/8 得到合法解。`h02` 求解器返回 `exit=1`（"没有找到合法映射"），**不是 solver 回归**：
  `h02` 参数 `L=2,E=16,Z=1024,Zs=65536,U=Uact=262144,M=239895`。取对内存最友好的 `V=2,P=1`：
  `Mexp=1×(16×1024+65536)=81,920`，加至少一份激活 `Uact=262,144` 已是 **344,064 > M=239,895**；
  若再计通信缓冲只会更大。该用例在输入层面就不可行。
- 根因：`tools/fuzz.py` 的 M 只按 Mexp 估最小驻留量，未计 `Movl/Mact`。t3 **未修改** `tools/fuzz.py`，而是在对照工具里加输入层面必要可行性过滤（只用题面公式，不看求解结果），并用**新的固定 seed** 重生成，避免对已看过的样本挑挑拣拣。

**v2：seed=424243（预注册必要可行性过滤）**

过滤条件（写入 `heldout-manifest.json`）：`ceil(L/V)·((E/P)Z+Zs) + U + Uact <= M`（本地保守口径）。

| case | TIME | wall(s) | V/P/K | flags |
| --- | ---: | ---: | --- | --- |
| h00 | 71,478,400 | 6.33 | 32/1/32 | zero_len_comm_suspect |
| h01 | 511,655,522 | 3.75 | 4/1/8 | zero_len_comm_suspect |
| h02 | 67,744 | 0.43 | 16/1/16 | zero_len_comm_suspect |
| h03 | 34,266,672 | 7.07 | 32/1/32 | zero_len_comm_suspect |
| h04 | 2,480 | 0.42 | 2/1/4 | zero_len_comm_suspect |
| h05 | 6,572,392,943,059 | 2.29 | 8/16/8 | - |
| h06 | 2,368 | 0.83 | 4/1/4 | zero_len_comm_suspect |
| h07 | 95,488 | 7.07 | 2/1/4 | zero_len_comm_suspect |

- 8/8 输入合格、8/8 官方合法，最大 wall 7.07 s；`zero_len_comm_suspect` 6 例（多为 `P=1`）。

### 5.6 mini-even 派生夹具（t5 零反向形态）

| case | TIME | wall(s) | V/P/K | flags |
| --- | ---: | ---: | --- | --- |
| mini-even | 280 | 0.08 | 1/2/1 | - |

- 官方与本地均合法，`Time=280=lb`；本地 `Mexp=20, Movl=5, Mact=1`（26/39），官方口径 `Movl=2`；
  差异全部来自 `t=280` 的 4 个零时长反向通信（`comb_bwd`/`disp_bwd` × 2 mb）。
- 该夹具只补充"零反向时长 + 零时长操作必须输出"的覆盖，不替代 `cases/mini.in`。

## 6. 与旧 README / 历史结论的关系

- 旧 README 声称的"50/50 合法、均值 21,900,063、较样例解 −31.1%、逐例更优、峰值墙钟 7.23 s"
  在本次串行实测中**全部复现**（均值 21,900,063、改善 31.06%、50/50 逐例更优、峰值 7.25 s）。
- 旧 README 的"六个样例经 CP-SAT 证明全局最优"**未在本次冻结条件下复验**，本报告不引用为证据；
  `ex3` 只记录本次实测 6072。
- 未为了复现旧结论而改预算、改输入或筛选样本；所有批次都是单趟（fast12 额外做了第二趟反向）。

## 7. 对 t1 协议的三处澄清（captain 2026-10-30 指示）

1. **历史文档与 ex3=6072 的表述**：不称"规则变更前/过期"，而是"**尚未在本冻结代码、输入、grader 下复验，故不作当前最优性证据**"。本报告只记录实测 ex3=6072；不从未复验推导其数值不成立，也不为此增加全局 oracle 长跑。
2. **确定性**：不再要求"同预算+同 seed 必有相同输出"。要求的是**同输入/seed/迭代上限下候选序列确定**；受墙钟截断的 anytime 搜索允许机器争用造成不同截断前缀，需记录实际迭代数与停止原因。`fast12` 两趟 11/12 相同、1 例 −0.36% 即为实测证据；正式 ABBA 如实量化，不当作随机性 bug。
3. **串行边界**：本 harness 只承诺自身 `jobs=1`，**无法也不去控制其他团队/进程**；不暂停、不干预其他 team。每批记录 CPU/wall/loadavg 与干扰（本次 loadavg 从 2.9 升到 5.4），重要回归再在同条件复测，不因外部负载永久阻塞。
4. 协议是研究口径，不为形式完善压过实际算法实验；t1 原始冻结证据（manifest、t1-smoke）原样保留。

## 8. 复现命令（本次全部批次）

```bash
cd /home/rainy/hackathon/work-frontier-sgs
SGS=$PWD
BASE=/home/rainy/hackathon/work-frontier-baseline
SOLVER=$BASE/src/solver/solve_all.py

# 0) 自测（四条失败路径）
python3 tools/frontier_bench.py --selftest

# 1) 官方 50 例（主成绩）
python3 tools/frontier_bench.py --label baseline-official50 --set official50 \
  --solver $SOLVER --worktree $BASE --out runs/frontier/baseline/baseline-official50

# 2) fast12 覆盖子集（第二趟加 --reverse）
python3 tools/frontier_bench.py --label baseline-fast12 --set fast12 \
  --solver $SOLVER --worktree $BASE --out runs/frontier/baseline/baseline-fast12
python3 tools/frontier_bench.py --label baseline-fast12-pass2-reverse --set fast12 --reverse \
  --solver $SOLVER --worktree $BASE --out runs/frontier/baseline/baseline-fast12-pass2-reverse

# 3) 六样例 + mini
python3 tools/frontier_bench.py --label baseline-samples7 --set samples7 \
  --solver $SOLVER --worktree $BASE --out runs/frontier/baseline/baseline-samples7

# 4) battery 13 例（主工作树未入库数据，只读）
python3 tools/frontier_bench.py --label baseline-battery13 --set battery13 \
  --solver $SOLVER --worktree $BASE --out runs/frontier/baseline/baseline-battery13

# 5) 留出集：生成 → 资格审计 → 基线
python3 tools/frontier_bench.py --gen-heldout --seed 424243 --count 8 \
  --out runs/frontier/cases/heldout-seed424243
python3 tools/frontier_bench.py --audit-inputs --set custom \
  --cases-dir runs/frontier/cases/heldout-seed424243 \
  --out runs/frontier/cases/heldout-seed424243/input-audit.json
python3 tools/frontier_bench.py --label baseline-heldout-seed424243 --set custom \
  --cases-dir runs/frontier/cases/heldout-seed424243 \
  --solver $SOLVER --worktree $BASE --out runs/frontier/baseline/baseline-heldout-seed424243

# 6) mini-even（零反向形态）
python3 tools/frontier_bench.py --label baseline-mini-even --set custom \
  --cases-dir runs/frontier/cases/mini-even \
  --solver $SOLVER --worktree $BASE --out runs/frontier/baseline/mini-even
```

## 9. 风险、限制与给 t4/t5 的约定

- **共享机器**：12 核共享，loadavg 2.9→5.4 明显上升；本报告不声称独占 CPU。正式 A/B 需 ABBA、记录 loadavg，并在同条件复测重要回归。
- **单趟基线**：官方 50 例只跑了一趟（~5.2 min）；battery 一趟。除 fast12 外没有重复测。若 t5 需要更稳的噪声估计，应复用工具对同一冻结版本重复，而不是重新发明测量方式。
- **基线已知失败面**：seed 424242 的 `h02` 输入不可行（生成器缺陷已定位，未改 `tools/fuzz.py`）；任何候选在留出集上的失败必须先按同一必要可行性检查归因，再判断是否回归。
- **mini 不是官方用例**：t5 的"官方 50+6 样例"统计不得把 mini 计入成功或失败；mini/mimi-even 只作本地退化形态。
- **零时长口径**：官方宽松、本地严格。候选在本地被判超内存但官方通过的，必须单列并说明；不得为通过本地门而修改 judge 或利用官方宽松。
- **不引入新依赖、不跑全局 oracle**：CP-SAT 只在需要离线复核时以只读 `.pylibs` 运行；本报告没有新增 oracle 结论。

## 10. 证据索引

| 批次 | 目录 | 状态 | 总墙钟 | loadavg(起→止) | tool SHA 前缀 |
| --- | --- | --- | ---: | --- | --- |
| 官方 50 例 | `runs/frontier/baseline/baseline-official50/` | 50/50 OK | 313.4 s | 2.90→3.42 | `b8e792df19ab8305` |
| fast12 pass1 | `runs/frontier/baseline/baseline-fast12/` | 12/12 OK | 68.8 s | 4.64→5.26 | `1e6bed7ceea27194` |
| fast12 pass2 | `runs/frontier/baseline/baseline-fast12-pass2-reverse/` | 12/12 OK | 67.9 s | 3.91→5.39 | `e53c1d3ebb002856` |
| 六样例+mini | `runs/frontier/baseline/baseline-samples7/` | 6 OK + mini N/A | 4.5 s | `[2.97, 3.51, 3.18]→[2.98, 3.51, 3.18]` | `f5996515661df9ab` |
| battery13 | `runs/frontier/baseline/baseline-battery13/` | 13/13 OK | 124.4 s | 3.19→5.03 | `1e6bed7ceea27194` |
| 留出集 v1 | `runs/frontier/baseline/baseline-heldout-seed424242/` | 7 OK + h02 输入不可行 | 24.6 s | `[4.78, 4.19, 3.51]→[4.64, 4.2, 3.53]` | `1e6bed7ceea27194` |
| 留出集 v2 | `runs/frontier/baseline/baseline-heldout-seed424243/` | 8/8 OK | 29.6 s | `[3.9, 4.31, 3.7]→[4.2, 4.36, 3.73]` | `e53c1d3ebb002856` |
| mini-even | `runs/frontier/baseline/mini-even/` | 1/1 OK | 0.3 s | `[3.05, 3.38, 3.15]→[3.05, 3.38, 3.15]` | `1e6bed7ceea27194` |
| 工具自测 | `runs/frontier/selftest-20261030-130027/` | 4/4 PASS | — | — | `e53c1d3e…` |
| 输入审计（official50） | `runs/frontier/baseline/baseline-official50/input-audit.json` | 50/50 eligible | — | — | — |
| 输入审计（v2 heldout） | `runs/frontier/cases/heldout-seed424243/input-audit.json` | 8/8 eligible | — | — | — |

每个批次目录内都有 `meta.json`（含 solver/judge/grader 哈希、预算表、用例哈希、loadavg）、
`cmd.txt`、`env.txt`、逐例 record 与官方/本地判分原始输出。

## 11. 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-10-30 | v1 | t3 首版：工具、自测、官方 50 / fast12 / samples7 / battery13 / 两版留出集 / mini-even 基线；补 t1 协议三处澄清与 mini 资格处理 |
