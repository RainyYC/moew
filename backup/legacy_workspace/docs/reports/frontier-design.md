# frontier：事件驱动就绪前沿调度原型（t2 设计说明）

> 状态：**原型，默认关闭**。生产入口 `solve_all.py` 只有显式 `--frontier` 才启用；
> 独立实验入口是 `tools/frontier_solve.py`。正式采用/否决由 t4/t5 的同预算对照决定。
>
> 口径见 `docs/reports/frontier-protocol.md`（冻结 v1）。本文所有数字都来自
> `runs/frontier/experiments/` 下的原始记录，属于**探索期**证据，不作最终结论。

---

## 0. 一句话

把「按优先级/最早时刻反复全量出堆」的列表调度换成**每卡组每引擎的就绪前沿 + 全局完成
事件堆**：操作只在依赖**真实完成**后进入前沿，引擎状态变化只刷新对应引擎的堆项；
零时长操作不占引擎、依赖满足即可执行并形成同刻闭包；内存不再靠固定 `mb−W` 窗口，
而用**生命周期门控**（通信闭区间槽 + 激活双闭区间槽）在派发时保证
`Mexp + U·peak_comm + Uact·peak_act ≤ M`。

公开的实测结论（细节见 §5）：

1. **A 组等价性成立，但不声称训练加速**：`order="lazy_early"` 逐句复刻基线 `early`
   （16 个可测例 Time 逐位相同），`order="priority"` 复刻 `prio`；这两个替身仍会惰性
   重入堆。`order="time"` 是**不同派发规则**，Time 可互有胜负。真实墙钟（无计数包装）上，
   事件内核在 <2k op 约慢 3.6×、2k–20k 约慢 1.8×，20k–100k 中位数约 0.87×、35k 例上
   约 0.18×：只有较大规模才体现工程优势，不能把“等价替身 + 计数开销”拼成 70× 加速。
2. **零时长零等待是语义修正，不是 Time 收益**：样例 ex2/ex5 上零时长操作确实提前
   （最多 32 个时间单位），但 Time 不变；fast12 上 A0（零时长也等引擎）与 A1（立即执行）
   合计 Time 完全相同。
3. **B/C 在 fast12 上没有实质收益**：合计 Time B 比 A0 少 0.0009%，C = B。按协议
   §9「B/C 无收益允许如实否决」处理；保留机制与可复现实验，不默认启用。
4. **A 并不总是与基线 `early` 同 Time**：严格 `(time, rank)` 出队与基线的惰性重排是两种
   派发规则；fast12 上 10/12 例相同，r16 差 +1.0%、r64_v8 差 +11.0%，ex5 反而更好
   （448 < 504）。这部分只称「**不同调度**」，不称加速。

---

## 1. 输入语义（继承，不改）

沿用 `solver/casein.py` / `solver/formula.py` 的整数时长与依赖：

* 节点线性索引 `idx = mb·(L·10) + ℓ·10 + op`，`op` 顺序见 `formula.OP_NAMES`；
* 同层依赖 `formula.DEPS`；层间前向入口 `s/disp(ℓ)` 等 `comb(ℓ−1)`，反向入口
  `s_bwd/comb_bwd(ℓ)` 等 `disp_bwd(ℓ+1)`（`sched._dep_tables`）；
* 引擎：每卡组一套计算 + 一套通信；非零操作占 `[t, t+d)`，**零时长不占**但必须输出；
* `K=2V` 时块 `k` 与 `2V−1−k` 属于同一卡组、共用引擎与内存核算；
* 内存：`used(v) = Mexp(v) + U·peak_comm(v) + Uact·peak_act(v)`，两个峰值**分别**取；
  通信区间 `[start,end]` 闭、同刻先开后关；激活区间 `[comb.end, s_bwd.start]` 双闭。
  本地 judge（`ZERO_LEN_COMM_COUNTS=True`）比官方更严：零时长通信也计入峰值。

本模块只读 `case`/`plan`，不修改它们，也不 import `judge.core`。

---

## 2. 内核设计

### 2.1 数据结构：分引擎就绪队列 + 可派发桶

每个卡组维护三条**可派发前沿**（`_Queue`）：

