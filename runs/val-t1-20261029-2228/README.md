# t1 独立验证报告 —— 填隙调度（fill_gaps）与剪枝（break→continue）修复

* 验证人：validator（worker，attempt 1，`bd6890d8-bc6f-41eb-aa08-25834cc2e66b`）
* 时间：2026-10-29 22:28–22:5x CST（Asia/Shanghai）
* 被验对象：工作区**未提交**改动（`git status`：`M solver/sched.py`、`M solver/solve.py`），HEAD = `b7a6a93`
* 基线取法：`git show HEAD:solver/sched.py` / `git show HEAD:solver/solve.py` →
  `base-solver/solver/{sched,solve}.py`，用 `PYTHONPATH=<此目录> python3 solver/solve_all.py …`
  让 import 优先命中基线模块（其余模块 `__init__/formula/place/psi/exact` 与 HEAD 相同，未改动）。
  **没有** `git checkout/stash`，**没有**改任何生产代码；本目录之外只生成了开始时老进度的
  `runs/probe_*.json`（他人产物，未触碰）。
* 模型路由：本会话没有可观测的模型路由信息（无 API/网关日志、无 `provider/model` 回显），
  **无法确认**；报告只记录命令与实测数据。

---

## 0. 结论（先看这里）

| # | 结论 | 证据 |
|---|---|---|
| A | 当前提交上 **b01-loose / b12-compute-bound 的最终结果与基线完全相同**；12 个未优化维度没有产生任何改善 | `current/*.out` 与 `base/*.out` 逐字节无法区分（judge 判定一致），见 §3 |
| B | 未优化的 P=1 候选（延后 `gemm_dw/s_dw` + 填隙）本身是**合法且显著更好**的：b01 `5.904e12`（基线 6.912e12，−14.6%，lb 4.896e12）、b12 `3.69e17`（基线 4.32e17，lb 3.06e17） | §4 直接调度实验 |
| C | 该候选 **从未被真正评估**：新代码位于 `_try_config`（**第一个被评估的配置**）里，而 `enumerate_configs` 之后 `solve_case` 按 `lb×fill` 排序取 `configs[0]`；b01/b12 的 `configs[0]` 恰好是 **V=64,P=1**，于是 P=1 分支在列表调度开始前先把 4.5 s 预算烧光 → 返回一份未优化的列表调度（b01 6.912e12, b12 9.83e16） | §4.3/§4.4 实测 |
| D | `break→continue` 修复本身**逻辑成立但实际无效**：在两个用例上 `configs[0].lb × fill` 都是最小值，后续配置的裸 lb **全部更大**，`continue` 只会多跑 0 次迭代 | §3.3 |
| E | fill_gaps 与「P=1 优先打通往返 + 旁支延后」的实现**在小规模上正确**：110 个用例×配置点全部经 **judge 判合法**（200 次 judge 调用，fill 0/1、prio/early、自定义优先级的组合），Time 与求解器自检一致 | §5 |
| F | COMP/COMM 索引与依赖语义与判题器**逐项一致**；零时长语义与 `comm_gap` 在 fill_gaps 下的交互安全（必要条件出队规则） | §2 |
| G | 回归：六官方样例结果不变；solver 单测 8/8；`solve_all.py --check` 当前与基线均通过 | §3.1、§3.2 |

**一句话给负责人**：新调度器部件（fill_gaps / 延迟优先级）是好的（b01/b12 上比现基线好 14%/15%），
但**接线位置错了**——它没有参与竞争，反而因为 `cost["est"]` 共享而挤掉了本来更好的普通列表调度；
`break→continue` 也是零收益。这两处都需要在 `solve.py` 的接线层面修（不是 sched.py 的算法问题），
当前工作区状态**不建议**直接作为「改进」提交或作为新基线。

---

## 1. 环境与复现命令

```
Python 3.14.6  Linux，cwd=/home/rainy/hackathon
```

