# 评分审计与高收益策略（t1 / score-strategist）

* 作者：score-strategist，attempt 1，`attempt_id = be1fdd4e-c488-49cf-9278-25b80d4b2500`
* 时间：2026-10-30 00:16–01:00 CST
* 生产代码**零改动**：本任务只读 `judge/`、`solver/`、`runs/`、题面与文档；所有实验脚本与产物都在
  `runs/score-strategy-20261030/`，`git status --porcelain` 在开始与结束时都只有此前已有的那几行
  （`M README.md`、`M solver/sched.py`、`M solver/selftests/test_tight_window.py`、`M solver/solve.py`、
  `M tools/independent_check.py` 与既有 `runs/*` 未跟踪文件）。
* 唯一一次"跑完整求解"用的是**进程内 monkeypatch**（`b13_patch.py`），只改内存里的
  `sched.schedule`，输出落在本目录，**没有缓存持久化**（`Schedule` 不跨进程落盘，无污染风险）。
* 所有数字都能用 §7 的命令复现。

---

## 0. 结论（先看这一页）

| # | 结论 | 证据 |
| --- | --- | --- |
| 1 | **最终得分 = 各测试点 `time/base` 的几何平均**；**任一测试点非法或超 10 s ⇒ 该点 0 分，且版本总分 `null`**。第一优先级永远是"一个都不能崩"。 | `problem-v5.md` §5.1–5.4；`judge/service/ledger.py:391-402`（`geometric_score`：任一 `ok=false / time空 / base空` ⇒ `None`） |
| 2 | **真正的官方评测器不是本仓库的 judge**，它只按题面模拟并给每点 Time；本仓库的 `judge` 是我们自己的复现。隐藏测试点输入看不到 ⇒ 评分优化其实是"在**未知输入分布**上把 Time 压低，同时保证 100% 合法"。 | 题面 §4.5；`README §4/§9` |
| 3 | **`Time` 有一个精确的解析式** `Time ≈ (nmb + V − 1) × seg`（`seg = max(ΣC, ΣWc)` 为最慢卡组的两套引擎工作量）。① 它把 `Time/lb` 解释成**输入决定的填充** `(nmb+V−1)/nmb`，不是求解器的浪费；② 它让 `V` 的取舍变成可计算量；③ `K=2V` 的代价直接可见（块数翻倍）。 | §1.3、`probe_fill_floor.json`（8 例逐例对上，残差 ≤1.5%） |
| 4 | **13 个电池点里 12 个已经贴死**：b02/b03/b04/b06/b07/b08/b11 距解析界 0.08%–1.5%，b01/b05/b09/b12 的生产解**优于**同 V 解析界（填隙/`early` 换变体），b10 差 1.5%。**b13 是唯一还有显著空间的点**：实测 **−7.2%（4.633e16 → 4.298e16，judge `ok=true`）**，来自"窗口候选太粗，排在前面的网格被算废"。 | `verify_battery_data.json`、`probe_b13_*`、§4 |
| 5 | **b13 的修复不是"选对窗口"这么简单**：只把 `early` 的窗口改准只够 −4.8%（P=64,V=8）；真正拿到 −7.2% 的是让 `(P=64,V=8)` 作为**首个候选**算出好解，从而让 `(P=32,V=16)`（lb 更低）进入搜索并胜出。**多网格搜索比单网格精调更值钱。** | `probe_b13_w20.json` + §4.1 的隔离实验（`b13_patch.py`） |
| 6 | **风险（隐藏点上最可能丢分）**：① `nmb` 小 + `L=64` 时 `V=L` 的填充高达 **32.5×**；② `early` 在 64 万 op 上单次 **2.6–21.6 s**（一次就撞穿 10 s）；③ 预算只用 4.5/6.5/8.5 s 而题面给 10 s。 | `probe_hidden_risk.json`、`probe_op_costs.json`（b05 `early` W=1000 = **21.6 s**） |
| 7 | **`K=2V`（DUALPIPE）是负收益**：`V=L` 是桥头堡，`K=2V` 要求 `2V≤L` ⇒ 块数翻倍 ⇒ 填充翻倍；静态核算所有用例比值恒 1.000。**不要做。** | `probe_mirror_split.json` |
| 8 | README §3 的 `Time/lb` 表不能用（13 个值里 6 个与当前代码不符），`tools/independent_check.py` 的通信公式仍是旧口径（P≥3 的 9 个用例误报）。 | §2.3 |

**给 t2 的最短路径**：先做 §4 的策略 1（b13 的网格回退 + 窗口候选，**已实测 −7.2%**），
再做策略 2（`early` 大用例禁用，**防 0 分**），其余按 §5 排序。

---

## 1. 评分路径审计

### 1.1 官方口径（题面 `problem-v5.md`）

