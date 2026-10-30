# t1 独立验证报告 —— 第二轮 MoE 求解器优化（完整电池）

* 验证人：battery-validator，attempt 1，`b5d51302-cb96-4368-b238-f744643fccb7`
* 时间：2026-10-29 23:08–23:3x CST
* 生产代码零改动：开始/结束 `git status` 恒为 `M solver/sched.py`、`M solver/solve.py`（无 checkout/reset/stash/编辑）；
  开始与结束 `sha256(solver/sched.py)=60874dfb559bcecb450f14083bdaf3b436af694c6102ac74cd45ad8b5ac9f1a9`、
  `sha256(solver/solve.py)=fd906b352d5a16e53dbdefa1ac33d7cfd5fe88f23fee804c8136dc3c800b0a6e`，一致。
* 全部产物在本目录（`runs/val-t1-battery-20261029-2308/`）；`current/` 是工作区生产代码跑出的 13 个输出，
  `iso-head/` 是 `git archive HEAD | tar -x` 的整仓基线，`iso-head-out/` 是基线跑出的 13 个输出，
  `judge/` 是官方 `python3 -m judge eval --json` 的原始判定，`checks/` 是官方校验命令的输出，
  `logs/` 是模块路径、耗时、搜索轨迹与探针。

---

## 0. 结论

| 检查项 | 结果 |
| --- | --- |
| 13 个 battery 用例全部在 10 s 内出解 | **通过**：生产最大墙钟 **6.27 s**（b13），基线最大 6.21 s；无超时、rc 全 0 |
| 官方 judge 判合法 | **通过**：26/26 份输出（13 生产 + 13 基线）`ok=true`、`errors=0` |
| 第三方独立复算（不 import judge） | **通过**：修正其过时的通信公式后，26/26 与 judge 的 `Time/lb/groups/engines` 完全一致 |
| 官方六例 | **通过**：`560 / 4880 / 6072 / 3200 / 416 / 1696`，judge 逐例同值 |
| solver 单测 / independent_check | **通过**：8/8 unittest OK；`tools/independent_check.py` 7/7 |
| judge 基线校验（附加） | **通过**：acceptance 7/7、service selftest 23/23、judge 单测 66 OK |
| 收益 vs README 旧表（时间视角，无独立记录） | **10/13 未变**，3 例更差；README 的 `Time/lb` 整体不可复现（§3.4） |
| 收益 vs 真实基线 `git archive HEAD`（可复现） | **9 例改善、4 例零改善**；b01 **−14.58%**、b12 **−14.71%**，b05/b06/b09/b10 小改善（§3.2） |
| fill_gaps 依赖 / 引擎互斥 / 零时长 / 内存语义 | **无违规**，但有 1 条**语义口径风险**与几处正确性依赖声明（§4） |
| 模型路由 | **无法确认**：本会话无可观测的 provider/model 信息（§6） |

**判定：可以放行。** 生产输出全部合法、在时限内、与官方 judge 和第三方复算一致；b01/b12 的收益是真实的
（相对隔离基线 −14.6%/−14.7%，judge 复核）。但 README §3 的 `Time/lb` 表不能被当前代码复现，应更新为时间口径或删除。

---

## 1. 隔离基线（避免"仓库根截胡"）

`runs/val-t2-20261029-2233/REPORT.md` §2 指出：`solver/solve_all.py` 顶部把**仓库根**插到 `sys.path`，
若从仓库根以脚本方式跑，`PYTHONPATH` 指向的影子 `solver/` 永远不会被用到。本报告不复用 shim，而是整仓
`git archive` 解包，并**从 `iso-head/` 目录作为 cwd** 运行，再用 `logs/show_files.py` 打印实际导入路径：