| 队列 | 内容 | 门控 |
| --- | --- | --- |
| `comp` | 该卡组计算引擎的全部操作 | 无（引擎空闲） |
| `comm` | 该卡组通信引擎中**非 comb** 的操作 | 通信槽 |
| `comb` | 该卡组通信引擎中的 `comb` | 通信槽 + 激活槽 |

每条队列内部：

* `nz_wait`：依赖已满足、但可能还要等引擎的非零操作，堆键 `(dep_ready, rank, idx)`；
* `nz_bucket`：`dep_ready ≤ 引擎空闲` 的操作，堆键 `(rank, idx)`；
* `zero_wait`：零时长操作（不占引擎），堆键 `(dep_ready, rank, idx)`，`zero_free=True`
  时使用。

**晋升只发生一次**：操作从 `nz_wait` 到 `nz_bucket` 至多一次，随后被弹出至多一次；因此
入堆/出堆总数是 `O(n)` 级别，不存在 `sched.py:296–299` 那种「引擎空闲后移 → 同一批旧键
逐个弹出重入堆」的二次行为（微基准见 §5.1）。

### 2.2 全局前沿堆（事件驱动）

再维护一个全局堆，键为
`(start, -引擎剩余工作量, rank, qid, token, idx)`：

* `start` 是该队列**下一次可开工时刻**（引擎空闲 / 依赖完成 / 通信槽可用三者取大）；
* `-work_left` 是「瓶颈引擎供给」启发：同一时刻优先让剩余总工作量更大的引擎开动；
* `rank` 是派发规则（默认见 §2.3），只在同一时刻的候选之间起作用；
* `token` 是队列代次，用于**惰性作废**旧堆项：队列状态一变就 `_touch` 一次（`token+1`
  并推入新前沿），旧项出堆时直接丢弃，不做全局扫描或重建。

只有以下事件会刷新对应队列：新操作依赖完成、该引擎派发了一次操作、同引擎兄弟队列变化、
激活槽/通信槽变化、窗口释放。全局堆大小 `O(n)`；每个操作最多触发常数次前沿刷新，单次调度保守 `O(n log n)`
（堆元素 O(n)，未证明更紧的界）。

### 2.3 派发规则（三档，可切换）

| `order` | 含义 | 用途 |
| --- | --- | --- |
| `"time"` | 严格按 `(start, rank)` 选全局最早可开工操作 | 事件内核默认；B/C |
| `"priority"` | 按 `rank` 出堆，`start = max(依赖完成, 引擎空闲)`，**允许延迟**（引擎先空着等关键操作） | A 组对基线 `prio` 的等价；C 的延迟派发分支 |
| `"lazy_early"` | 逐句复刻基线 `mode="early"` 的惰性重排（`actual > heap[0][0]` 才重排） | 只作等价性/重入堆计数替身，不推荐生产 |

`rank` 有两种：

* 显式基线键：`variant=(fwd_first, mb_desc, l_desc, l_major)` → `variant_priority`；
* 默认「真实依赖剩余路径」：按 `sched._dep_tables` 的同一张依赖图算每个
  `(layer, op)` 到汇点的最长剩余路径（含本操作时长），越接近关键路径越优先，再按
  `mb` / 层 / op 稳定排序（`default_priority`）。

**紧凑内存保护**：`gating=True` 且某卡组 `cap_act ≤ 4` 时，默认优先级自动退化为
`fwd-first/mb-major`。原因是默认剩余路径优先级可能把多个 microbatch 的 `layer-0 comb`
排在前面、占满激活槽后无法再放下一层 `comb`（实测合成用例会死锁）；退化后仍保持
「只可能更好或回退」的语义。显式 `variant`/`priority` 不受影响。

### 2.4 内存生命周期门控（B 组核心）

对每个卡组，`memory_caps` 先做静态预留：

```
avail = M − Mexp
cap_comm ≥ 1,  cap_act ≥ need_act
U·cap_comm + Uact·cap_act ≤ avail
```

* `cap_comm`：默认 2（非零通信在闭区间下最坏 2 块）；若该卡组存在**零时长通信**，
  则把「留够激活槽之后」的剩余内存尽量给通信槽，减少零时长通信被 `+1` 拉开的时间代价。
  可用 `comm_cap`/`act_cap` 或 `policy="comm1|comm2|comm4|actmax"` 覆盖（消融用）。