```bash
VD=runs/val-t1-20261029-2228
# 基线文件（只读提取，不 checkout）
for f in solver/sched.py solver/solve.py; do mkdir -p $VD/base-solver/$(dirname $f); git show HEAD:$f > $VD/base-solver/$f; done

# 1) 依赖/引擎索引对拍（solver vs judge）
python3 $VD/verify.py cmp-deps            # -> cmp-deps.json   （same_deps/same_engine/same_comp_ops = True）
# 2) fill_gaps 合法性探针（13 个大用例 + 5 个小用例，prio/early × fill 0/1）
python3 $VD/verify.py fill-fuzz           # -> fill-fuzz.json
# 3) 小用例上 fill_gaps × 自定义优先级，全部交 judge 判定
python3 $VD/judge_fill_fuzz.py            # -> judge-fill-fuzz.json  (rows=200 judge_fail=0 time_mismatch=0)
# 4) 六官方样例（当前 / 基线），带 judge 复核
python3 solver/solve_all.py --check --out $VD/official-current
PYTHONPATH=$PWD/$VD/base-solver python3 solver/solve_all.py --check --out $VD/official-base
# 5) b01/b12 单例（当前 / 基线），再逐份 judge
for c in b01-loose b12-compute-bound; do
  python3 solver/solve_all.py bigcases/battery/$c.in $VD/current/$c.out
  PYTHONPATH=$PWD/$VD/base-solver python3 solver/solve_all.py bigcases/battery/$c.in $VD/base/$c.out
  python3 -m judge eval bigcases/battery/$c.in $VD/current/$c.out --json > $VD/judge/current-$c.json
  python3 -m judge eval bigcases/battery/$c.in $VD/base/$c.out    --json > $VD/judge/base-$c.json
done
# 6) solver 单测
python3 -m unittest discover -s solver/selftests -t . -q     # Ran 8 tests OK
```

`solve_all.py` 单例模式按规模自动给预算：`n_ops=65280 > 20000 → 6.5 s`（b01/b12 均为此预算）。

---

## 2. 静态检查：COMP/COMM 索引、依赖、零时长语义

`verify.py cmp-deps`（`cmp-deps.json`）：

* `solver/formula.py:DEPS` 与 `judge/core/model.py:DEPS` **完全一致**（按名）：
  `s`=（无）、`disp`=（无）、`gemm`←disp、`comb`←gemm,s、`s_bwd`←comb、`comb_bwd`←comb、
  `gemm_dx`←comb_bwd、`gemm_dw`←comb_bwd、`disp_bwd`←gemm_dx,s_bwd、`s_dw`←comb_bwd
  —— 即题面 §4.2 原文（含 `comb≥s`、`disp_bwd≥s_bwd`、`s_dw≥comb_bwd` 三条）。
* `ENGINE` 两边都是 `(C,M,C,M,C,M,C,C,M,C)`，`COMP_OPS=(0,2,4,6,7,9)`、`COMM_OPS=(1,3,5,8)`
  一致；`OP_NAMES` 顺序一致。
* 跨层边：`sched._dep_tables` 给 `s`/`disp` 加 `−10+COMB`、给 `s_bwd`/`comb_bwd` 加 `+10+DISP_BWD`，
  与 `judge/core/sim._dependency_table` 相同（`judge/core/sim.py:396-399`）。

### 2.1 fill_gaps 的实现审读（`solver/sched.py:181-322`）

* 空隙表 `gaps[group][engine]` 只在 `dur>0 and comm_gap==0` 时使用；**零时长操作**既不写入、也不从空隙里取位
  （`if gaps is not None and dur and not comm_gap`），完全沿用原语义：零时长不占引擎、`comm_gap` 只对通信生效。
  → 与题面「零时长操作不占引擎；零长度通信计入 Movl（保守口径）」及 `x0_zero_payload` 全零用例一致
  （judge 判 `Time=0` 合法）。
* 依赖先算（`ready = max(前驱 end)`）、窗口先算，之后才找空隙 → 空隙只影响引擎占用，不会绕过依赖。
  `ready = max(ready, begin)` 后 `+dur ≤ stop`，不会与空隙两端已占用区间重叠。
