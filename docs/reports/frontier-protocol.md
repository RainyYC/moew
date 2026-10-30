# frontier 核心算法实验协议（冻结口径 v1）

> 团队 `frontier-core-optimization` 的**实验契约**。任何求解器改动、A/B 对照、正式测时，
> 都必须按本文件执行；与本文件冲突的历史文档（`docs/reports/solution-report.md`、
> `docs/optimality.md`、`docs/large-cases.md`）一律**不得**作为当前证据——它们写于
> 2026-10-29 规则变更（取消 `D`、依赖图与内存口径改写）之前。
>
> 本文件由 `benchmark-reviewer` 在 t1 冻结；代码/用例/判题器的逐文件哈希见
> `runs/frontier/manifest.json`（由 `tools/frontier_manifest.py` 只读生成）。

---

## 0. 一句话口径

- **评分权威**：官方 `data/official/Problem/grader.py` 的 `TIME`（越小越好）；合法性以它为准。
- **本地复核**：`PYTHONPATH=src python3 -m judge eval <case> <out> --json`，只作为更严格的
  第二道闸；两边不一致时**以官方为准判成绩、以本地为准判风险**，并单列差异。
- **公平对照**：同输入、同显式预算、同种子、串行、逐例独立进程；原始输出与退出码全留。
- **默认关闭**：未通过 t5 独立复核的新路线不得默认启用，也不得用更大预算/预存结果充收益。

---

## 1. 冻结身份

| 项 | 值 |
| --- | --- |
| 工作根 | `/home/rainy/hackathon` |
| 冻结提交（两 worktree 共同起点） | `c558d9be025b4825ce00fdb8ff343da6392272b8`（`master`） |
| 实验 worktree | `/home/rainy/hackathon/work-frontier-sgs`，分支 `opt-frontier-sgs` |
| 基线 worktree | `/home/rainy/hackathon/work-frontier-baseline`，**detached** 同一提交 |
| 两 worktree 冻结文件是否一致 | 是（solver / judge / 官方判题器 / Makefile 逐文件相等，见 manifest） |
| Python | 3.14.6（`/usr/bin/python3`，GCC 15.3.0 构建） |
| 机器 | Linux `rainy-aosc` 6.18.16 x86_64，12 核，约 13 GiB 内存，**共享** |
| 生成时间 | 见 `runs/frontier/manifest.json` 的 `generated_at` |

**写权限边界**

- 只允许在 `work-frontier-sgs` 写入；`work-frontier-baseline` 保持 detached + 干净
  （运行基线时必须带 `PYTHONDONTWRITEBYTECODE=1`，避免生成 `__pycache__`）。
- 禁止写入主工作树、`work-fillboost`、`work-placement-baseline`、`work-placement-partition`。
- 官方输入、`grader.py`、`run_all.py`、`src/judge/**` 是**只读**面；不得为让候选通过而修改。
- 实验产物一律进 `work-frontier-sgs/runs/frontier/`（`runs/` 已被 `.gitignore` 忽略，不入库）。

---

## 2. 冻结文件哈希

全量逐文件哈希在 `runs/frontier/manifest.json → hashes`。关键项（SHA-256）：

| 文件 | SHA-256 |
| --- | --- |
| `src/solver/formula.py` | `b2511aa41bc60fc37daa2150b7de91e66fc2a3a00c84d5a1d7aa13d09bc176d7` |
| `src/solver/sched.py` | `4610bb01228f78befde83165879c8ad2e48596dace5dc7ea8d6354eb3390500b` |
| `src/solver/solve.py` | `5036569b492263f69b96c34198ef872da1457e067b90eb3b7907a46da4bbc526` |
| `src/solver/solve_all.py` | `8024d56848a232199969a78ca17b757784d9ed4e4f427b017226c89d2dfcad0b` |
| `src/judge/core/memory.py` | `d231de36b3112a71e87ecf14aa80eaafb278f35367262215b8efa60fc688d820` |
| `src/judge/core/sim.py` | `37a02f3d5bf187814af56f2d89c1663e12265e3e5ad19e270923574ad81c01cf` |
| `data/official/Problem/grader.py` | `c42d5f0675e33cbfc1d40bdcafbb8aa40b6d0a4e26377e69405cdbb2b167cfbc` |
| `data/official/Problem/run_all.py` | `4ae700dcd19f0794d5f1067f1e59b3ed3066214e86ea641da0d9b6b09ee71c53` |
| `Makefile` | `940c14cb06a1e6ba5a53e95b9dc867e126fe9ab158f6078cd4a7dd1e637d39b9` |