* `cap_act`：`(avail − U·cap_comm) // Uact`；`need_act` 是能推进的保守下界：卡组内存在
  相邻层 `(ℓ, ℓ+1)` 时需要 2 个槽（`disp(ℓ+1)` 等 `comb(ℓ)`，释放 `ℓ` 又要 `comb(ℓ+1)`），
  否则 1 个。连 `need_act` 都放不下时 `memory_caps` 返回 `None` → 内核返回 `None`，
  调用方回退完整合法 incumbent。
* **通信槽**：闭区间 `[start,end]` 的区间图着色。维护每个槽的 `last_end` 最小堆：
  有 `last_end < start` 的槽就复用，否则槽数未满就新开，否则把 `start` 推到
  `min(last_end)+1`（同刻先开后关 ⇒ 必须错开一个单位）。零时长通信同样占槽（本地口径）。
* **激活槽**：`comb` 派发时申请，`s_bwd` 派发时**登记释放时刻**，等时间**严格越过**
  `s_bwd.start` 才真正释放——因为激活是双闭区间 `[comb.end, s_bwd.start]`，同一时刻的
  新激活与旧激活仍然重叠。实现为每卡组一个 `release_heap`；若某一时刻只剩「等一个单位
  释放」而没有可派发操作，允许时间空转推进（有意义的等待事件），不制造假死锁。

最终仍由 `sched.memory_usage` 复核；内核自己**不**把「瞬时总量」当作两个峰值之和，
也不把 `U·cap_comm + Uact·cap_act` 合并成一个峰值。

### 2.5 死锁、预算与回退

* `deadline` 是 `time.monotonic()` 绝对时刻，内核每 1024 次派发检查一次；超时返回
  `None`（`stats.abort="deadline"`），调用方保留已有完整解。
* 事件前沿为空 → `abort="deadlock"`，返回 `None`；`schedule()` 在「默认优先级 + 门控 +
  未显式指定 variant/priority」时会自动换 `fwd-first/mb-major` 重试一次。
* `search()`/`solve._try_frontier()` 只接受**严格更优且 `memory_usage` 通过**的解；
  新内核异常也被捕获，绝不影响既有 incumbent。
* 大用例自动降级：C 组在 `n_ops > 120000` 时不分支，`> 20000` 时只做一次关键路径延迟
  派发 rollout（`stats.degraded=True` 并写 `notes`）。

### 2.6 确定性

* 事件内核与优先级内核都不使用随机数；同输入 + 同配置 + 同 seed 逐位相同（回归测试）。
* C 组的分支顺序固定（冲突点按时间顺序、候选按堆序），`seed` 只作为接口占位；
  固定迭代上限下确定，`deadline` 截断会写 `notes`。共享机器上不同 deadline 前缀可能
  得到不同候选序列——这是 anytime 行为，报告里如实记录迭代数/截止原因。

---

## 3. 对外接口

```python
# src/solver/frontier.py（新模块；默认不接入生产）
def schedule(case, plan, *, window=None, deadline=None, seed=20261020,
             variant=None, mode="event", lookahead=0,
             zero_free=True, gating=True, policy="auto",
             comm_cap=None, act_cap=None, priority=None,
             trace_limit=0, order="time", stats=None) -> sched.Schedule | None

def search(case, plan, *, strategy="B", windows=None, deadline=None, seed=20261020,
           log=None, stats=None, variant_set=None, policies=None) -> sched.Schedule | None

def memory_caps(case, plan, *, policy="auto", comm_cap=None, act_cap=None) -> list[Caps] | None

def default_priority(case, plan) -> list[int]
def variant_priority(case, plan, variant) -> list[int]
def parse_schedule_config(text, case) -> dict
```

* `schedule` 返回完整 `sched.Schedule`（`start`/`end` 线性索引）或 `None`；**绝不半份**。
* `search` 是给工具/生产接入的「同配置候选扫描」，返回**已过 `memory_usage`** 的最好解。
* `Stats` 只做剖析：`pushes/pops/promotions/repushes/front_refreshes/dispatches/...`，
  `abort`/`degraded`/`notes` 说明截止与降级原因；不参与正式墙钟。

生产开关（默认关闭）：