* **必要条件出队规则（关键正确性论证）**：用基准键 `(ready, +inf)` 右二分，跳过「结束 ≤ ready」的空隙；
  而这个 ready 已是全量 ready（依赖+引擎+窗口）。任何**已完成**操作 k 若被安排在 `[ready, ready+dur)` 内，
  必有 `end_k = stop ≤ ready ≤ start_new`，净效果与「按 `end` 的 EDF-like 立即开始」相同；
  未完成操作 k 只可能位于 `start_k ≥ end_k > ready`，其未来释放的空隙会在其出队时被重新考虑。
  → 因此跳过 `stop ≤ ready` 的空隙**不会**导致后续更强的「已就绪」被错过（无 Cafeteria 反例），
  至多与「按引擎序列重排」差一个常数。`pop/insert` 逻辑：切掉已用前缀、切掉剩余后缀，区间保持有序、
  互不相交，`free` 用 `max(...)` 单调不减 → 列表调度的引擎上界 `free` 仍有效。
* 不看 `mode=="early"`：`early` 的惰性修正只看 `ready>heap[0][0]`，空隙填充可能让 `ready` 不变但落点变化；
  行为仍是**构造上合法**（依赖/互斥全部在 `ready/finish` 里保证），仅可能不是 `early` 语义下的最优拓扑。
* 复杂度：跳过前缀是纯扫描（摊还很好），但**找不到合适空隙时**会对每个 `j` 做一次 `max/sum`
  （O(空隙数)）。在 b13（P=64）上实测 fill 让 prio 单次调度 0.117→0.146 s（+25%），b11 early 3.49→4.43 s
  （+27%）；预算紧张时会少吃一两个配置。**不是正确性问题，只是预算问题**。

### 2.2 P=1「权重梯度旁支延后」优先级（`solver/solve.py:267-285`）

`priority[(mb,l,op)] = (op∈{7,9}, mb + (layer if op<4 else 2L−layer), op)`：
先排 `s,disp,gemm,comb`；反向链 `s_bwd(4),comb_bwd(5),gemm_dx(6),disp_bwd(8)` 按「距离层尾的距离」
= `2L−l` 与 mb 混成一个标量 → 深层先反向（与层序一致）；`gemm_dw(7)/s_dw(9)` 排最后。
在 b01/b12（x=0）上这把 `gemm_dw/s_dw` 推到后边，并把空档交给别的 mb 的前向/反向，再靠 fill_gaps 回插。
**语义完全落在依赖表之内**（只是堆键），合法性由 §2.1 的空隙逻辑保证 → judge 200 点全绿（§5）。

---

## 3. 回归与结果（judge 独立判定）

### 3.1 六官方样例（`official-current/log.txt` vs `official-base/log.txt`，两者都跑 `--check`）

| 例 | 当前 | 基线 | judge |
|---|---|---|---|
| ex1 | 560 (lb 560) V=1 P=2 | 560 | ok, Time=560 |
| ex2 | 4880 (lb 3200) V=2 P=2 | 4880 | ok, Time=4880 |
| ex3 | 6072 (lb 4000) V=2 P=2 | 6072 | ok, Time=6072 |
| ex4 | 3200 (lb 3200) V=1 P=2 | 3200 | ok, Time=3200 |
| ex5 | 416 (lb 320) V=2 P=1 | 416 | ok, Time=416 |
| ex6 | 1696 (lb 1120) V=2 P=2 | 1696 | ok, Time=1696 |

`solve_all.py --check` 两版都 `exit 0`：合法 / 10 s 内 / 不劣于题面值 / 退化形态 6/6 全部通过。
`python3 -m judge eval …` 对 `official-current/*.out` 与 `official-base/*.out` 逐例复核，Time 全部一致。
**注意**：`solve_all.py` 打印行的 `lb=` 是**所选 plan** 的 lb（`solve.py:555`），不是 judge 的 lb；
例如 b12 的 `lb=69377771358000000` 是 P=8 那个 plan 的 lb，与 b12 全局最优 P=1 的 `lb=3.06e17` 无关。
比较不同 P 的比值没有意义，报告里一律给**绝对 Time**。