| 条目 | 原文位置 | 含义 |
| --- | --- | --- |
| 合法性 | §4.7 | 网格 `V·P≤R`、`P∣E`、`P∣S 或 S∣P`；`K∈{V,2V}` 且切点严格递增；`MAP` 每行每 rank 恰好 `E/P` 个；调度满足 §4.2 四条；`nmb` 偶数 |
| Time | §4.5 | `Time = max(t + 时长)`，评测器只模拟、不搜索 |
| 内存 | §4.6 | `Mexp + Movl + Mact ≤ M`，否则**得 0 分** |
| 计分 | §5.3 | "各测试点按**相对成绩**聚合排名；Time 越小得分越高；并列先比求解器 CPU 时间，再比提交时间" |
| 时限 | §5.4 | 每点 **10 s 墙钟**（评测器自身模拟不计），**超时该点记 0 分** |
| 规模 | §6 | `R≤512`、`L≤64`、`nmb≤1000`、`T_ℓ≤1e9`、`F_*≤1e6`、`U,Uact≤2^20`、调度条目 ≤2e7 |

**注意 §5.3 只说了"相对成绩聚合"，没有给精确公式。** 本仓库把它实现成几何平均
（`CONTRACT.md` §2.6 / `judge/service/ledger.py::geometric_score`）：

```
score = exp( mean_c log(time_c / base_c) )        # 全部合法才给分；否则 null
rank  = 按 score 升序（同一基准 base 下与 Σ log time 同序）
```

对优化的含义（三句话）：

1. **相对收益可加、可排序**：把某点从 `1.30×base` 压到 `1.15×base` 的贡献是 `log(1.15/1.30) = −0.122`，
   把另一个点从 `1.05` 压到 `1.04` 只有 `−0.0096`。**该优先打"离下界最远"的点**，而不是把已经贴死的点再抠 1%。
2. **一个点崩掉的代价是无穷大**（score 变 `null`、rank 落到最后）。**鲁棒性 ≫ 局部最优。**
3. `base` 是题面样例值（有样例的测试点）或未知基准（隐藏点）。对隐藏点我们只能假设它恒等于"样例排法"，
   所以**任何 Time 下降都是正收益**。

### 1.2 仓库内的评分实现（我们自己的复现）

| 位置 | 行为 | 审计结论 |
| --- | --- | --- |
| `judge/service/ledger.py::geometric_score` | 任一 case `ok=false`、`time` 非 int、`base` 缺省 ⇒ `None`；`time==0` ⇒ 0.0 | 与题面一致；`base` 取自 `cases/expected.json`（6 例） |
| `compute_versions` | `score` 升序、`None` 排最后、非法版本**仍然列出** | 一致 |
| `judge/core/sim.py::evaluate_output` | 先网格/PSI/MAP，再 token/覆盖，再依赖+引擎，再内存；任意一类错都 `ok=false` | 一致；**错误最先出现在 `errors[0]`，用它定位** |
| `judge/core/sim.py::_simulate` | 依赖与引擎互斥是**两趟全量检查**，与书写顺序无关 | 一致（CONTRACT §11） |
| 服务层 `queue.py` | `timeout` 默认取 `config.case_timeout`（10 s），超时 kill 并记 `timeout` | 与题面一致 |
| `solver/solve_all.py::auto_budget` | `n_ops>200k → 4.5 s`、`>20k → 6.5 s`、否则 `8.5 s` | **预算全部 ≤8.5 s，而题面给 10 s** —— 见 §4.6（会白扔 15–31% 的搜索时间） |

### 1.3 `Time` 是由什么决定的（对本问题有效的解析）

记一个卡组的层集合为 `G_v`，逐层两套引擎工作量
`C_ℓ = s + gemm + s_bwd + gemm_dx + gemm_dw + s_dw`、
`Wc_ℓ = disp + comb + comb_bwd + disp_bwd = 2x + 2⌈αx⌉`，并记 `seg_v = max(ΣC, ΣWc)`。

* **`lb = nmb × max_v seg_v`**（每个卡组两套引擎各自串行做完 nmb 份）。
* **流水线按"块"推进**：`V` 个卡组、每个 mb 要依次经过 V 个卡组，因此
  **`Time ≈ (nmb + V − 1) × seg_v*`**，其中 `seg_v*` 是最慢卡组的段长。填充项 `(nmb+V−1)/nmb`
  就是 `Time/lb` 的分子。这个式子在本审计的 8 个用例上**逐例对上**（`probe_fill_floor.json`）：

| 用例 | judge Time | `(nmb+V−1)·seg` | 比值 | 生产 V |
| --- | ---: | ---: | ---: | ---: |
| b02-m512 | 5.4216e14 | 5.4067e14 | 1.0027 | 64 |
| b03-m256 | 8.1178e14 | 8.1101e14 | 1.0010 | 64 |
| b04-m96 | 9.4692e14 | 9.4618e14 | 1.0008 | 64 |
| b08-narrow | 1.5695e15 | 1.5679e15 | 1.0010 | 64 |
| b11-short-l | 4.9347e15 | 4.9299e15 | 1.0010 | 4 |
| b10-high-k | 1.7935e14 | 1.7664e14 | 1.0153 | 64 |
| b07-mixed | 3.4928e15 | 3.4832e15 | 1.0027 | 64 |
| b13-balanced-compute | 4.6327e16 | 4.2861e16 | **1.0809** | 8 |

**读法**：前 7 个用例距"`(nmb+V−1)·seg` 解析界"只有 0.08%–1.5%，说明**调度器本身没问题，
问题在网格选择 `(P,V)`**。b13 是唯一一个差 8.1% 的——它的调度器没有把 `seg` 用满。