用例集合（排序后的「相对名 + 字节」聚合，逐文件哈希同样在 manifest）：

| 集合 | 个数 | 聚合 SHA-256 | 位置 |
| --- | --- | --- | --- |
| 官方 50 例 | 50 | `4b60fe06442de4c3…`（全文见 manifest） | `work-frontier-sgs/data/official/Problem/cases/*.txt` |
| 六样例 + mini | 7 | `5dfe47d60543c8e2…` | `work-frontier-sgs/cases/{ex1..ex6,mini}.in` |
| 现有 battery | 13 | `44bf1c83c976dc6c…` | **只读**引用主工作树 `data/battery/bigcases/battery/*.in` |

> battery（236 MB）与官方包的部分目录**未入库**：worktree 里没有 `data/battery/`。
> 需要时按绝对路径读取主工作树的副本，禁止复制进 worktree、禁止修改。
> `cases/big1.in` 是额外本地样例，不计入「六样例 + mini」。

---

## 3. 判分语义（当前题面 `docs/problem/problem-v5.md` §3–6）

所有量整数；时长按题面 §4.1 向上取整；`Time = max(t + duration)`。

### 3.1 依赖（§4.2，2026-10-29 修订版）

- 前向路由链 `disp → gemm → comb`；反向路由链 `comb_bwd → gemm_dx → disp_bwd`。
- 共享专家：`s` 只依赖本层输入（与 `disp` 同一条边），须在 `comb` 前收尾；`s_bwd` 与
  `comb_bwd` 同源（本层 `comb` 结束，且 `l ≤ L−2` 时等 `l+1` 的 `disp_bwd`），须在
  `disp_bwd` 前收尾；`s_dw` 只等 `comb_bwd`。
- 权重梯度 `gemm_dw` / `s_dw` 只等 `comb_bwd`，可推迟到任意空档（不拖累下游层）。
- 层序锚点是 `comb(ℓ−1)`（前向入口）与 `disp_bwd(ℓ+1)`（反向入口），**建在层上而非块上**。
- 卡组引擎互斥：一个卡组一套计算引擎 + 一套通信引擎；`K=2V` 时两块共用同一对引擎。

### 3.2 内存（§4.6）——**本次冻结的核心口径**

对每个卡组 `v`（不是每张卡单独算，组内各卡同值）：

```
used(v) = Mexp(v) + U · peak_comm(v) + Uact · peak_act(v)
```

- **两个峰值分别取、再相加**，不允许用「同一时刻的瞬时总量」代替，也不允许把
  `U·peak_comm + Uact·peak_act` 换成某个联合峰值。
- `Mexp(v) = Σ_{ℓ 属于卡组 v} (E/P·Z + Z_s)`，静态。
- **通信缓冲 `peak_comm`**：区间 `[start, end]` 闭；同一时刻**先开后关**——一个通信恰好在
  下一个开始时结束，该时刻按 **2 块**计（题面 §4.6 原文）。只统计
  `disp/comb/comb_bwd/disp_bwd` 四种通信操作。
- **激活 `peak_act`**：`(mb, ℓ)` 从 `comb` 结束到本层 `s_bwd` 开始都算存活，区间
  **双闭** `[comb.end, s_bwd.start]`；前向恰在反向开始时结束，该时刻仍持有。
- 网格 `V·P < R` 时只有前 `V·P` 张卡承载层，空闲卡不计内存；但**每个卡组**都必须满足
  `used(v) ≤ M`，判分取最坏卡组。
- 超内存 = 非法 = 0 分（不是扣分）。

### 3.3 引擎占用（§4.2 第 3 条）

- 只有**非零时长**操作占用引擎；零时长操作**不占**（`P=1` 时 `x=0`、`s=0` 等）。
- 非零区间按 `[t, t+d)` **半开**处理：相等时刻释放合法（上一操作 `end == next start` 不冲突）。
- 同一行内不得出现两个占用同一引擎的操作。
- 每个 `(mb, ℓ, op)` 三元组必须恰好出现一次；**零时长操作也必须输出**（缺一条即非法）。

### 3.4 `K=2V` 镜像配对（§3.1）

- `K ∈ {V, 2V}`；`K=2V` 时块 `k ≥ V` 属于卡组 `2V−1−k`。
- 一个卡组持有前后两块，两块共用**同一对引擎**与**同一份内存核算**（`Mexp` 累加两块层数）。
- `K=2V` 不是免费的重叠：两个块的操作互相争用引擎，必须显式建模。