```
# 生产（cwd=/home/rainy/hackathon）
solver.sched       -> /home/rainy/hackathon/solver/sched.py
solver.solve       -> /home/rainy/hackathon/solver/solve.py
fill_gaps in schedule sig: True
'gap-fill' in solve.py source: True
prune line: 'continue  # 按 lb×fill 排序，后续候选的裸 lb 仍可能更小'

# 基线（cwd=runs/.../iso-head，HEAD=b7a6a93）
solver.sched       -> runs/val-t1-battery-20261029-2308/iso-head/solver/sched.py
solver.solve       -> runs/val-t1-battery-20261029-2308/iso-head/solver/solve.py
fill_gaps in schedule sig: False
'gap-fill' in solve.py source: False
prune line: 'break  # 已按 lb 升序：后面的只会更差'
```

* 工作区 `md5(sched.py)=4a5b9a7e…`／`md5(solve.py)=7a534e67…`；HEAD blob：
  `git rev-parse HEAD:solver/sched.py` = `5715bee…`、`HEAD:solver/solve.py` = `ba9354a…`（与工作区不同）。
* `solve.py` 本会话前已被改动（t2 报告记录为 `9811e539…`，现为 `7a534e67…`），但 `sched.py` 未变；
  §3.2 的数值是**按当前代码重新跑**得到的，不依赖 t2 的旧结论。

运行方式（`run_battery.sh` + `logs/_runner.py`）：以 `__main__` 方式执行 `solver/solve_all.py <in> <out>`（等价于
线上单例调用形态），记录 wall/maxrss；然后对 26 份输出逐份跑官方 `python3 -m judge eval --json`（`logs/judge_all.py`）。

---

## 2. 单例时限

| 指标 | 生产 | 基线 |
| --- | --- | --- |
| 最大墙钟 | **6.267 s**（b13） | 6.214 s（b12） |
| 子进程求解自计最大 | 6.24 s（b13） | 6.18 s |
| maxrss 最大 | 190.3 MiB（b07） | 144.2 MiB（b06） |
| 超 10 s / 非零退出 | 0 / 0 | 0 / 0 |

预算：`auto_budget` 对 >200 000 op 给 4.5 s、>20 000 op 给 6.5 s，其余 8.5 s；加上渲染落盘，最大墙钟仍在 10 s 内，
但 b13/b12/b02/b03/b01 的 6.1–6.3 s 已用到 6.5 s 预算的 ~96%，余量主要来自"预算 ≤ 6.5 s"。生产侧观察到更大的内存峰值
（b07 190 MiB vs 基线 139 MiB，b05 149 vs 118，b06 188 vs 144），原因是 `fill_gaps=True` 时多维护一份优先表（nmb·L·10 元组）。

---

## 3. 结果核对

### 3.1 生产（当前工作区）13 个用例

官方 judge 判定全部 `ok=true`、`errors=0`：

| 用例 | P | V | judge Time | lb | Time/lb | solve s | wall s | 峰值内存/上限 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| b01-loose | 1 | 64 | 5,904,000,000,000 | 4,896,000,000,000 | 1.21 | 5.85 | 5.891 | 590,413,824/2,147,483,648 |
| b02-m512 | 2 | 64 | 542,157,603,132,750 | 334,233,600,000,000 | 1.62 | 6.08 | 6.123 | 295,763,968/536,870,912 |
| b03-m256 | 4 | 64 | 811,784,777,827,320 | 501,350,400,000,000 | 1.62 | 6.04 | 6.077 | 161,546,240/268,435,456 |
| b04-m96 | 8 | 64 | 946,917,900,211,470 | 584,908,800,000,000 | 1.62 | 4.59 | 4.628 | 94,437,376/100,663,296 |
| b05-maxmb | 1 | 64 | 49,008,000,000,000 | 48,000,000,000,000 | 1.02 | 3.55 | 3.589 | 826,462,208/2,147,483,648 |
| b06-maxmb-tight | 4 | 64 | 5,229,861,932,305,704 | 4,915,200,000,000,000 | 1.06 | 4.59 | 4.640 | 192,488,448/268,435,456 |
| b07-mixed | 2 | 64 | 3,492,805,460,668,064 | 3,276,800,000,000,000 | 1.07 | 4.73 | 4.779 | 330,031,872/536,870,912 |
| b08-narrow | 4 | 64 | 1,569,450,570,466,152 | 1,258,291,200,000,000 | 1.25 | 5.54 | 5.579 | 185,155,584/268,435,456 |
| b09-small-e | 1 | 64 | 49,008,000,000,000 | 48,000,000,000,000 | 1.02 | 2.44 | 2.478 | 290,535,424/1,073,741,824 |
| b10-high-k | 4 | 64 | 179,346,953,034,600 | 157,286,400,000,000 | 1.14 | 2.81 | 2.848 | 169,287,680/268,435,456 |
| b11-short-l | 4 | 4 | 4,934,667,467,641,224 | 4,915,200,000,000,000 | 1.00 | 4.48 | 4.509 | 160,236,288/268,435,456 |
| b12-compute-bound | 8 | 64 | 83,843,497,367,000,000 | 69,377,771,358,000,000 | 1.21 | 6.11 | 6.152 | 91,254,016/2,147,483,648 |
| b13-balanced-compute | 64 | 8 | 46,326,548,000,000,000 | 40,108,032,000,000,000 | 1.16 | 6.24 | 6.267 | 150,922,240/2,147,483,648 |