```bash
# 单例：在既有搜索之后，用 frontier 在最优配置上再试一次（只接受更优且内存合法的解）
PYTHONPATH=src python3 src/solver/solve_all.py cases/ex2.in /tmp/ex2.out \
    --frontier --frontier-mode B

# 独立实验入口：固定基线输出的 V/P/K/ψ/MAP，只比较调度内核
PYTHONPATH=src python3 tools/frontier_solve.py cases/ex1.in /tmp/ex1.frontier.out \
    --baseline-out cases/ex1.out --strategy B --compare-kernel
```

`--frontier-mode` 取 `A/B/C/auto`；默认 `B`。`solve_all.py` 的 stdout/退出码约定不变。

---

## 4. 消融定义（与协议 §9 对齐）

| 组 | 实现 | 声称边界 |
| --- | --- | --- |
| A | `gating=False`，`window`/`variant` 与基线相同；时间前沿 + 优先级出堆两条路径；`zero_free` 两态 | `lazy_early` 与基线 `early` 同 Time ⇒ 只称**工程加速**；`time` 与 `early` 的差异称**不同调度**；零时长零等待单列为**语义修正** |
| B | `window=None`，`gating=True`，生命周期门控 + 多预留策略 | 只称**门控/无窗口**的收益；若收益来自默认优先级，必须单列 |
| C | B 的最优解上做**一步偏离 + 贪心 rollout**（延迟派发分支 + 冲突点「同刻等待」分支），**不是全状态 beam** | 只称**一步前瞻**；无收益不等于所有前瞻无用；分支数与规模上限写进 `stats`，大用例降级 |

禁止把 A 的工程加速、B 的优先级变化、C 的分支收益混成一个总账；每项分开报 Time 与合法率。

---

## 5. 实测结果（探索期，`runs/frontier/experiments/`）

环境：Python 3.14.6，12 核，Linux；固定配置来自基线 `solve_all.py` 在**同预算**下的
输出（`V/P/K/ψ/MAP`），frontier 只换调度内核。

### 5.1 微基准：堆访问计数（**计数带开销，不作真实墙钟**）

ex2 配置（V=2,P=2,K=2），按 `nmb` 放大；基线 `sched.heappush/heappop` 被计数包装器替换，
**21.9 s 里包含包装器开销**，只用于证明“堆操作次数按 ~n² 增长”，**不能**当训练加速证据。
真实墙钟见 §5.2/§5.6（无包装，65k op 基线 early 约 0.66 s，事件内核约 0.65 s）。

| nmb | ops | 基线 early 堆操作 | 事件内核堆操作 | 基线 early 耗时 | 事件内核耗时 |
| --- | --- | --- | --- | --- | --- |
| 64 | 1,280 | 14,838 | 2,330 | 0.017 s | 0.011 s |
| 256 | 5,120 | 224,852 | 9,338 | 0.300 s | 0.040 s |
| 1,024 | 20,480 | 3,546,933 | 37,370 | 4.97 s | 0.15 s |
| 2,048 | 40,960 | 14,155,174 | 74,746 | 21.9 s | 0.30 s |

基线 `early` 的堆操作按约 `n²` 增长；事件内核约 `1.8n`。`lazy_early` 替身在 40,960 op
上复刻出 1,255 万次 repush，证明差异来自基线惰性重排，不是偶然。

### 5.2 A 组：等价与“不同调度”

* 六样例+mini，8 个变体、同窗口 `W=nmb`：
  `order="lazy_early"` vs 基线 `early` **全部逐位相同**；
  `order="priority"` vs 基线 `prio` **全部逐位相同**。
* `order="time"`（严格最早）vs `early`：ex1/ex2/ex3/ex4/ex6/mini 相同；ex5 更好
  （448 < 504）。fast12 上 10/12 相同，r16 差 +1.0%（22,086,710 vs 21,869,220），
  r64_v8 差 +11.0%（5,817,110 vs 5,239,340，但该例基线端到端含退火）。
* 零时长：ex2 上 `s_bwd/s_dw` 等零时长操作比基线 early 提前 24–32 个时间单位；
  但全部可测例上 A0 vs A1 Time 完全相同（见 §5.3）。