### 3.2 solver 单测

`python3 -m unittest discover -s solver/selftests -t . -q` → `Ran 8 tests … OK`（7.35 s）。
含 `p1_zero_comm`、`x0_zero_payload`（全零时长）、`s0`、`v1_l1`、`r1`、`nmb2` 与 `test_tight_window.py`
（紧内存 + 空隙救援 + 窗口上限）。**单测没有覆盖 fill_gaps**（无 `fill_gaps=True` 用例）→ §5 的 judge fuzz 是补充。

### 3.3 `break → continue`（`solver/solve.py:456-459`）

`enumerate_configs` 先按 `(lb*(nmb+V−1)//nmb, −V, P)` 排序。题面/文档说明的理由成立（V 不同时 lb 不可直接比），
但在这两个用例上：

| 例 | configs[0] | 前 5 个候选 | 后续配置裸 lb 是否可能更小 |
|---|---|---|---|
| b01-loose | P=1, lb=4.896e12 | (P1,4.90e12) (P2,3.34e14) (P4,5.01e14) (P8,5.85e14) (P16,1.25e15) | 否（其余 P 的 lb 全部 ≥ 3.34e14） |
| b12 | P=8, lb=6.94e16 | (P8,6.94e16) (P4,7.80e16) (P16,1.35e17) (P2,1.53e17) (P16,2.03e17) | 否（其余 P 的 lb 全部 ≥ 7.8e16） |

→ `continue` 在两者上都等价于 `break`：**修复逻辑没错，但零收益**（只多一层循环判断）。
它真正的价值是「排序键与剪枝键一致」的正确性护栏；如果想让 P=1 分支在 b12 上重新变成候选，
`continue` 还不够——剪枝键必须和**当前 best 的网格**比较（见 §4.5）。

### 3.4 大用例（真·单例，judge 独立判定，`current/` vs `base/`）

| 例 | 网格 | 当前工作区 Time（judge） | 基线 Time（judge） | 差 | 当前 solve= | 基线 solve= |
|---|---|---|---|---|---|---|
| b01-loose | V=64 P=1 | **5,904,000,000,000** | 5,904,000,000,000 | 0 | 5.15 s | 5.16 s |
| b12-compute-bound | V=64 P=8 | **98,307,789,776,000,000** | 98,307,789,776,000,000 | 0 | 6.12 s | 6.03 s |

* judge：两份都 `ok=true`、`errors=[]`；`lb` 分别是 4,896,000,000,000 / 69,377,771,358,000,000。
* 内存（judge `groups`，limit 2,147,483,648 B）：b01 最大 `Mexp+Movl+Mact=590,413,824`（V0：Movl=Mact=26,738,688），
  其余卡组 `564,199,424`；b12 最大 `94,437,376`。**两版逐组相同**（改动没有触动这两份解）。
* 说明**基线**（HEAD）对 b01/b12 已经是 **5.904e12 / 9.83e16**，README §3 的 6.91e12 是旧数据；
  工作区改动后结果不变。
* 注：`bigcases/battery/out/*.out` 是旧格式（首行 `V P D` 3 个数），**当前 judge 无法判**，不能当基线。§8.2 列出的 `solver/judgedbridge.py` 文件存在（t1 任务描述里的这一点成立）。

---

## 4. 「改进调度」到底在哪、为什么没生效

### 4.1 直接调度实验（绕过 `_try_config`，在 `configs[0]` 的 plan 上直接调 `sched.schedule`）

| 例 | plan | 自定义优先级 + fill=0 | 自定义优先级 + fill=1 | lb | 合法性 | 单次耗时 |
|---|---|---|---|---|---|---|
| b01-loose | P=1 V=64 | 6,912,000,000,000 | **5,904,000,000,000**（−14.6%） | 4,896,000,000,000 | `check_schedule` 0 错，`memory_usage` OK（≤590.4 MB） | 0.106 / 0.127 s |
| b12 | P=8 V=64 | 432,000,000,000,000,000 | **369,000,000,000,000,000**（−14.6%） | 306,000,000,000,000,000 | 0 错，内存 OK | 0.105 / 0.120 s |
| ex5（P=1） | V=2 | 448 | 448 | 320 | judge OK | ≪1 ms |