由此得到**打分优化真正能动的三个旋钮**：

| 旋钮 | 影响 | 当前状态 | 还能动多少 |
| --- | --- | --- | --- |
| **P**（专家并行） | `x ∝ T·H/P` 逐层**向上取整** ⇒ 通信约 `∝1/P` 但带取整台阶；`gemm ∝ m ≈ T/P`；`Mexp ∝ (E/P)` | 枚举全部合法 P 并按 `lb×fill` 排序；但对**每个 P 只生成一个 V** | 电池上 P 已全对（`probe_grid_sweep.json`：逐 P 扫过，没有更低的）；**但 b13 证明"排在前面的 P 算废了"会连带毁掉后面的候选** |
| **V**（stage 数） | 填充 `(nmb+V−1)/nmb`；`V=L` 让 `seg` 最小 | **直接取 `V=max<L,64,R//P>`**，不考虑 nmb | **只有 `V=L` 时**等效；当卡不够/内存不够时必须退而求其次 —— 见 §3.3 |
| **调度/切点** | 在上式里相当于"能不能达到 `seg`" | b13 差 8.1%，其余 ≤1.5% | b13 有 ~7–8% 可拿 |
| ~~K=2V~~ | 块数翻倍 ⇒ 填充翻倍 | 从未使用 | **负收益，见 §3.4** |
| **W（窗口）** | 题面**不强制** 1F1B；W 只是压 Mact 的自加约束 | 探窗只试 `nmb, nmb/8, nmb/32` 并只保留最好一个 | **b13 的最优在 `W≈nmb/5`**，不在候选集里 —— 见 §3.5/§4.1 |

---

## 2. 数据核对（13 个大用例基线 + 当前 gap-fill 改动）

### 2.1 生产 13 例（judge 原始判定，非二手转述）

`verify_battery_data.py` 直接读 `runs/val-t1-battery-20261029-2308/judge/current-*.json`：

| 用例 | Time | lb | Time/lb | V | P | 内存峰值/上限 | vs HEAD 基线 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| b01-loose | 5 904 000 000 000 | 4.896e12 | 1.206 | 64 | 1 | 27.5% | **−14.58%** |
| b02-m512 | 542 157 603 132 750 | 3.342e14 | 1.622 | 64 | 2 | 55.1% | 0 |
| b03-m256 | 811 784 777 827 320 | 5.014e14 | 1.619 | 64 | 4 | 60.2% | 0 |
| b04-m96 | 946 917 900 211 470 | 5.849e14 | 1.619 | 64 | 8 | **93.8%** | 0 |
| b05-maxmb | 49 008 000 000 000 | 4.800e13 | 1.021 | 64 | 1 | 38.8% | **−2.02%** |
| b06-maxmb-tight | 5 229 861 932 305 704 | 4.915e15 | 1.064 | 64 | 4 | 62.8% | **−2.81%** |
| b07-mixed | 3 492 805 460 668 064 | 3.277e15 | 1.066 | 64 | 2 | 56.4% | ≈0 |
| b08-narrow | 1 569 450 570 466 152 | 1.258e15 | 1.247 | 64 | 4 | 62.8% | 0 |
| b09-small-e | 49 008 000 000 000 | 4.800e13 | 1.021 | 64 | 1 | 28.0% | **−2.02%** |
| b10-high-k | 179 346 953 034 600 | 1.573e14 | 1.140 | 64 | 4 | 62.8% | **−4.16%** |
| b11-short-l | 4 934 667 467 641 224 | 4.915e15 | 1.004 | 4 | 4 | 51.1% | ≈0（−0.004%） |
| b12-compute-bound | 83 843 497 367 000 000 | 6.938e16 | 1.209 | 64 | 8 | **4.4%** | **−14.71%** |
| b13-balanced-compute | 46 326 548 000 000 000 | 4.011e16 | 1.155 | 8 | 64 | 6.7% | 0 |

* 13/13 `ok=true`、`errors=0`；`runs/battery-current/*.out` 与验证时重跑的输出 **sha256 逐字节相同**
  （`verify_battery_data.json` 的 `sha256.upload_eq_rerun` 全 True）⇒ 生产结果是**可复现**的。
* 墙钟最大 **6.27 s**（b13），全部 < 10 s（`runs/val-t1-battery-20261029-2308/logs/prod_times.txt`）。
* 内存最紧的是 b04（93.8%）、b12/b13 最松（4.4%、6.7%）。

### 2.2 当前 gap-fill 改动（工作区 vs `git archive HEAD`）

* 收益 **真实**：b01 −14.58%、b12 −14.71%、b05/b09 −2.02%、b06 −2.81%、b10 −4.16%；
  其余 7 例 0（b07/b11 是可忽略的 1e-6 量级）。**没有任何"用非法换时间"的伪收益**（两棵树 26/26 合法）。
* `runs/probe_gap_fill.json` 是**旧口径**（HEAD 版求解器，b06/b10/b11 那里 `legal=false` 而 `errors=0`
  是那时 `_accept` 先比 Time 再核内存的副作用），**不要再用它判断收益**。