* **真实构造墙钟**（`tools/frontier_ablate.py`，无计数包装）：`frontier(time)` /
  `base_early` 的比值在 <2k op 中位 3.56×、2k–20k 中位 1.81×、20k–100k 中位 0.87×；
  35,840 op 的 r256 上是 0.18×（0.25 s vs 1.38 s），65,280 op 的 b13 是 0.76×。
  即“工程加速”只在大规模出现，且随用例形状波动，不能一概而论。

### 5.3 B/C：固定配置（17 个官方合法例合计 Time）

固定配置来自基线 `solve_all.py` 在同预算下的输出；全部候选过官方 grader + 本地 judge。
样本 7 例用**同预算新鲜基线**（`t2-baseline-samples7`），fast12 用 `t2-baseline-fast12`。

| 方案 | 合计 Time（17 例） | 相对基线 |
| --- | --- | --- |
| 基线端到端（solve_all） | 228,972,838 | — |
| A0（零时长也等引擎） | 228,618,042（12 例合计口径不完全可比） | — |
| B（无窗口 + 生命周期门控） | 228,633,913 | −0.148% |
| C（B + 有界前瞻） | 228,633,049 | −0.148% |

逐例（官方 grader Time，括号为相对基线）：

* B/C **更好**：r24 −1.0%、r32 −2.7%、x05 −0.7%、x13 −0.2%、x03 −0.08%、r256 −0.02%；
* B/C **更差**：ex2 +7.4%、ex3 +7.6%、ex5 +7.7%、ex6 +7.8%、r64_v8 +11.0%、r16 +1.0%；
* 其余持平（ex1/ex4/mini/r64_v2/r128/x18/x19）。

**结论：B/C 作为“替换整个搜索”没有稳定收益，且会在若干样例上退化**；作为“只接受更优解
的额外候选”才有意义（§5.6）。C 与 B 逐例相同（rollout 没找到更好的解），成本 0.1–1.2 s。
B 相对 A0 只改善 x03 一例（−2,105，0.0009%）：**B 的收益在本批用例上几乎全部来自
默认剩余路径优先级与候选扫描，不是生命周期门控本身**——这与 §5.5 的机制证据并不矛盾：
门控只在“整数窗口粒度卡住”的形状上才生效，官方 fast12 恰好没有这种形状。

> 噪声提示：t3 实测 fast12 同配置重复有 ~0.36% 的截断波动（`docs/reports/frontier-baseline.md`）。
> 本条中 <0.5% 的差异（r64_v2、r256、x03、x13）不能单独作为收益证据，必须重复后看。

### 5.4 K=2V 定向对照

fast12 的 12 例里有 **4 例本身就是 `K=2V`**（r16_p4_trap `V=4,K=8`；r24_p4_block
`V=6,K=12`；x03_lr_trap_p3 `V=9,K=18`；x13_lr_twochunk_p8 `V=6,K=12`），所以 §5.3 的
B/C 数字已经覆盖镜像配对（两块共用引擎/内存）。另外用 `solve.k2v_candidates` 的
另一组切点做了定向对照（`runs/frontier/experiments/t2_k2v.json`）：

| 用例 | ops | K | 基线列表调度（同配置最好） | B | C |
| --- | --- | --- | --- | --- | --- |
| r16_p4_trap | 3,840 | 8 | 21,869,220 | 22,086,710（+1.0%） | 同 B |
| r24_p4_block | 10,240 | 12 | 53,879,530 | 50,791,330（−5.7%） | 同 B |
| x03_lr_trap_p3 | 5,400 | 18 | 12,539,316 | 12,410,687（−1.0%） | 同 B |
| x13_lr_twochunk_p8 | 3,840 | 12 | 14,937,492 | 14,913,208（−0.2%） | 同 B |

结论与 §5.3 一致：B/C 在这些 K=2V 配置上没有稳定、可归因于门控的收益；表内差异主要
来自默认剩余路径优先级与候选集，不能算作「生命周期门控」的收益。所有输出都过了
`check_schedule` 与本地 `memory_usage`（含零时长通信保守口径）。

### 5.5 合成紧内存：门控机制本身的对照

官方 fast12 上 B 的门控没有绑定（A0/B 同 Time），所以另做**受控合成用例**：
`V=1,P=2,L=2,nmb=8`，`Mexp=20`、`M=25`、`U=1,Uact=1`，于是
`cap_comm=2, cap_act=3`（相邻两层，`need_act=2`）。