同一优先级下 fill=1 比 fill=0 好 14.6%（回插旁支）；默认变体下 fill 对 b01/b12 **没有效果**
（6.912e12 两者相同）→ 填隙的价值依赖于「先把引擎腾空」的优先级，二者是一套组合技。

### 4.2 为什么没被采纳（根因，`solver/solve.py:250-285`）

1. `solve_case` 把 `configs[0]`（lb×fill 最小）交给 `_try_config`，新代码**就在这个函数里、是无条件的第一段**；
2. 对 b01/b12 这个 `configs[0]` 恰巧是 **P=1** → 执行扩展候选；
3. 扩展候选**先于**普通列表调度执行，并把 `cost["est"]` 写成自身耗时（0.12 s）；
4. `window_candidates()` 对 nmb=102 返回**全部 102 个窗口**，`_SMALL_VARIANTS` 3 个变体 × 2 模式 = 612 次调度，
   预算 4.5 s（`reserve=0.25+0.065`，`budget=6.5`）→ 走到约第 18–20 个窗口时
   `now + est*1.3 > deadline` 直接 `return best`；
5. 而**真正的 P=1 候选早已在 `_try_config` 开头被短期评估**：对 b12 来说，位置靠前的 P=1 配置（P=4 前面的 `configs[?]`，
  它的 plan 只被**直接调 `sched.schedule`** 测过）才是 `3.69e17` 的来源；它对 b01 的保护期同样在列表调度前就被耗尽。

对应地，`solve_case` 里对该配置的后续 `break` 早已不触发（见 §3.3），所以最终剩下的是
`best = _try_config(...)` 返回的**未消费完预算的列表调度**（b01 6.912e12 / b12 9.83e16）。
这解释了「缓存版 6.91e12 / 9.83e17 看起来比文档好但实际没有变化」的全部矛盾。

### 4.3 复现「预算被打穿」的最小观察

`_try_config` 的预算门 `now + cost["est"]*1.3 > deadline` + `window_candidates` 全枚举：
把 `nmb=102` 的 102 个窗口 × 3 变体 × 2 模式在 4.5 s 内跑不完（单次 prio ≈ 0.11–0.15 s，early 更慢）。
只要 `configs[0]` 是 P=1，扩展候选就排在最前；它自己只花 0.12 s，但把 `est` 抬高后并不会被重试，
真正耗时的是它后面的列表调度。

### 4.4 建议（给人看的修法，供负责人决定；本次不修改代码）

1. **网格级短路**：`if config.P == 1 and case.n_ops > 5000 and any(c.P > 1 for c in configs) and
   best is not None and best.plan.P != 1: skip` —— 让 P=1 扩展只在 (a) 当前 best 也是 P=1（同网格内的拓扑改进）
   或 (b) 没有 P>1 候选 时才使用；
2. 或把扩展候选**放回普通候选之后**（在 `_try_config` 末尾或作为独立阶段），让它与列表调度在同一网格内竞争；
3. 让 `cost["est"]` 只用于「同类型」调度的预算估计，避免扩展候选把 `est` 抬高后挤掉列表调度；
4. `continue` 的剪枝键与排序键需一致（例如 `config.lb >= best.time` 且 `config.P == best.plan.P` 才剪）。

---

## 5. fill_gaps / 延后优先级的独立合法性证据（judge 判定，非求解器自检）

### 5.1 `judge_fill_fuzz.py` → `judge-fill-fuzz.json`

* 用例：`ex5`、`mini` + 8 个随机小用例（L∈1–4，nmb∈1–4，E∈{2,4}，S∈{1,2,4}，N∈{1,2}，
  α×∈{0,1,3,10}，β×∈{0,1,5,10}，含全 0 时长、无边通信等退化，`jfuzz*.in` 已留档）；