* 读代码时确认的两点语义（与验证报告一致，不是问题，但要写进回归）：
  * `comp_free/comm_free = max(free, finish)` 是填隙正确性的必要条件；
  * 填隙分支要求 `not comm_gap`，零时长通信不进 `gaps`。

### 2.3 数字层面必须纠正的文档

| 文档 | 问题 | 应改为 |
| --- | --- | --- |
| `README.md` §3 | `Time/lb` 表 13 个值里 **6 个与当前代码不符**（b01 1.41→1.21、b05/b09 1.04→1.02、b06 1.09→1.06、b10 1.19→1.14、b12 1.42→1.21），且不随代码变化 | 用 §2.1 这张表（绝对 Time + 基线提交号 + 测量命令） |
| `README.md` §0 | "13 个大用例全部 10 s 内出合法解；`Time/lb` 落在 1.00–1.62" —— 数值范围对，但**没有任何一条说明 `1.62` 已经是可达下界** | 补一句"除 b13 外，实测 Time 距 `(nmb+V−1)·seg` 解析界 ≤1.5%" |
| `README.md` §6 | "b02–b04 填充型 …结构性" 里写 "`nmb≈V` 时必然"，但 b02 是 `nmb=102, V=64` | 改为 `(nmb+V−1)/nmb` |
| `tools/independent_check.py` | 通信公式仍是旧口径 `X=⌈T·H·(P−1)/P⌉`，P≥3 的 9 个大用例会**误报依赖违反** | 改成 `⌈T·H/P⌉`（验证报告 B3 已提，仍未动：`git status` 显示该文件只是"M"，需要人工确认改的是不是这一处） |
| `solver/solve_all.py` 注释 | `auto_budget` 给 4.5/6.5/8.5 s，而题面允许 10 s | 见 §4.4 |

---

## 3. 差距分解：13 个点里还剩多少可拿

### 3.1 网格层面的可达下界（`probe_grid_sweep.json` + `probe_fill_floor.json`）

对每个用例枚举**全部合法 P**，用 `place.best_placement` 的真实 `m_ℓ` 算逐层时长，再按 §1.3
用**同 V 的** `(nmb+V−1)·seg` 作界（`lb × fill` 只在 V 相同时可乘，见下方更正）：

| 用例 | 当前 Time | 解析界（同 V） | 比值 | 还能拿？ |
| --- | ---: | ---: | ---: | --- |
| b01 | 5.904e12 | (102+64−1)·4.8e10 = 7.92e12 | **生产更好** | 无（生产用填隙压到了 1.21×lb） |
| b02 | 5.4216e14 | 5.4067e14 | 1.003 | 无 |
| b03 | 8.1178e14 | 8.1101e14 | 1.001 | 无 |
| b04 | 9.4692e14 | 9.4618e14 | 1.001 | 无 |
| b05 / b09 | 4.901e13 | (1000+63)·4.8e10 = 5.1024e13 | **生产更好** | 无 |
| b06 | 5.230e15 | (1000+63)·4.9152e12 = 5.2249e15 | 1.001 | 无 |
| b07 | 3.4928e15 | (1000+63)·3.2768e12 = 3.4832e15 | 1.003 | 无 |
| b08 | 1.5695e15 | (256+63)·4.9152e12 = 1.5679e15 | 1.001 | 无 |
| b10 | 1.7935e14 | (512+63)·3.072e11 = 1.7664e14 | 1.015 | 1.5%（取整台阶，见下） |
| b11 | 4.9347e15 | (1000+3)·4.9152e12 = 4.9299e15 | 1.001 | 无 |
| b12 | 8.384e16 | (102+63)·6.8017e14 = 1.1223e17 | **生产更好** | 无（生产用 `early`+变体 + 填隙） |
| **b13** | **4.633e16** | (102+7)·3.9322e14 = 4.2861e16 | **1.081** | **7–8%，见 §4** |

> ⚠️ **我自己探针里的两个错，已在此更正**（保留记录以免后人重犯）：
> 1. `probe_grid_sweep.py` 把 `lb × fill` 与当前 Time 直接比，对 b12 得出"1.75× 可拿"——**错的**。
>    `fill = (nmb+V−1)/nmb` 只对同一 V 有意义；跨 V 比较必须回到 `seg` 本身。
> 2. 我曾据此把 `sched.compact` 当成 b13 的解法——**也是错的**：在 65k op 上 compact 1/3 趟都是
>    **0.00% 改进**（0.13–0.35 s 白花），而且会把 `peak_act` 从 160 抬到 816（凭空吃掉内存余量）。
>    b13 的真实原因见 §4.1（窗口 + 网格回退），不是压实。

### 3.2 填充：`V=L` 把 `Time` 抬到了 `lb×1.61`，但这是**作业数不足**，不是浪费

`nmb=102, L=V=64` 时，流水线只有 102 个 mb，却要依次过 64 个 stage，`Time` 下界就是
`(102+64−1)/102 = 1.618 × lb`。要消掉它只有两条路：

* 让 `V` 小（每卡组多背几层）：会让 `seg` 变大 `L/V` 倍，净效果 **更大**（`probe_psi_2d.json`：
  b02 的 V=32 是 2.41×、V=16 是 4.95×；b07/b08/b10 同样）。