---

## 4. 已知口径差异与陷阱（不得"修正"）

1. **零时长通信缓冲**：官方 `grader.py` 在通信峰值统计里 `if D[l][op] <= 0: continue`，
   **完全忽略**零时长通信；本地 `src/judge/core/memory.py` 的
   `ZERO_LEN_COMM_COUNTS = True`（团队裁定保守）**计入**零长度区间。
   → 影响仅限 `Movl`。实测对照（同一份官方样例输出）：
   `ex5` 本地 `Movl=2`，跳过零长度后为 `0`；`mini` 本地 `Movl=3`，跳过为 `1`；
   `ex1` 两边都是 `2`。`Time` 与合法性不变；**紧内存用例上可能出现"官方合法、
   本地判超内存"**。两边都不许改；这种分歧要单列。
2. **`formula.comm_payload` 的 docstring 写错**：注释写 `⌈T·H·(P−1)/P⌉`，代码与官方
   grader 都是 `⌈T·H / P⌉`。**以代码 + grader 为准**，不要照注释"修"。
3. **`solve_all.TARGETS` 的 `ex3=7000`** 是题面样例输出值（`≤` 判定），不是最优；
   `cases/expected.json` 记的 6072 来自旧 CP-SAT 证明，**规则变更后不可作当前证据**。
4. **`tools/run_official.py` 是并行评测器**（默认 8 路，超时 30 s），注释声称 `TIME`
   与串行逐位相同——但求解器受**墙钟预算截断**，并行争抢 CPU 会改变截断点，正式成绩
   **不得**用它。它只用于探索期冒烟。
5. **`run_all.py` 的 10 s 是求解器子进程墙钟**；判题器自身耗时另计。求解器内部预算
   （`auto_budget`）已按 op 数折算并留余量，见 §6。
6. **历史文档全部过期**：`solution-report.md` / `optimality.md` / `large-cases.md` 的
   模型（含 `D`）与下界均不能引用；任何"最优/下界"结论必须来自当前提交的实测或
   当前规则下的独立 oracle。
7. **`.pylibs/`（ortools，241 MB）不在 worktree**。CP-SAT 只能作为只读离线 oracle：
   `PYTHONPATH=/home/rainy/hackathon/.pylibs:src python3 tools/cpsat_*.py`，不做生产依赖。

---

## 5. 产物与目录规范

```
runs/frontier/
├── manifest.json          # 冻结身份 + 哈希（本协议 §1–2 的机器可读版）
├── baseline/<run_id>/     # 冻结基线原始证据
├── experiments/<run_id>/  # 候选 / 消融原始证据
├── logs/                  # 长跑日志、loadavg、机器干扰记录
└── cases/                 # 合成边界用例（零时长 / 紧内存 / K=2V / 死锁反例）
```

每个 `run_id` 目录必须至少包含：

| 文件 | 内容 |
| --- | --- |
| `meta.json` | 时间、`run_id`、label、git SHA（sgs 与 baseline）、Python、loadavg 起止、显式预算 B、种子、命令、用例集合与聚合哈希 |
| `cmd.txt` | 完整可复现命令行（含 `PYTHONPATH`、`PYTHONDONTWRITEBYTECODE`） |
| `env.txt` | `python3 -VV`、`uname -a`、`nproc`、`free -g`、`git -C <worktree> rev-parse HEAD` |
| `<case>.out` | 求解器原始输出（未裁剪） |
| `<case>.stdout` / `<case>.stderr` | 求解器原始 stdout/stderr |
| `<case>.json` | 逐例记录：exit、wall、CPU、`TIME`（官方）、本地 judge 的 `ok/time/lb/groups`、超时/非法原因 |
| `summary.json` / `summary.md` | 逐例与汇总：合法数、均值/几何均值/最坏 wall、相对基线比率 |

**追加不覆盖**：同一 `run_id` 不复用；重跑生成新目录。正式报告只引用 `runs/` 内存在的目录。

---

## 6. 预算协议

### 6.1 硬约束

- **单例求解墙钟 ≤ 10 s**（题面 §5.4，含进程启动与输出落盘）；超时该例 0 分。
- 判题器耗时**不占**求解器预算；但端到端对照时两者都记录。
- 不允许为了赢对照而调大预算；同一次 A/B 中两边的显式预算必须**逐例相同**。

### 6.2 显式预算 B（同预算对照的唯一合法形式）