* 每例取 ≤3 个不同 P 的配置，跑 `{v0 prio/early × fill 0/1}` 与 `{自定义优先级 prio × fill 0/1}`；
* 结果：**200 行，judge_ok 全部 True，judge_time==solver_time 全部一致**，
  求解器自检 `check_schedule` 也是 0 错。
* 代表数据（ex5）：`V2P1 v0 fill0/1 = 448/448`，`V2P1 custom fill1 = 448`，`V1P2 custom fill1 = 1216`…

### 5.2 `verify.py fill-fuzz` → `fill-fuzz.json`（13 个大用例 + 小用例，只看自检/内存）

* 全部 36 个有效行 `check_schedule=0 错`；`fill` 对 b01/b02/b03/b04/b08/b12 默认变体无变化；
  b12 prio 986.0e14→983.08e14（−0.3%），b13 prio 701.14e14→667.50e14（−4.8%）；
  b11 在 `configs[0]`（P=4,V=4）上内存超限（两种 fill 都一样），说明 `configs[0]` 不一定是可行解——
  这正是 `solve.py` 里「内存超限 → 试 comm_gap → 换窗口/换配置」路径存在的原因。
* 随机小用例（`fuzz*.in`）第一行格式写错（我把头两行顺序弄反），解析失败，已在 §5.1 用 `jfuzz*.in` 重做，
  `fuzz*.in` 仅留档。

### 5.3 零时长 / 边界语义

* `x=0`（P=1）时 `disp/comb/comb_bwd/disp_bwd` 时长 0：fill_gaps 不写入空隙表、不从空隙表取位 →
  与「零时长不占引擎」一致；`comm_gap>0` 时 `fill_gaps` 自动关闭（`not comm_gap`），两机制不会互相踩。
* `ex5`、`mini`、`x0_zero_payload` 等退化用例的 judge 判定与原有语义一致（§3.1、§5.1）。

---

## 6. 给负责人的行动清单

1. **不要把当前工作区状态当「改进」**：b01/b12 最终 Time 与基线相同（5.904e12 / 9.83e16），`continue` 零收益；
   真正有价值的候选（P=1 fill 组合）被接线挡住，未进入最终结果。
2. **修接线而不是修算法**：§4.4 的网格级短路或把扩展候选挪到普通候选之后即可让 b01/b12 候选（5.904e12 / 3.69e17）
   参与竞争；b12 需要 `continue` 的剪枝键与「best 的网格」对齐后才会被尝试。
3. **保留 `continue`** 作为正确性护栏（成本为零），但别把它当成 b12 的改进来源。
4. **给 fill_gaps 补单测**：`solver/selftests` 目前无 `fill_gaps=True`；可直接复用 `judge-fill-fuzz.json`
   的 tag 做回归基线。
5. 若继续做性能优化：先修 §4.4，再跑 b01/b12（每组约 6 s），本轮**没有**跑其它重型基准（避免并行争抢）。

---

## 7. 文件索引

```
runs/val-t1-20261029-2228/
├── README.md                     ← 本报告
├── verify.py                     cmp-deps / fill-fuzz / compare
├── judge_fill_fuzz.py            → judge-fill-fuzz.json（judge 判定 200 点）
├── base-solver/solver/{sched,solve}.py   git show HEAD: 基线（只读）
├── cmp-deps.json                 solver vs judge 依赖/引擎逐项对拍
├── fill-fuzz.json                fill_gaps 自检 + 内存（13 大例 + 小例）
├── judge-fill-fuzz.json          fill × 优先级 × 模式 的 judge 判定
├── official-current/             solve_all --check 日志 + 6 个 .out
├── official-base/                基线同上
├── current/{b01-loose,b12-compute-bound}.{out,stderr}
├── base/   同上（基线）
├── judge/{current,base}-{b01-loose,b12-compute-bound}.json   judge --json 原文
├── jfuzz0-7.in                   随机小用例（§5.1）
└── fuzz0-5.in                    首版随机用例（格式写错，仅留档）
```