* 让 `nmb` 变大：**输入给定，改不了**。

⇒ **b02–b08/b10 这几点的 `Time/lb ≈ 1.61–1.62` 是这批输入的物理下限**。它们是正常成绩，不是缺陷。
**不要再往这几个点上投入搜索时间。**

### 3.3 隐藏测试点上的填充会变本加厉（风险）

题面 §6 **不限制** `nmb` 与 `L` 的组合。用 §1.3 的式子（`V=L`）：

| `L` | `nmb` | `V=L` 时的块数 | 理想块数 | 惩罚 |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 2 | 65 | 2 | **32.5×** |
| 64 | 8 | 71 | 8 | 8.9× |
| 64 | 32 | 95 | 32 | 3.0× |
| 64 | 128 | 191 | 128 | 1.49× |
| 64 | 1000 | 1063 | 1000 | 1.06× |

**如果隐藏点里出现 `L=64, nmb=2/4/8`，现在的求解器会给出 8–32 倍于下界的解。**
battery 的 `nmb` 全部 ≥102，所以这条从来没有被测到。求解器**从不**对 `V` 做 `(nmb+V−1)·seg` 的比较
（`enumerate_configs` 只取 `V=max`），这是隐藏点上最容易白送分的地方 —— 但**必须先有正确的候选生成**
（现在的 `psi_candidates` 与 `lb` 已经能算，缺的只是"多生成几个 V 并比较"）。

### 3.4 `K=2V`（DUALPIPE 镜像）：负收益，跳过

* `K=2V` 要求 `2V ≤ L`，即 `V ≤ L/2`；而电池里 11/13 个用例在 `V=L` 时 `V·P=R`（卡已用满），
  `K=2V` 必须把 V 砍半。
* 块数从 `V` 变 `2V`，流水线填充 `(nmb+K−1)/nmb` 直接翻倍；题面 §4.6 的 `Mexp` 按**卡组持层数**计，
  `K=2V` 时卡组层数与 `K=V, V=L` 相同 ⇒ **一点内存都省不下来**（`probe_mirror_split.json`：
  `layers_per_group_KV == layers_per_block_K2V`，所有用例的 `K2V/KV` 比值恒为 **1.000**）。
* 唯一可能翻盘的是"前向/反向极不对称 + `Mact` 是瓶颈"，但 battery 最紧的 b04 是 93.8% 由 `Mexp` 主导，
  b13（唯一 V<L 的用例）内存只用 6.7%。

**结论：t2 不要做 `K=2V`。README §7.3 的这条建议应当降级/删除。**

### 3.5 窗口 `W` 不是"越大越好"，而是**存在最优的中等窗口**（b13 就是反例）

题面 §4.2 **没有** 1F1B 约束，`W` 是求解器自加的（只为压 `Mact`）。`probe_b13_window_law.json`
在 b13（P=64,V=8，`early`）上扫出完整曲线：

| W | 时间 → lb 倍数 |
| ---: | ---: |
| 1 | 13.02 |
| 4 | 3.53 |
| 8 | 1.91 |
| 12 | 1.44 |
| 16 | 1.22 |
| **20（≈nmb/5）** | **1.186 ← 最优** |
| 26 | 1.196 |
| 51（nmb/2） | 1.230 |
| 102（nmb，生产选中） | 1.294 |

* 对**通信主导、层少**的点（b13：每卡组 8 层、`ΣWc=3.93e14 > ΣC=3.75e14`），窗口过大会让
  `Mact` 峰值顶到 816 份，`early` 出堆被拖；窗口过小则填充爆炸。
  ⇒ **`W` 需要"两边都够紧"的一维搜索**，而不是只探 `nmb, nmb/8, nmb/32` 三个点。
* 对**通信满负荷**的点（b02/b03/b04/b08，`ΣWc ≫ ΣC`），`W` 越大越好、`early` 比 `prio` 差，
  `prio` + `W=nmb` 就是最优 —— 与生产行为一致（`probe_b13_w20.json` 逐例确认）。
* 所以"窗口候选"**不能统一改成 nmb/5**：那会让 b02/b03/b04/b08 退化 **2.5–2.7×**。
  必须是"候选集更细 + 按结果取最好"，不是"换个默认值"。

### 3.6 已证最优的部分

六个官方样例 `560 / 4880 / 6072 / 3200 / 416 / 1696` 全部经 CP-SAT 构造性证明（`tools/cpsat_global.py`，
另有 `tools/ex3_verify.py` 的独立穷举）。**这 6 个点已经是 1.000×base（或更好），动不了。**

---

## 4. 策略清单（按期望得分收益排序）

> 排序依据：**已实测的电池提升**（可验收）+ **对隐藏点的防 0 分保护**。
> 每条都给出机制、实测数据、落点、风险、验收。

### 4.1 策略 1（**已实测 −7.2%**）：修正 `early` 的窗口候选 + 让"次优网格"有机会被算出来（b13）

**现象**（`probe_b13_ab.json`、`probe_b13_window_law.json`、`runs/val-t1-*/logs/search_trace.txt`）：