`B = auto_budget(n_ops)`，`n_ops = nmb · L · 10`，规则与 `src/solver/solve_all.py` 一致：

| `n_ops` | B（秒） |
| --- | --- |
| `> 200 000` | 6.2 |
| `≤ 200 000` 且 `> 20 000` | 7.2 |
| `≤ 20 000` | 7.6 |

- 正式对照**必须显式传** `--budget B`（不要依赖默认值，避免两边实现漂移）。
- 基线 worktree 与候选 worktree 用**同一张表**计算 B；`B` 与 `n_ops` 写进 `meta.json`。
- 官方 50 例：40 例 `B=7.6`、10 例 `B=7.2`（`n_ops` 640–76 800，无 200k 以上）。
- battery：`b05/b06/b07/b09` 为 640k op → `B=6.2`；其余按上表。
- 若某例 wall 逼近 10 s（≥ 9.5 s）或出现 `TO`，该例标记可疑，重复 3 次取最坏值重报，
  并记录当时 `loadavg`。

### 6.3 端到端墙钟

- "同端到端预算"指**同一显式 B + 同一 10 s 硬上限**，不是"谁跑得久谁赢"。
- 同时记录：求解进程 wall（含启动）、求解 CPU、判题 wall、总 wall。
- 若候选把 frontier 作为**额外候选**接入 `solve_case`，必须共享同一份 B（不能
  `baseline_budget + frontier_budget`）；若因此挤掉原搜索预算，必须原样报告回归，
  不能只报 `min(旧, 新)`。

---

## 7. 计时与随机性协议

1. **串行正式测时**：一次只跑一个求解进程（`jobs=1`），不与其他成员/团队并发跑重活；
   开始与结束各记一次 `loadavg`，写进 `meta.json`。机器被占用导致 `loadavg(1m) > 6`
   时，该批标注 `contended: true`，正式结论需在低负载下复测。
2. **预热**：正式批前先跑 12 例 fast 子集一次（丢弃结果），让文件缓存与解释器预热。
3. **交替与重复**：正式 A/B 在同一会话内按 **B → C → C → B**（ABBA）四趟执行；
   若时间不允许，最低要求是每边一整趟 + 对 wall 差异 > 10% 的用例补测。禁用"只挑好
   的一次"。
4. **固定种子**：现有 ILS 的种子硬编码在代码里（`solve.py` 用
   `20261020 + 7919·index`，`sched.improve_sequences` 默认 `20261020`），不得改动。
   任何新增随机成分必须接受显式 seed 并写入 `meta.json`；正式批用固定 seed 列表
   `[20261020]`，重复测同一 seed。
5. **不许按用例名/预存输出特判**；不许缓存跨进程复用结果冒充计算。
6. **原始输出保留**：stdout/stderr/exit/wall/CPU/`.out` 全部留档，报告只做汇总，
   不删除失败与超时记录。

---

## 8. 用例矩阵与阶段

### 8.1 集合

| 集合 | 规模 | 用途 | 阶段 |
| --- | --- | --- | --- |
| `official50` | 50（`data/official/Problem/cases`） | 评分主集 | 探索期用 12 例 fast 子集；冻结后全量 |
| `samples7` | 6 样例 + mini | 格式/退化形态/手算复核 | 每轮 |
| `battery13` | 13（主工作树，只读） | 大规模、紧内存、极端偏斜 | 探索期选 5 例；冻结后全量 |
| `boundary` | 合成，见 §8.2 | 零时长 / 紧内存 / K=2V / 死锁反例 | 每轮 |

fast 子集（12 例）：`r16_p4_trap, r24_p4_block, r32_p8_ramp, r64_v2_c2, r64_v8_c8d,
r128_v8_c8a, r256_v4_c4, x03_lr_trap_p3, x05_lr_tight_p6, x13_lr_twochunk_p8,
x18_vl_tight_small, x19_vl_trap4_fs4`（与 `tools/run_official.py --subset fast` 一致）。

battery 探索子集建议：`b03-m256`（中紧）、`b05-maxmb`（640k 宽松）、`b06-maxmb-tight`
（640k 最紧）、`b08-narrow`（跨节点窄带）、`b13-balanced-compute`（均衡计算）。

### 8.2 合成边界用例（放 `runs/frontier/cases/`，**不得**写入官方 `cases/`）