`runs/battery-current/*.out`（生产方上传的权威结果）与本次重跑**逐字节相同**（b01/b05/b09/b12/b13 sha256 一致），
说明其结果可复现。所有输出的时间戳序列非降序、行数等于操作数（例如 b13 38 870 行 = 8×64×10 唯一时刻）。

### 3.2 与真实基线（`git archive HEAD`，b7a6a93）对比

| 用例 | 生产 Time | 基线 Time | 改善 | 判定 |
| --- | --- | --- | --- | --- |
| b01-loose | 5,904,000,000,000 | 6,912,000,000,000 | **−14.58%** | 真实 |
| b02-m512 | 542,157,603,132,750 | 542,157,603,132,750 | 0 | 无 |
| b03-m256 | 811,784,777,827,320 | 811,784,777,827,320 | 0 | 无 |
| b04-m96 | 946,917,900,211,470 | 946,917,900,211,470 | 0 | 无 |
| b05-maxmb | 49,008,000,000,000 | 50,016,000,000,000 | **−2.02%** | 真实 |
| b06-maxmb-tight | 5,229,861,932,305,704 | 5,381,044,662,971,220 | **−2.81%** | 真实 |
| b07-mixed | 3,492,805,460,668,064 | 3,492,807,937,646,768 | −0.00007% | 可忽略 |
| b08-narrow | 1,569,450,570,466,152 | 1,569,450,570,466,152 | 0 | 无（输出逐字节相同） |
| b09-small-e | 49,008,000,000,000 | 50,016,000,000,000 | **−2.02%** | 真实 |
| b10-high-k | 179,346,953,034,600 | 187,125,693,610,200 | **−4.16%** | 真实 |
| b11-short-l | 4,934,667,467,641,224 | 4,934,872,569,361,020 | **−0.0042%** | 真实（极小） |
| b12-compute-bound | 83,843,497,367,000,000 | 98,307,789,776,000,000 | **−14.71%** | 真实 |
| b13-balanced-compute | 46,326,548,000,000,000 | 46,326,548,000,000,000 | 0 | 无（输出逐字节相同） |

* 13/13 生产与基线输出均被 judge 判 `ok=true`；所以**没有任何"用非法换时间"的伪收益**。
* 搜索轨迹（`logs/search_trace.txt`，4.5 s 预算复采）：**12/13 的最终解就是新的 `gap-fill` 候选**（`[填隙] …`），
  b13 走 `early` 列表调度（其 gap-fill 候选 Time=61,569,005,000,000,000 更差，但 `mem_ok=True`，排除内存/合法性被挡）。
* 内存峰值两版都远低于上限（最紧的 b04：94.4/100.7 MiB）。生产侧峰值分布不同（Movl 峰值可达 262 MB 的用例降到 26.7 MB），
  因为填隙把通信交错打散；b02–b04 等 512/256/96 MiB 用例的 Mexp 由 P 决定，两版相同。