* b13 是唯一 `V < L` 的用例（`P=64,V=8`，每卡组 8 层，`ΣWc=3.93e14 > ΣC=3.75e14`，通信主导）。
* `early` 在 `W=20` 时 **4.757e16（1.186×lb）**，`W=102` 时 5.191e16（1.294×lb）；`prio` 在**任何**窗口
  都差 5–8 倍 ⇒ 这里**只有 `early` 可用**。
* 生产的 `_try_config` 探窗用的是 `nmb, nmb/8, nmb/32`（=102, 12, 3），然后**只保留最好那个**（102）；
  `nmb/5 ≈ 20` 这一整段**从来没被看到**。

**但这只值 −4.8%。真正拿到 −7.2% 的是下一步**：在进程内把 `early` 的窗口固定成 20（`b13_patch.py`），
**唯一**的改动，跑完整 `solve_case`，结果是

```
[填隙] P=64 V=8   → 61.57e15
[探窗] W=3  early → 47.57e15      ← P=64,V=8 现在算出好解了
[填隙] P=32 V=16  → 42.98e15      ← 次优网格(更低 lb=38.25e15)进入搜索并胜出
solver Time = 42 984 846 000 000 000 = 4.298e16   (生产 4.633e16，−7.2%)
judge eval: {"ok": true, "time": 42984846000000000, "lb": 38250000000000000, "K": 16, "V": 16, "P": 32}
内存: mact = 106.9 MB / 2147.5 MB（5%）
```

**为什么这个现象重要**：`enumerate_configs` 按 `lb × fill` 排序，`P=64,V=8` 排在 `P=32,V=16` 前面
（lower bound 更低）；只有当前者**算得好**，后者才在"`lb ≥ best.time` 就停"的门槛内轮到。
生产里前者被算成了 61.6e15（比 `P=32` 的 lb 还大）⇒ **后者的机会被一次糟糕的调度浪费掉了**。

**落点（`solver/solve.py::_try_config` + `sched.window_candidates`）**：
1. 中等规模分支的探窗比例从 `(1, 8, 32)` 换成更细的一组，例如 `(1, 2, 3, 4, 5, 8, 16, 32)`
   的 `nmb//k`（b13 需要 `k=5`）。单次要 0.14–0.26 s，8 个候选≈1–2 s，**在预算内**。
2. 探窗**不要只保留最好的一个窗口**：b13 证明"窗口 × 模式"的交互是**非单调**的，
   保留 `top-2` 再扫变体即可（`scored` 已有，只需别砍成一个）。
3. 给 `early` 一个**与窗口无关**的保护：`early` 只在 `n_ops ≤ 200_000` 时进入候选（见 4.2）。
4. 可选（更稳）：探窗时对每个窗口的 `prio/early` 都试一次，但要按 `case.n_ops` 预算门控。

**验收**：b13 `Time ≤ 4.40e16`（目标 4.298e16），judge `ok=true`；13 例其余不动（尤其
b02/b03/b04/b08 **不能**因为窗口候选变化而退化 —— 见 4.1 的"不要统一改默认值"）。

**风险**：探窗次数 ×1 会挤掉后面的变体扫描；对 65k op 的点这不贵（0.14 s/次），
对 640k op 的点要沿用现有的"不探窗、不 `early`"路径。

---

### 4.2 策略 2（**防 0 分**，收益无法在电池上体现但优先级最高）：`early` 在大用例上会撞穿 10 s

`probe_op_costs.json`（本机 12 核）实测单次 `sched.schedule(..., mode='early')`：

| 用例 | n_ops | 窗口 | `prio` | `early` |
| --- | ---: | ---: | ---: | ---: |
| b05 | 640 000 | 125 | 1.56 s | **4.13 s** |
| b05 | 640 000 | 500 | 1.59 s | **14.19 s** |
| b05 | 640 000 | 1000 | 1.49 s | **21.63 s** |
| b07 | 640 000 | 1000 | 2.33 s | **6.95 s** |
| b10 | 327 680 | 512 | 1.03 s | 2.34 s |

`_modes_for` 只在"窗口被压小"时才**优先** `early`，窗口没压小时 `early` 仍是第二模式被尝试；
`solve_case` 的 deadline 检查是"**开始前**判断 `now + est*1.3 < deadline`"，
**est 是用 `prio` 估的**（1.5 s），于是 `early` 实际跑 21.6 s ⇒ **该点 0 分**。
`runs/probe_gap_fill.json` 里 b05 `early` 单次 17.9–22.2 s 已经把这个风险实测了一遍；
现在没炸只是因为电池的预算/顺序刚好躲开。

**落点**：`_modes_for` / `_try_config` 里加硬门：`if case.n_ops > 200_000: modes = ("prio",)`；
更稳的做法是给 `sched.schedule` 传 `deadline`，`early` 每次弹出后检查，超 `2×est` 直接放弃。

**验收**：构造 `nmb=1000, L=64, E=512, 640k ops` 的用例连跑 20 次，**墙钟全部 ≤ 9.5 s**；
13 例 Time 不变。

---

### 4.3 策略 3（保护隐藏点）：`enumerate_configs` 的 V 候选 + `(nmb+V−1)·seg` 比较