| 方案 | Time | 峰值 `(comm, act)` | 合法 |
| --- | --- | --- | --- |
| 基线列表调度（整数窗口扫描 W=1..8 × 变体 × 模式，最好） | 298 | (2, 2) | 是 |
| B：生命周期门控（`policy=auto`，W=2.0 等价容量） | **288** (−3.4%) | (2, 3) | 是 |
| B：`comm1`（让出通信槽换激活槽） | 288 | (1, 4) | 是 |

解释：基线只能用整数 `W` 限制「同时活跃的 microbatch 数」，`W=1` 只允许 2 个激活；
生命周期门控直接按「激活槽个数」约束，能用满 `cap_act=3`，所以同一内存上限下多挤进
一个激活、Time 少 10。这是**机制层面**的证据（合成用例，不计入官方成绩）。
本次探索里**找到的** B 收益来源就是这种“内存上限卡在整数窗口粒度之间”的形状；
这是一个观察，不是“B 只在此时有效”的排他性定理——官方 fast12 的 20 个用例上
`gating_binding=0`，因此那些差异不能归因于门控。

### 5.6 生产接入（`--frontier`，默认关闭）：只接受更优解

`solve_case(frontier=True)` 从同一份 B 里**预留** `min(0.9s, 12%·B)` 给新内核，在基线
搜索得到的最优配置上扫 5 个拓扑（`VARIANTS[0,2,4,5,7]`）× `policy ∈ {auto,comm1}`
（`n_ops>20000` 时只扫 `VARIANTS[0,4]` × auto），只接受严格更优且过 `memory_usage` 的解。

单次实测（显式 B=7.6，非正式 ABBA）：

| 用例 | 基线端到端 | `--frontier` | 变化 |
| --- | --- | --- | --- |
| r24_p4_block | 51,491,190 | 50,791,330 | −1.36% |
| r32_p8_ramp | 17,096,182 | 16,637,188 | −2.69% |
| x05_lr_tight_p6 | 16,417,874 | 16,309,154 | −0.66% |
| x13_lr_twochunk_p8 | 14,937,492 | 14,913,208 | −0.16% |
| r64_v2_c2 | 2,600,248 | 2,600,232 | −0.0006% |
| r256_v4_c4 | 64,625,020 | 64,612,898 | −0.02% |
| r16 / r64_v8 / r128 / x18 / x19 | 同左 | 同左 | 0 |

t4 同预算 ABBA（冻结基线 vs 显式候选入口，每臂 2 趟）见
`docs/reports/frontier-experiments.md` §5；结论：fast12 6 好/1 差/5 平（−0.186%），
K=2V 6 例 3/0/3（−0.98%），samples 全平，battery5 全平（无命中）。唯一的“差”r24 是
墙钟截断离群：候选 5 次重复中 4 次优于 fullB（中位 50,970,670 vs 51,491,190）；
no-op 控制（只预留不运行）在 r24×3、r32×1 上与 fullB 完全相同，说明预留本身无系统代价。
**候选仍默认关闭，交 t5 正式 50/13/留出集决定。**

在 tested 19 例上**未观察到回归**（因为只接受更优解；但预留预算会让基线搜索略变差，
本批里被 frontier 候选补回并超过基线）。`>0.5%` 的 r24/r32/x05 收益需按 t3 的 ABBA
与重复协议复核；本轮另有 3 次重复记录在 `runs/frontier/experiments/t2-integration/`。
**该开关默认关闭，是否默认启用由 t4/t5 决定。**

> 预算纪律：frontier 与基线搜索共享同一份 `B`，没有额外加预算；预留会挤掉一部分原搜索
> 预算（r24 上基线搜索从 51.49M 退到 51.60M，frontier 再把它压到 50.79M）。这一点必须
> 在正式报告里单列，不能只报 `min(旧, 新)`。

---

## 6. 已知限制与风险

1. **`order="priority"` 不能与门控同用**：时间非单调，激活/通信槽的“未释放计数=存活数”
   推理不成立；该路径只用于 A 组等价与 C 的延迟派发分支，结果必须过
   `sched.memory_usage` 才接受。