### 3.3 官方六例 / 单测 / 独立复算

```
python3 solver/solve_all.py --check --json   → ok=true，ex1..ex6 = 560/4880/6072/3200/416/1696（judge 同值），selftests_ok=true
python3 -m unittest discover -s solver/selftests -t . -q → Ran 8 tests, OK
python3 tools/independent_check.py           → 7/7 与 judge + expected.json 完全一致
python3 -m judge.core.acceptance             → 7/7
python3 -m judge.service.selftest            → 23/23
python3 -m unittest discover -s judge/tests -q → Ran 66 tests, OK
```

附加：（a）第三方 `tools/independent_check.py` 的用例集合只覆盖 `cases/*`，我把它扩展到 13 个大用例
（`logs/indep_battery.py`）；（b）对 fill_gaps 路径做 12 个随机小用例 × 2 400 次构造调度（`logs/fill_fuzz.py`），
`sched.check_schedule` 零违规；再把 12 个小用例的 `solve_case` 输出交给官方 judge（`logs/fill_judge.py`），**12/12 合法且 Time 一致**。

> **工具缺陷（非本次改动引入）**：`tools/independent_check.py` 的通信公式仍是 v4 旧口径 `X=⌈T·H·(P−1)/P⌉`（第 14、124 行），
> 与 `judge/core/model.py` 及 `problem-v5.md`（"每个**对端**的字节数 X=⌈T·H/P⌉"）不一致。直接用它跑大用例时
> 13 例中 9 例报"依赖违反"（b03/b04/b06/b08/b10/b11/b12/b13 等，且两版结果同样失败，与本次改动无关）。
> 我把 `X` 换成 `⌈T·H/P⌉` 后（`logs/indep_battery2.py`，其余不改），26/26 与 judge 完全一致 ⇒ 判题口径以 judge 为准是正确的，
> 但 README §8.1 推荐的"独立复算"在 P≥3 的用例上会误报。**建议修正该工具并加一个大用例回归**（见 §7-B3）。

### 3.4 与 README 旧结果比较（重点看 b01/b05/b09/b12/b13）

README §3 只有 `Time/lb` 表，没有绝对时间记录。用**当前生产**代码重算的比值与 README 对不上：

| 用例 | README 表 | 本次生产重算 | 一致？ |
| --- | --- | --- | --- |
| b01-loose | 1.41 | **1.21** | ✗ |
| b05-maxmb / b09-small-e | 1.04 | **1.02** | ✗ |
| b06-maxmb-tight | 1.09 | **1.06** | ✗ |
| b10-high-k | 1.19 | **1.14** | ✗ |
| b02/b03/b04 | 1.62 | 1.62 | ✓ |
| b07 / b08 / b11 / b13 | 1.07 / 1.25 / 1.00 / 1.16 | 1.07 / 1.25 / 1.00 / 1.16 | ✓ |
| b12-compute-bound | 1.42 | **1.21** | ✗ |

即 README 的 13 个比值里有 6 个比当前生产**更差**，而 b02/b03/b04/b07/b08/b11/b13 的时间与基线逐字节/逐位相同 ⇒
那 6 个旧比值**不可能是"当前代码之前的版本"跑出来的**（否则未改动的 7 例也该不同）。README 的表格与现存任何一棵代码树都对不上，
**不能用它判定收益**。因此本节收益一律以可复现的 `git archive HEAD` 基线为准（§3.2）：

* **b01**：6.912e12 → 5.904e12（−14.58%），比值 1.41 → 1.21。**真实收益。**
* **b12**：98.3078e15 → 83.8435e15（−14.71%），比值（按同 lb）1.42 → 1.21。**真实收益**（t2 曾观察到"b12 无改善"，
  那是当时 `solve.py` 尚未改成"对 P 无关地触发填隙"的版本；现版本 b12 的 P=8 也进了填隙分支）。