| 编号 | 构造 | 验证点 |
| --- | --- | --- |
| `bd-zero-comm` | `P=1`（`x=0`）或 `payload=0`，其余非零 | 零时长操作必须输出、不占引擎；本地/官方 `Movl` 差异单列 |
| `bd-tight-mem` | `M` 只比 `Mexp + 1·U + 1·Uact` 多 0–1 个单位 | 两个峰值分别取峰；同刻双缓冲被本地计入时是否仍合法 |
| `bd-k2v` | `V=2, K=4`，两块层数不均 | 镜像配对、两块共用引擎与内存；与 `K=V` 同配置对照 |
| `bd-deadlock` | `V=1,K=1,L=2,nmb=2`，扣除参数与通信峰值后激活容量恰为 2 | 逐时刻不超内存 ≠ 可完成；实现必须靠预留/安全状态避免死锁或明确失败回退 |
| `bd-ex5`/`bd-mini` | 现有 `cases/ex5.in`、`cases/mini.in` | 本地保守口径的已知分歧样本 |

### 8.3 两阶段

- **探索期**（t2/t4）：fast 12 + samples7 + battery 5 + boundary，全部记录但不作最终结论；
  允许反复迭代，但每轮都必须留 `runs/frontier/experiments/<run_id>/`。
- **冻结验证期**（t4 冻结 → t5）：official50 全量 + battery13 全量 + samples7 + boundary，
  串行 ABBA，双判分器；只认这一阶段的数字作"采用/否决"依据。

---

## 9. 消融矩阵（必须是"同配置"）

固定输入、`V/P/K/PSI/MAP`（取基线在同一例上的配置）与预算，只换调度内核/门控/前瞻：

| 组 | 内容 | 期望/判据 |
| --- | --- | --- |
| A | 同窗口、同优先规则下的事件驱动内核 vs 基线列表调度 | 若声称"工程加速"：`Time` 应逐例相等（或解释差异来源）；记录构造耗时、堆/队列访问计数 |
| B | 去掉 `mb−W` 入口边，改为生命周期内存门控（按卡组峰值预留） | 同预算下 `Time` 收益、峰值内存、合法率；紧内存用例不得非法 |
| C | 有界前瞻/束搜索（含"暂时等待下一有效事件"分支），限制分支与复制成本 | 与 A/B 单独对比；大规模自动降级的证据 |

规则：

- A 组只能称"等价/加速"，不能称"新解空间"；B/C 若只换了 priority 或堆键，必须如实归类。
- 每组的 `Time`、构造耗时、`peak_comm`/`peak_act`/`used`、合法率分开报，禁止混在一起算总账。
- 任何"收益"都要给同预算对照；回退/超时/非法一律计入分母。

---

## 10. 复现命令

```bash
# 0) 环境（每次正式跑都记录）
cd /home/rainy/hackathon/work-frontier-sgs
python3 -VV; uname -a; nproc; free -g
git -C . rev-parse HEAD
git -C /home/rainy/hackathon/work-frontier-baseline rev-parse HEAD

# 1) 单例（生产接口；stdout 只有映射，日志走 stderr；exit 0/1/2/3）
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python3 src/solver/solve_all.py cases/ex1.in runs/frontier/experiments/<run_id>/ex1.out

# 2) 基线（只读 worktree + 不写 pycache，产物重定向到 sgs 的 runs/）
cd /home/rainy/hackathon/work-frontier-baseline
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python3 src/solver/solve_all.py \
  /home/rainy/hackathon/work-frontier-sgs/cases/ex1.in \
  /home/rainy/hackathon/work-frontier-sgs/runs/frontier/baseline/<run_id>/ex1.out

# 3) 本地判分（更保守的第二道闸；JSON 供工具解析）
cd /home/rainy/hackathon/work-frontier-sgs
PYTHONPATH=src python3 -m judge eval <case.in> <out> --json

# 4) 官方判分（成绩权威；单例）
cd data/official/Problem
python3 grader.py <case.txt> <out>          # stdout 只有 TIME 数字

# 5) 官方 50 例串行（官方口径，solver-only 10s；探索期可用，正式以自建串行 harness 为准）
cd data/official/Problem
python3 run_all.py --timeout 10 \
  --cmd "python3 /home/rainy/hackathon/work-frontier-sgs/src/solver/solve_all.py"

# 6) 六样例 + mini（每个 ≤ 题面值；注意 ex3 的 6072 不是当前证据）
PYTHONPATH=src python3 src/solver/solve_all.py --cases ex1 ex2 ex3 ex4 ex5 ex6 mini \
  --out runs/frontier/experiments/<run_id>/samples --budget 7.6 --check

# 7) manifest 刷新（只读，不改源码）
python3 tools/frontier_manifest.py --sgs . \
  --baseline /home/rainy/hackathon/work-frontier-baseline \
  --out runs/frontier/manifest.json
```