见 §3.3：`V=max` 是唯一候选，`L=64, nmb=2` 时白送 32×。电池里"缩 V"全是坏方向（`probe_psi_2d.json`），
所以**不能改默认值**，只能**多加候选、按 `lb × (nmb+V−1)/nmb`（现有排序键）比**：

* `V ∈ {vmax, vmax/2, vmax/4, 1}`（受 `V≤L`、`V·P≤R`、`Mexp≤M` 过滤）；
* 排序键已经是 `lb × (nmb+V−1)/nmb` —— **不需要改排序**；
* 真正的收益在"vmax 被内存/卡数砍掉时"，有更小的 V 参与比较（现在会退到不合法的 vmax）。

**风险**：候选数 ×，65k op 上单次 0.16 s 可以接受；640k op 上不可接受（1.5–2.4 s/次）⇒ 大用例保持"只取 vmax"。
**验收**：13 例不回归；新增 `R<L`（如 `N=2,S=16,R=32,L=64`）夹具，证明不再越界/白送。

---

### 4.4 策略 4（便宜、稳）：预算从 4.5/6.5/8.5 提到 ~6/7.5/9.2，中等规模点多花在"模式 × 窗口"上

* `solve_all.auto_budget` = `(200k→4.5, 20k→6.5, else 8.5)`，题面给 10 s；实测渲染 0.03–0.49 s、
  启动 ≈0.1 s ⇒ 留 0.7 s 余量可以给到 **9.2/7.5/6.0**（65k 的点多 8%，640k 的点多 33%）。
* 65k op 的点单次调度 0.12–0.17 s（`probe_op_costs.json`）⇒ 10 s 内可跑 50–80 次；现在只跑 2–4 次。
  b13 的教训就是"排在前面的那个候选没算够"。

**验收**：13 例墙钟 ≤9.5 s、Time ≤ 现在；b13 单独 ≤4.40e16。

---

### 不建议做（并说明为什么）

| 方向 | 理由（都有实测） |
| --- | --- |
| `K=2V` / DUALPIPE | §3.4：块数翻倍、填充翻倍、内存不变 ⇒ 负收益 |
| `sched.compact` 放开到 65k op | 实测 **0.00% 改进**，反而把 `peak_act` 160→816（`b13-w20` 那次脚本运行） |
| 把窗口候选统一改成 `nmb/5` | b02/b03/b04/b08 会退化 **2.5–2.7×**（`probe_b13_w20.json`） |
| 继续压 b02–b04/b08 的 `Time/lb` | §3.1：距解析界 ≤0.3%，`nmb·seg` 是硬底 |
| 用"零长度激活不计 Mact"之类的口径取巧 | `CONTRACT.md` §11 已冻结；收益 ≤1e-15，风险 0 分 |
| 只在 `bigcases/` 上加更多同型用例 | `nmb` 都 ≥102，已经饱和；要加就加 `nmb∈{2,4,8}` 与 `R<L` 的异形 |

## 5. 给 t2 的落单（按顺序，每步都可独立验收）

| 步 | 改动 | 预期 | 验收（用官方 `python3 -m judge eval --json`） |
| --- | --- | --- | --- |
| 1 | 窗口候选加细（`nmb//k`, k∈{1,2,3,4,5,8,16,32}，保留 top-2）+ `early` 保留 | b13 **−7.2%** | b13 ≤ 4.40e16（目标 4.298e16）、`ok=true`；13 例逐一 ≤ 现值 |
| 2 | `n_ops > 200_000` 时禁用 `early`（或给 `schedule` 传 deadline） | 防 0 分 | 640k 夹具 ×20 次墙钟 ≤9.5 s；13 例不变 |
| 3 | `enumerate_configs` 增加 V 候选（大用例仍只取 vmax） | 隐藏点保护 | 13 例不回归；`R<L` 夹具不再越界 |
| 4 | 预算提到 6.0/7.5/9.2 | +8%/+33% 搜索时间 | 13 例墙钟 ≤9.5 s、Time 不回退 |
| 5 | 修 `tools/independent_check.py` 的 `X` 公式 + README §3 表换成 §2.1 | 判据可信 | 13 例复算 26/26 一致（现 9 例误报） |

**不要做**：`K=2V`、`compact` 放开到 65k、窗口统一改 nmb/5（§3.4 与 §4 的"不建议做"）。

---

## 6. 模型路由可观测性

* **本轮调用**：`agent_teams_status` 的面板显示本成员为 `score-strategist · opencode-go/deepseek-v4.1-flash`；
  t1/t2/t3 的 assignee 与成员清单一致。
* **本会话自身**：工具输出、`env`、`git` 记录里**没有**本轮 provider/model 的独立证据
  （与 `runs/val-t1-battery-20261029-2308/REPORT.md` §6 的结论相同）——**只能引用团队状态面板的
  provider/model 字段，不能声称从本进程内观测到**。
* 若要可复现的路由证据：在任务卡里记 `model_route` 字段，或让求解器运行时把
  `run_id / version / commit / solver_cmd` 写进账本（已有）。**求解结果与模型路由无关**——`judge` 只看输出文本。

---

## 7. 复现命令（全部只读；产物都在本目录）