* **b05 / b09**：50.016e12 → 49.008e12（−2.02%），比值 1.04 → 1.02。**真实但小**；两例输出不同、judge 均合法。
  注意这两例的 P=1、通信全零时长，改善来自填隙把计算旁支塞进空隙。
* **b13**：时间与基线**完全相同**（输出逐字节相同）。README 的 1.16 与实测一致 ⇒ b13 **没有收益**，也没有回归。

---

## 4. fill_gaps 语义专项

### 4.1 依赖表（与 judge 逐条对拍）

```
judge.core.model.DEPS : ((), (), (1,), (2,0), (3,), (3,), (5,), (5,), (6,4), (5,))
solver.formula.DEPS   : ((), (), (1,), (2,0), (3,), (3,), (5,), (5,), (6,4), (5,))
```

即 `comb ≥ gemm,s`、`disp_bwd ≥ gemm_dx,s_bwd`、`s_dw ≥ comb_bwd`、`s_bwd/comb_bwd ≥ comb`、跨层 `s,disp ≥ 上一层 comb`、
`s_bwd,comb_bwd ≥ 下一层 disp_bwd` 全部到位。填隙只改动"起点选择"，不改依赖闭包：它只在**已留出的空闲段**里提前放置操作，
`ready` 只由前驱与已占引擎决定，因此**不会造成依赖提前**。fuzz（2 400 次）+ 13 例 judge `errors=0` 支持这一点。

### 4.2 引擎互斥

* 生产把 `comp_free/comm_free` 从 `= finish` 改为 `= max(free, finish)`（基线是直接覆盖）。**这是必要的**：填隙会把操作插到
  "空闲段"里，使 `finish` 可能早于 `free`，旧写法会**让引擎水位回退**并导致重叠。改法正确，且 fuzz 零冲突。
* 零时长操作：插入分支有 `dur and` 守卫，`dur==0` 时既不插入也不更新 `free`（与 judge `duration <= 0: continue` 一致）。
* 零时长通信 + `comm_gap`：填隙分支要求 `not comm_gap`，所以旧的"零时长通信也拉开距离"逻辑保持原样。

### 4.3 内存语义

* `_accept` 之后仍走 `sched.memory_usage`（含 Movl/Mact 闭区间峰值与零长度通信计入 Movl），13 例摘要与 judge `groups` 逐字段相同（§3.3）。
* **语义风险（需注意，不是违规）**：题面 §4.6 的 `Mact` 是「前向已完成、反向未完成」的 `(mb,ℓ)` 计数，而反向开始按题面是 `s_bwd`。
  填隙把 `s_bwd` 启动时刻压到 `comb` 完成**同一时刻**时，该 `(mb,ℓ)` 的激活窗口长度为 0。solver 的 `memory_usage` 与 judge 的
  `peak()` 都是「同刻先开后关」的闭区间峰值 ⇒ 不把这 0 长度窗口算进 `Mact`。若判题方按保守口径（窗口必须严格 >0）计，就会多算一块。
  实测影响：b10 有 509/32 768、b11 有 997/4 000 个这样的零窗口；对 b11 输出做"零窗口右移 1"的同构变换后 judge 仍 `ok=true`，
  Time 49,346,674,676,412,224 → 49,346,674,676,422,221（**+10 毫秒级**，相对变化 2e-15），b10 同理。
  ⇒ 口径风险**不影响结论**，但建议在 CONTRACT 里把"零长度激活是否计入 Mact"写死（§7-B1）。

### 4.4 调度语义依赖（正确性的隐含前提）

生产 `early` 模式依赖「零时长操作可以在前驱尚未完成时入堆」——因为 `rem` 只在前驱排上（而非完成）时递减；
排程阶段 `end` 可能仍为 −1 被当作 0 比较。当前电池用例里该情形全部由 `ready=0` 兜住（fuzz + 13 例零违规），
但这是一条**未被单测锁定**的隐含不变量：建议补一条"零时长 + `early` 模式 + 窗口约束"的回归（§7-B4）。