> 正式成绩由 t3 的串行 harness（`tools/frontier_bench.py`）产出：它逐例调用上面的单例
> 接口，保存 `.out`/stdout/stderr/exit/wall/CPU，再用**官方 grader** 与**本地 judge**
> 各判一次；`run_all.py` 仅作交叉核对。

---

## 11. 接口约定（给 algorithm-engineer / t2+）

### 11.1 生产接口（不得改）

- CLI：`python3 src/solver/solve_all.py <case.in> [<out>]`；单例模式 stdout **只有映射**，
  日志走 stderr；退出码 `0` 成功 / `1` 无合法解 / `2` 用法或输入错误 / `3` 写输出失败。
- 输出格式：`V P` / `PSI` / `K [ψ…]` / `MAP` / `SCHEDULE`；`K=1` 时 PSI 只写 `1`。
- 判分交互只经子进程（`solver/judgedbridge.py`）；`solver/` **不得 import `judge.core`**。

### 11.2 调度内核接口（建议签名，t2 落地）

```python
# src/solver/frontier.py（新模块，默认关闭）
def schedule(case, plan, *, window=None, deadline=None, seed=20261020,
             variant=None, mode="event", lookahead=0) -> sched.Schedule | None
```

- 入参 `case`（`solver.casein.Case`）、`plan`（`solver.formula.Plan`）只读，不得修改。
- 返回 `sched.Schedule`（`start`/`end` 按 `mb*L*10 + ℓ*10 + op` 线性索引；`time`、
  `window`、`variant` 同现有字段），**或** `None` 表示死锁/预算内无完整解；
  绝不返回半份调度。
- `deadline` 为 `time.monotonic()` 的绝对时刻，必须在内核内定期检查（构造、校验、输出
  余量都算在预算内）。
- 提交前必须依次通过：`sched.check_schedule(case, plan, result) == []`、
  `sched.memory_usage(case, plan, result.start, result.end)[0] == True`、
  `sched.render_output(case, plan, result, map_rows)`；再交 `judgedbridge.judge_eval`。
- `memory_usage` 的内部峰值口径与本地 judge 一致（零时长通信**计入**），因此它是比官方
  更严的门；门不过就回退到已验完整解。
- 确定性：同输入 + 同预算 + 同 seed 必须得到同一份调度；若因 deadline 截断导致不确定，
  需改用确定性迭代上限并在文档说明。

### 11.3 实验入口（t2 交付）

`tools/frontier_solve.py`：可单独调用新内核，固定 `V/P/K/PSI/MAP`，输出与生产相同的
映射文件；默认不接入 `solve_case`，需显式开关。它的输出必须能被 §10 的判分命令直接消费。

### 11.4 对照工具（t3 交付）

`tools/frontier_bench.py`：串行、逐例独立进程、显式预算、保存原始证据（见 §5），
同时调用官方 grader 与本地 judge；支持 `--label baseline|candidate`、`--solver`、
`--cases`、`--budget auto|<float>`、`--timeout 10`、`--out <run_id>`。
必须显式设置 `PYTHONPATH` 指向**对应 worktree** 的 `src`，防止串用另一版本。

---

## 12. 合规自检（每轮提交前）

- [ ] 只改了 `work-frontier-sgs`；baseline 仍 `detached` 且 `git status --porcelain` 为空。
- [ ] `data/official/**`、`src/judge/**`、`Makefile` 与 §2 哈希一致（`tools/frontier_manifest.py` 可复核）。
- [ ] 没有装新依赖、没有起服务、没有调用其他模型/另建团队。
- [ ] `make test` 与 `PYTHONPATH=src python3 -m judge.core.acceptance` 结果已记录；
      基线已有的失败原样对照，不悄悄改断言。
- [ ] 每份结论都有同预算 A/B 与原始 `runs/frontier/` 证据；失败/超时/非法都保留。
- [ ] 未默认启用新路线；未用更大预算或预存结果充当算法收益。

---

## 13. 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-10-30 | v1 | t1 冻结：worktree、哈希、内存/区间/引擎口径、预算与计时协议、用例矩阵、接口约定；本次冻结提交的完整 SHA 见 `runs/frontier/manifest.json → worktrees.sgs.head_sha` |