2. **`time` 与基线 `early` 不是同一派发规则**：基线只在 `actual > heap[0][0]` 时重排，
   等时刻不保证严格 `(earliest, rank)` 全序；两边的 Time 可以互有胜负，不能用“等价加速”
   描述。`lazy_early` 才是逐句等价物。
3. **紧内存下默认优先级可能死锁**：已有 `cap_act ≤ 4` 的自动退化与失败重试；但任意
   variant 仍可能因错误的 comb 顺序返回 `None`（允许），`search` 会兜底。
4. **零时长通信的本地/官方口径差异**：内核按本地更严口径（零时长也占通信槽）门控；
   官方 grader 忽略零时长通信。紧内存用例可能出现“官方合法、本地超内存”，按协议单列，
   不利用。
5. **`cases/mini.in` 是本地回归**：`nmb=1` 被官方输入解析拒绝，不能作为官方合法样例；
   官方判分只用 `data/official/Problem/cases` 与六样例。
6. **C 的 anytime 性**：固定迭代上限下确定；不同 deadline 前缀会截断不同分支，报告中
   记录 `stats.notes` 的截断原因，不强行限制合法搜索时间。
7. **生产接入默认关闭**：`solve_case(frontier=False)`；即使打开也只接受严格更优且内存
   合法的解，不会让结果变差。

---

## 7. 复现命令

```bash
cd /home/rainy/hackathon/work-frontier-sgs

# 回归（含 frontier 16 项）
PYTHONPATH=src python3 -m unittest discover -s src/solver/selftests -t src -q

# 固定基线配置 + 对照基线列表调度
PYTHONPATH=src python3 tools/frontier_solve.py \
    data/official/Problem/cases/r16_p4_trap.txt /tmp/r16.B.out \
    --baseline-out runs/frontier/experiments/t2-baseline-fast12/r16_p4_trap.out \
    --strategy B --budget 5 --compare-kernel --json

# 双判分
cd data/official/Problem && python3 grader.py <case.txt> /tmp/r16.B.out
cd /home/rainy/hackathon/work-frontier-sgs && \
  PYTHONPATH=src python3 -m judge eval <case.in> /tmp/r16.B.out --json

# 微基准
PYTHONPATH=src python3 tools/frontier_solve.py cases/ex2.in --microbench \
    --baseline-out cases/ex2.out --nmb 64 256 1024 2048

# 生产开关（默认关闭）
PYTHONPATH=src python3 src/solver/solve_all.py cases/ex2.in /tmp/ex2.out \
    --frontier --frontier-mode C
```

原始记录：`runs/frontier/experiments/{t2-baseline-fast12,t2-tool,t2_attrib.json,
t2_compare.json,t2_k2v.json,`与各 `*.log`；基线/候选产物与命令都在对应目录。

---

## 8. 合规自检（对应协议 §12）

- 只在 `work-frontier-sgs` 写入；`data/official/**`、`src/judge/**`、`Makefile` 未改。
- 新路线默认关闭；正式对照必须显式 `--frontier`，且只接受更优解。
- 没有装新依赖、没有起服务、没有改断言；`make test` / `judge.core.acceptance` 结果记录在
  §9（提交前）。
- 没有用更大预算或预存结果充当收益；B/C 无收益已如实记录。

---

## 9. 本轮验证记录

| 命令 | 结果 |
| --- | --- |
| `make test` | 通过：judge 66 + solver 34（含 frontier 16 项；1 项既有 skip） |
| `PYTHONPATH=src python3 -m judge.core.acceptance` | 通过：7/7 例（ex1–ex6 + mini，Time 与期望一致） |
| samples7 + fast12 候选双判分 | 17/17 官方合法例双判通过，official Time == 本地 judge Time；mini 官方输入解析拒绝（nmb=1），本地 164 合法 |
| K=2V 定向对照 | 4 例全部双判合法（§5.4） |
| 合成紧内存/死锁回归 | `test_frontier.py` 覆盖；`cap_act=2` 可完成、不可行内存返回 None |

原始日志：`runs/frontier/experiments/{t2-make-test-final.log,t2-acceptance.log,
t2_grade2.log,t2-candidates2/summary.json,t2_k2v.json,t2-integration/}`。