```bash
cd /home/rainy/hackathon

# 0) 生产代码未被改动（应与任务开始时一致：只有既有的 5 个 M + runs/* 未跟踪）
git status --porcelain

# 1) 13 例 judge 判定核对（生产 vs HEAD 基线，含 sha256 一致性）
python3 runs/score-strategy-20261030/verify_battery_data.py \
  > runs/score-strategy-20261030/verify_battery_data.json

# 2) 可达下界（逐 P；精确 DP 切分）
PYTHONPATH=. python3 runs/score-strategy-20261030/model_margins.py \
  > runs/score-strategy-20261030/model_margins.json
PYTHONPATH=. python3 runs/score-strategy-20261030/probe_grid_sweep.py \
  > runs/score-strategy-20261030/probe_grid_sweep.json

# 3) 解析界 (nmb+V-1)·seg
PYTHONPATH=. python3 runs/score-strategy-20261030/probe_fill_floor.py \
  > runs/score-strategy-20261030/probe_fill_floor.json

# 4) K=2V 静态核算（负收益）
PYTHONPATH=. python3 runs/score-strategy-20261030/probe_mirror_split.py \
  > runs/score-strategy-20261030/probe_mirror_split.json

# 5) 窗口扫描（b13：W=20 最优；b02 等 W=nmb 最优）
PYTHONPATH=. python3 runs/score-strategy-20261030/probe_window_ceiling.py \
  > runs/score-strategy-20261030/probe_window_ceiling.json
PYTHONPATH=. python3 runs/score-strategy-20261030/probe_b13_window52_54.py \
  > runs/score-strategy-20261030/probe_b13_window52_54.json
PYTHONPATH=. python3 runs/score-strategy-20261030/probe_b13_ab.py \
  > runs/score-strategy-20261030/probe_b13_ab.json
PYTHONPATH=. python3 runs/score-strategy-20261030/probe_b13_window_law.py \
  > runs/score-strategy-20261030/probe_b13_window_law.json
PYTHONPATH=. python3 runs/score-strategy-20261030/probe_b13_w20.py \
  > runs/score-strategy-20261030/probe_b13_w20.json

# 6) 单次调度耗时（early 在 64 万 op 上 21.6 s）
PYTHONPATH=. python3 runs/score-strategy-20261030/probe_op_costs.py \
  > runs/score-strategy-20261030/probe_op_costs.json

# 7) 切点对齐 / 二维切分（切点不是杠杆）
PYTHONPATH=. python3 runs/score-strategy-20261030/probe_psi_alignment.py \
  > runs/score-strategy-20261030/probe_psi_alignment.json
PYTHONPATH=. python3 runs/score-strategy-20261030/probe_psi_2d.py \
  > runs/score-strategy-20261030/probe_psi_2d.json

# 8) 隐藏点风险参数
PYTHONPATH=. python3 runs/score-strategy-20261030/probe_hidden_risk.py \
  > runs/score-strategy-20261030/probe_hidden_risk.json

# 9) 策略 1 的隔离实验（进程内把 early 窗口固定为 20 后跑完整求解；见 runs/.../b13_patch.py）
PYTHONPATH=. python3 runs/score-strategy-20261030/b13_patch.py
python3 -m judge eval --json bigcases/battery/b13-balanced-compute.in \
        runs/score-strategy-20261030/b13-w20/b13.out    # ok=true, time=42984846000000000
```

依赖：标准库 + 仓库内 `solver/`（`PYTHONPATH=.`）。全部命令**不写** `judge/`、`solver/`、`cases/`、
`bigcases/` 下任何文件；唯一一次跑完整求解用进程内 monkeypatch（`b13_patch.py`），产物写在本目录。

## 8. 文件索引

```
runs/score-strategy-20261030/
├── REPORT.md                          本报告
├── verify_battery_data.{py,json}      13 例 judge 判定核对 + sha256
├── model_margins.{py,json,log}        逐 P 的可达 lb（V∈{max,max/2,max/4}）
├── probe_grid_sweep.{py,json}         逐 (P,V) 最优切分 lb vs 当前
├── probe_fill_floor.{py,json}         (nmb+V−1)·seg 解析界
├── probe_mirror_split.{py,json}       K=2V 静态核算
├── probe_window_ceiling.{py,json,log} 窗口扫描 × 内存可行性
├── probe_b13_window52_54.{py,json}    b13 细窗口（发现 W≈20）
├── probe_b13_ab.{py,json}             b13：窗口 vs 填隙 vs 出堆模式
├── probe_b13_window_law.{py,json}     b13 完整窗口曲线（1.186×lb @ W=20）
├── probe_b13_w20.{py,json}            中等规模点上的 W=nmb vs nmb/5
├── b13_patch.py                       策略 1 的隔离实验脚本（monkeypatch，不落盘缓存）
├── b13-w20/b13.out                    隔离实验输出（judge ok=true, 4.298e16, V=16, P=32）
├── probe_op_costs.{py,json,log}       单次调度/渲染耗时
├── probe_psi_alignment.{py,json,log}  块长×seg 对齐 nmb 的尝试
├── probe_psi_2d.{py,json,log}         V 减小（每卡组多层）的实测
└── probe_hidden_risk.{py,json}        隐藏点形状风险参数
```