---

## 5. 运行时限与回归

| 项目 | 结果 |
| --- | --- |
| 单例 ≤ 10 s | 通过（最大 6.27 s） |
| `--check` 六例全体 | 通过（含退化形态自测） |
| solver 8 单测 | 通过 |
| judge 66 单测 / acceptance 7/7 / 服务自检 23/23 | 通过 |
| independent_check 7/7 | 通过（但见 §3.3 工具缺陷） |
| 大用例输出可复现 | 通过（`runs/battery-current/*.out` 与本次重跑 sha256 一致） |

---

## 6. 模型路由

**无法确认。** 本会话的工具输出、环境变量（未发现 provider/model 相关项）与 `git` 记录都不含本轮调用所用的 provider/model；
只在文档层面能读到"team/session 配置"，没有可观测证据。故不给出任何路由断言。

---

## 7. 建议（按优先级；不阻塞放行）

* **B1** 在 `CONTRACT.md` / `judge` 注释中写明 `Mact` 对「零长度激活窗口」（`s_bwd` 起点 == `comb` 完成）的计法。
  当前实现按不计入，实测影响 ≤ 10 时间单位，但口径必须冻结。
* **B2** README §3 的 `Time/lb` 表有 6 个值与当前代码不符（§3.4），且不随代码变化——建议改为"绝对 Time + 基线提交号"两列并注明
  测量命令，否则后续无法判断收益。
* **B3** 修正 `tools/independent_check.py` 的 `X`（`⌈T·H·(P−1)/P⌉` → `⌈T·H/P⌉`），并在 `bigcases/battery` 上加一个大用例回归
  （当前 13 例中 9 例误报依赖违反，两版都是，容易把判题器当成坏掉）。
* **B4** 给 `sched.schedule(fill_gaps=True)` 与 `early` + 零时长组合补单测（`solver/selftests/test_tight_window.py` 目前 8 条不含填隙）。
* **B5** `fill_gaps` 候选在 b13 上产生 61.569e15 的较差解但仍被 `_accept` 正常丢弃，行为正确；可考虑把该候选限制在 `P` 小或 `x>0` 的形状，
  省下每次 ~0.5–1 s（b13 6.24 s 里占一大部分），给后续配置留预算。
* **B6** 生产内存峰值比基线高（b07 190 vs 139 MiB），大 nmb 用例可考虑用 `array('q')` 存优先键，降低峰值。

---

## 8. 文件索引

```
runs/val-t1-battery-20261029-2308/
├── REPORT.md                      本报告
├── run_battery.sh                 13 例 × 2 棵树 的墙钟/内存采集脚本
├── current/                       生产代码 13 例输出（.out/.stdout/.stderr）
├── iso-head/                      git archive HEAD 整仓基线（solver/ 为 HEAD blob）
├── iso-head-out/                  基线 13 例输出
├── judge/{current,iso}-*.json     官方 judge eval --json 原始判定（26 份）
├── checks/
│   ├── official-prod.json         官方六例 --check --json
│   ├── solver-selftests.txt / independent_check.txt / acceptance.txt / service-selftest.txt / judge-tests.txt
│   ├── fill-fuzz/{f*.in,f*.out}   fill_gaps 随机小用例
│   └── *.boundary-shift.out       零激活窗口右移 1 的敏感性输出（已交 judge）
└── logs/
    ├── prod_files.txt / isohead_files.txt   实际导入模块路径
    ├── prod_times.txt / iso_times.txt       wall/maxrss（每例）
    ├── search_trace.txt                     当前代码的搜索轨迹（[填隙]/[探窗]/[贪心]）
    ├── indep_battery*.py/.json              第三方复算（原版/修正版）
    ├── fill_fuzz.py/.json, fill_judge.py/.json
    ├── gapwitness.py/.txt, semi_stress.py, boundary_shift.py
    ├── zprobe*.py/.txt, zcheck-*.txt        零时长/缝隙探针
    └── sched_rows.txt                       行数与时间戳单调性抽查
```
