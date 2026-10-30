# 判题核心 `judge/core` 复核报告（两轮）

- 复核者：verifier（独立复核，未参与 t1/t7 实现；**只读**，未修改 `judge/core` 任何一行）
- 被复核对象：`judge/core/{parse,model,sim,memory,evaluate,acceptance}.py`
- 权威依据：`problem-fixed.md`（题面）；接口语义以 `CONTRACT.md` v2 为准；`solution-report.md` 只作方法参考，数值不可信
- **当前结论（第二轮 · t8，复验 t7 修复）：verdict = pass**
  - 第一轮（t6）唯一 medium finding **F1 已修并被我独立复验**：同一 `(t,mb,ℓ,op)` 多重集的 4 种等价写法（拆行 / 同 `t` 行倒序 / 行内倒序 / 两者叠加）在全部 7 个用例上**结果字典逐字节相同**；真违规（依赖/引擎/格式/重复/缺失/闭区间内存）仍全部被拒；
  - 7 个验收值、`lb`、`groups`、`engines` 与 **t6 复核基线逐项相同**，独立复算（不 import `judge`，算法不同）仍逐项一致；`acceptance` 7/7；`unittest` **54** 个全绿；64 万条 `evaluate` 1.60 s；
  - N1 裁定已落成 `ZERO_LEN_COMM_COUNTS`（默认 `True`）：默认路径不变、只影响 `Movl`、零长度激活仍计入 `Mact`（题面 §4.6 要求）；
  - 3 条**观察**（不构成 finding、不需改代码）：CONTRACT §11 的 `ZERO_LEN_COUNTS` TODO 措辞有题面风险、`test_negative.py` 过时注释、`GOLDEN_SHA256` 的自证性质。详见 §10。
- 第一轮记录（t6，verdict = needs_revision）保留在 §1–§9 作为审计轨迹；第二轮复验见 §10。

---

## 0. 复核方法（为什么不是"只跑测试"）

1. **逐条读题面 §4.1–§4.7 与 §3.1/§3.2**，对照 `judge/core` 的每个公式与每条约束，写「规则 → 代码 → 结论」表（§1）。
2. **自己写一遍最小模拟**（附录 A，`verify7.py`），**不 import `judge`**，且故意用与 t1 不同的算法：
   - 依赖：先登记全部 `(start,end)`，再对每个 `(op, dep)` 全量检查（t1 是逐行增量检查）；
   - 引擎互斥：按 `(卡组, 引擎)` 收集区间后排序查重叠（t1 是游标）；
   - 内存峰值：端点事件全量扫描（t1 是结束时刻小顶堆流式）。
   7 个用例的 `time / lb / groups(Mexp,Movl,Mact)` 与 t1 **逐项相等**（§2）。
3. **题面散文中给出的手算值**（§7.1–§7.6 与 §3.2）当作第二把尺子，逐项对照实现（§5 表）。
4. **20 条变异用例**：从题面推出"应合法/应非法"，再看 t1 判什么（§6）。这一步专门用来找"两边一致但都违背题面"：
   我与 t1 对每条规则的**读法**分别被题面散文手算值、官方样例和变异用例钉住，而不是互相比对。
5. 三个最易错语义做**反事实实验**（§3）：换掉规则后结果必须变坏/变非法，才能证明 t1 用的就是题面那条。
6. 跑 t1 自带测试与验收（只作背景，不作结论）：`python3 -m unittest discover -s judge/tests -t . -q` → **Ran 42 tests, OK**；`python3 -m judge.core.acceptance` → **7/7 通过，exit 0**。

复跑命令见 §7；独立复算脚本全文见附录 A。

---

## 1. 规则 → 代码 → 结论

行号均指当前工作区文件。标记：✅ 与题面一致；⚠️ 有偏差（见 §4）；ℹ️ 题面未规定/由契约补充。

### 1.1 §4.1 十种操作、时长与取整

| 题面规则 | 代码位置 | 结论 |
|---|---|---|
| 十种操作名，顺序与引擎归属（`s,gemm,s_bwd,gemm_dx,gemm_dw,s_dw` 计算；`disp,comb,comb_bwd,disp_bwd` 通信） | `model.py:65-85`（`OP_NAMES`/`ENGINE`/`COMP_OPS`/`COMM_OPS`） | ✅ 逐项一致 |
| `s = T_l·Fs`、`gemm = m_l·Fin`、`disp = comb = x_l` | `model.py:192-201` | ✅ |
| `s_bwd = α·s`、`comb_bwd = disp_bwd = α·x`、`gemm_dx = α·m·Fin` | `model.py:196-206`，`ceil_div(α×·v, 1e6)` | ✅ |
| `gemm_dw = αβ·m·Fin`、`s_dw = αβ·s` | `model.py:206-208`，`ceil_div(α×·β×·v, 1e12)` | ✅ |
| **每个表达式只向上取整一次**（不是"先取整 β 再取整 α"） | `model.py:61-62`（`MICRO/MICRO2`）+ `103-107`（纯整数 `ceil_div`）+ `196-208` | ✅ 单次整数 ceil，全程无 float/真除法。注：7 个官方值不区分单/双取整，`judge/tests/test_api.py:143` 单独锁了这条 |
| α=α×/10⁶、β=β×/10⁶，全整数 | 同上 | ✅ |

### 1.2 §4.2 依赖与资源

| 题面规则 | 代码位置 | 结论 |
|---|---|---|
| 层内前向 `s→disp→gemm→comb` | `model.py:89-100`（`DEPS`）+ `sim.py:386-398`（`_dependency_table`）+ `sim.py:457-487` | ✅ |
| 反向路径 `s_bwd→comb_bwd→gemm_dx→disp_bwd` | 同上 | ✅ |
| `gemm_dw`/`s_dw` **只**依赖 `comb_bwd`（可推迟） | `model.py:97-99` | ✅ |
| `s_bwd` 不早于**同层 comb 结束** | `model.py:94`（`DEPS[4]=(comb,)`） | ✅ |
| 管线前向：`s(ℓ) ≥ comb(ℓ−1)`，同一 microbatch | `sim.py:391-393` | ✅ |
| 管线反向：`s_bwd(ℓ) ≥ disp_bwd(ℓ+1)`，锚点是 `disp_bwd` **不是** `s_dw` | `sim.py:394-395` | ✅（反事实见 §3.3） |
| 两条管线依赖建在**层**上而非块上（共卡的两层同样受约束） | 依赖表只按层号建，卡组只影响引擎/内存 | ✅ |
| 资源互斥：每卡组各一套计算/通信引擎；`K=2V` 两块共用 | `sim.py:488-515` + `model.py:229-251`（`block_group`/`group_of_layer`） | ✅（合成用例验证见 §6 `k2v_engine_share`） |
| 时长 0 的操作**不占用**引擎 | `sim.py:490-492` | ✅（证据见 §3.1） |
| 因果性：声明的 `t` 不早于依赖完成时刻 | `sim.py:457-487` | ⚠️ **F1**：同一 `t` 写在多行且依赖在后面的行时，会被误判（详见 §4） |

### 1.3 §4.3 负载、放置与计算时间

| 题面规则 | 代码位置 | 结论 |
|---|---|---|
| `L_{ℓ,r}=Σ_{e:σ_{ℓ,e}=r} a_{ℓ,e}`，`m_ℓ=max_r L_{ℓ,r}` | `model.py:177-187` | ✅ |
| 无负载向量时把 `T_ℓ` 尽量均分给 `E` 个专家，前 `T_ℓ%E` 个各多 1 | `model.py:115-126` | ✅（手算 `T=10,E=4 → (3,3,2,2)`，见 §5） |
| 偏斜只抬计算不改变通信：`m` 取最慢 rank，`X` 只依赖 `T` | `model.py:177-187` 与 `157-161` 分离 | ✅（ex2 `m₁=6→gemm 24`、ex4 `m₀=5→gemm 20`） |
| 题面 §4.3 括注"负载均衡时 `m=⌈T/P⌉`" | 实现取定义式（rank 求和取最大），不取该简写 | ✅ 实现更严格；`T%E≠0` 时该简写本就不成立（`m` 依 MAP 为 6 或 5），见 §5 |

### 1.4 §4.4 通信时间

| 题面规则 | 代码位置 | 结论 |
|---|---|---|
| `H = ⌊d·b/k⌋` | `parse.py:88-91`（`Case.H`） | ✅ |
| `X_ℓ = ⌈T_ℓ·H·(P−1)/P⌉` | `model.py:157-161` | ✅ |
| 嵌入 `q=v·(P·D)+d·P+p`（p 最快变），按物理卡定 `pin`、`pout=P−1−pin` | `model.py:145-151` | ✅（ex3 `P=4→(1,2)`；`D>1` 也按 (v,d) 逐组复核，并要求所有组一致） |
| `x_ℓ = max(⌈pin·X/Bin⌉, ⌈pout·X/Bout⌉)·Fio`（先取 max 再乘，流量按实际对端数分项） | `model.py:164-174` | ✅ |
| `P=1`：`X=0、pin=pout=0、x=0`，通信操作以 0 时长出现 | `model.py:141-142,159-160,170-171` | ✅（ex5） |

### 1.5 §4.5 / §4.6 / §4.7

| 题面规则 | 代码位置 | 结论 |
|---|---|---|
| `Time = max(t + 时长)`，前向模拟，不做优化 | `sim.py:692-693` | ✅ |
| `Mexp = Σ_{ℓ∈卡组}((E/P)·Z + Zs)` | `memory.py:106,110` | ✅ |
| `Movl = U × 通信并发峰值`，**闭区间**（恰好在下次开始时结束算两块） | `memory.py:65-87`（流式）与 `28-62`（`closed_peak`） | ✅（证据见 §3.2） |
| `Mact = Uact × [comb 结束, s_bwd 开始]` 内激活峰值，**闭区间** | `sim.py:548-561`（区间端点）+ `memory.py:112` | ✅（反事实见 §3.2） |
| `Mexp+Movl+Mact ≤ M`，否则非法 | `sim.py:662-688` | ✅（报错带 `group/mexp/movl/mact/limit` 与峰值时刻，便于定位） |
| §4.7.1 `V·P·D=R`、`V,P,D≥1`、`P∣E`、`P∣S` 或 `S∣P`（另拒 `V>L`） | `sim.py:94-129` | ✅ |
| §4.7.2 `K∈{V,2V}`，恰好 `K−1` 个切点，严格递增且覆盖 `0..L` | `sim.py:132-183` | ✅（每点须落在 `(0,L)`；隐含端点 0、L） |
| §4.7.3 `σ_{ℓ,e}∈[0,P)`，每取值恰好 `E/P` 次，共 `L` 行 | `sim.py:186-243` | ✅ |
| §4.7.4 只引用十种操作名；`mb∈[0,nmb)`、`ℓ∈[0,L)` | `sim.py:251-316` | ✅ |
| §3.2 每 `(mb,ℓ,op)` 恰好出现一次（十个操作 × 每层 × 每 mb） | `sim.py:319-356` | ✅ |
| §3.2 `t` 非降 | `sim.py:263-273` | ✅ |
| §3.2 同一行内不得有两个占用同引擎的操作 | 由 §4.2 引擎互斥覆盖（零时长不占） | ✅ |
| §4.7.5 `nmb` 为偶数（题面注明"输入保证"） | 未校验 | ℹ️ 可接受：这是输入约束，不是输出合法性约束 |
| §3.1 块 k 含 `[ψ_k,ψ_{k+1})`；`K=2V` 时 `g(k)=2V−1−k` | `model.py:217-251`（`layer_block`/`block_group`/`group_layers`/`group_of_layer`） | ✅（合成用例：V=1→`[0,0]`，V=2→`[0,1,1,0]`，见 §5） |
| CONTRACT §1 `grid/K/psi/errors` 回显 | `sim.py:629-631` | ✅ |
| CONTRACT §1 `lb = max_v nmb·max(ΣC_v,ΣWc_v)` | `model.py:259-273` | ✅（注意 `ΣC` 是**单 microbatch** 的量和，`engines.comp` 才是 `nmb×ΣC`；ex1 `lb=560`、`comp=240` 两者自洽） |
| CONTRACT §1 `engines{comp,comm,comm_first,comm_last}` | `sim.py:564-594` | ✅（ex1 = `240/560/16/576`，与 CONTRACT §1 示例逐字段相同） |
| 纯函数（不写文件、不读时钟、不联网） | `judge/tests/test_purity.py` 静态+动态检查；我重复调用 `evaluate` 结果字节级一致 | ✅ |

---

## 2. 7 个验收值：t1 vs 独立复算

`judge` 侧来自 `python3 -m judge.core.acceptance` 与 `evaluate()`；"独立"侧来自附录 A（不 import judge）。

| 用例 | 题面/契约 Time | judge Time | 独立 Time | judge lb | 独立 lb | judge `groups`(Mexp,Movl,Mact) | 独立 `groups` | 一致 |
|---|---|---|---|---|---|---|---|---|
| ex1 | 592 | 592 | **592** | 560 | 560 | (20, 2, 1) | (20, 2, 1) | ✅ |
| ex2 | 4880 | 4880 | **4880** | 3200 | 3200 | (40,2,2), (40,2,1) | 同 | ✅ |
| ex3 | 4000 | 4000 | **4000** | 4000 | 4000 | (40, 2, 1) | 同 | ✅ |
| ex4 | 3200 | 3200 | **3200** | 3200 | 3200 | (40, 2, 1) | 同 | ✅ |
| ex5 | 416 | 416 | **416** | 320 | 320 | (40,1,2), (40,1,1) | 同 | ✅ |
| ex6 | 1744 | 1744 | **1744** | 1120 | 1120 | (20,2,2), (20,2,1) | 同 | ✅ |
| mini | 180（**合成**，非题面官方值） | 180 | **180** | 140 | 140 | (20, 3, 1) | 同 | ✅ |

补充逐项一致（我逐字段比对，不只比 `time`）：

| 用例 | `engines`(comp,comm,comm_first,comm_last) | `pin/pout` | 逐层 10 个时长 | MAP/`m_l` |
|---|---|---|---|---|
| ex1 | (240, 560, 16, 576) | (1,0) | 一致 | 一致 |
| ex2 | (96,3200,0,4880), (144,3200,816,4064) | (1,0) | 一致 | 一致 |
| ex3 | (72, 4000, 0, 4000) | (1,0) | 一致 | 一致 |
| ex4 | (120, 3200, 0, 3200) | (1,0) | 一致 | 一致 |
| ex5 | (320, 0, 16, 392), (320, 0, 80, 320) | (0,0) | 一致 | 一致 |
| ex6 | (120,1120,16,1744), (120,1120,316,1444) | (1,0) | 一致 | 一致 |
| mini | (40, 140, 16, 180) | (1,0) | 一致 | 一致 |

> `ex1` 的 `movl = 2`（闭区间口径，用户已裁定）与 CONTRACT §1 示例一致；t1 **没有**把 `movl==1` 硬编码，值来自 8 次 AllToAll 首尾相接（`model.py` 只给公式，`memory.py` 只算峰值）。
> `mini` 的 `movl = 3`（`comb` 在 180 结束 + `comb_bwd`/`disp_bwd` 在 180 开始，闭区间三者同时"在途"），仍是 `20+3+1=24 ≤ 39`。

---

## 3. 三个最易错语义的反事实验证

### 3.1 零时长操作不占引擎

- 实现：`sim.py:488-492`，`if duration <= 0: continue`（不计引擎占用，也不推进 `free`）。
- 证据（不需要变异，官方样例本身就互相矛盾）：
  - `ex2` 的 `Fs=0` ⇒ 所有 `s` 时长为 0；`ex2.out` 第 0 行 `0:0:s 1:0:disp 1:0:s` 把两个 `s` 放在同一时刻的同一（计算）引擎；第 3240 行 `1:0:gemm_dx`（24 时长）与 `1:0:s_dw`（0 时长）同刻同引擎。若"零时长占引擎"，`ex2` 必然非法 → 题面 4880 无法复现。
  - 实测同刻同引擎且含零时长操作的对数：`ex2=5`、`ex3=3`、`ex4=1`、`mini=9`（`mini` 一行里 4 个零时长计算操作）。这 4 个用例的官方值都精确复现 ⇒ 规则成立。
  - `ex5`（`x=0`，全部通信零时长）与 `ex1` 不依赖这条，故为 0 对，属正常。

### 3.2 `Movl` / `Mact` 闭区间

- `Movl`：`memory.py:49` 弹出条件是 `heap[0] < start`（**不是** `<=`），所以 `end == 下一段 start` 的两块同时计入。
  - `ex1`：8 次 AllToAll 首尾相接 → `Movl = 2U = 2`（judge `groups=(20,2,1)`），与 CONTRACT §1 示例一致。
  - 判别性变异（半开口径会给出相反结论）：
    - `ex1` 把 `U` 改成 18：闭区间 `20+36+1=57 > 39` → 非法；半开口径恰为 `20+18+1=39` → 合法。**judge 判非法** ✅（闭区间）。
    - `ex6` 把 `M` 改成 23（隔离 `Movl`：`Mact` 在两种口径下都是 2）：闭区间 `20+2+2=24 > 23` → 非法；半开口径 `23` → 合法。**judge 判非法** ✅。
  - `Mact`：区间端点取 `end(comb)` 与 `start(s_bwd)`（`sim.py:558-560`），`closed_peak` 同闭区间语义。
    - `ex1` 把 `M` 改成 22：闭区间 `20+2+1=23 > 22` → 非法。**judge 判非法** ✅。
    - 隔离 `Mact` 的合成用例（`L=1,nmb=2,P=2`，让 mb1 的 `comb` 恰好在 mb0 的 `s_bwd` 开始时结束；同时把零时长通信操作挪开，使 `Movl` 在两种口径下都是 1）：`M=23` → 合法、`Time=422`；`M=22` → 非法。**judge 与独立复算一致** ✅。

### 3.3 `s_bwd` 的跨层锚点是 `disp_bwd`，不是 `s_dw`

- 实现：`sim.py:394-395`，`deps.append((layer+1, _OI_DISP_BWD))`；`s_dw` 只作为 `gemm_dw`/`s_dw` 自身的依赖，不参与跨层。
- 反事实：把独立复算的锚点换成 `s_dw`，重跑官方样例：
  - `ex5` → **非法**：`0:0:s_bwd@t=192 < 0:1:s_dw end=328`、`1:0:s_bwd@t=320 < 1:1:s_dw end=336`。
  - 也就是说：t1 能判 `ex5` 合法并给出 **416**，只可能因为它用的是 `disp_bwd`（用 `s_dw` 会直接拒掉题面自己的合法输出）。✅
  - `ex6` 的这份调度在"仅换锚点"下仍然合法（`0:0:s_bwd@1160 > 0:1:s_dw end=888`），所以 `ex6` 不判别锚点；它判别的是"权重梯度可推迟"与"两块共用引擎"。
- 题面 §7.5/§7.6 说链式规则（`disp_bwd` 排在权重梯度之后、锚点取 `s_dw`）会得到 480 / 1784：这与"给定调度在链式规则下不合法"一致，不构成矛盾。

### 3.4 专门找"两边一致但都违背题面"

逐条检查了最容易"双方一起读错"的地方，结论是没有系统性共错——每一处都被题面散文的手算值独立钉住（§5）：

| 疑点 | 题面手算值 | t1 | 独立复算 |
|---|---|---|---|
| 取整顺序（α、αβ 只取整一次） | —（官方值不判别） | 单次 ceil | 单次 ceil |
| `X` 的 ceil 方向、`(P−1)/P` | ex1 64 / ex2 32 / ex3 48、72 / ex4 40 / ex6 64 | ✅ | ✅ |
| `x` 先 max 后乘 `Fio` | ex1 70 / ex2 400 / ex3 500、14400 / ex4 400 / ex6 140 | ✅ | ✅ |
| `m` 取最慢 rank（不是 `⌈T/P⌉` 简写） | ex2 `m₁=6→gemm 24` / ex4 `m₀=5→gemm 20` | ✅ | ✅ |
| `pin/pout` 由物理卡嵌入算出 | ex3 `P=2→(1,0)`、`P=4→(1,2)` | ✅ | ✅ |
| 反向各步时长 | ex5 `(16,0,48,0,16,0,48,24,0,8)`；ex6 `(16,140,4,140,16,140,4,4,140,16)` | ✅ | ✅ |
| 均分口径（前 `T%E` 个多 1） | `T=10,E=4 → (3,3,2,2)` | ✅ | ✅ |
| 块→卡组镜像 | V=2,K=4 → `[0,1,1,0]`（g(k)=2V−1−k） | ✅ | ✅ |

---

## 4. Findings

### F1 · medium · `judge/core/sim.py:450-460`（因果性检查依赖"书写行序"）

**问题**
`_simulate` 是逐行处理的：先在当前行登记本行所有操作的 `(start,end)`（450-455），再对本行每个操作查依赖（457-487）。
因此，当两份**同一时刻 `t`** 的操作被写在**两行**里、且依赖方在前一行时，被依赖方尚未登记（`end = -1`），会被报成
`dependency / 因果性` 错误——尽管按题面它完全合法（依赖的时长为 0，`t == dep_end`）。

**题面依据**
- §3.2 只要求"`t` 必须非降"，没有禁止同一 `t` 出现多行，也没有赋予行序任何语义；
- §4.2 第 4 条只说"条目声明的 `t` 不得早于其依赖的完成时刻"——这只比较 `t` 与依赖的**完成时刻**，与写在哪个行无关。

**可复现证据**
把题面官方合法输出 `cases/ex2.out` 的每一行拆成"一行一个操作"（`t` 不变，因此 40 个 `(t, mb, ℓ, op)` 三元组**完全不变**）：

```bash
cd /home/rainy/hackathon && python3 - <<'PY'
import sys; sys.path.insert(0,'.')
from judge.core.evaluate import parse_case_text, evaluate
inp=open('cases/ex2.in').read(); out=open('cases/ex2.out').read()
res=[]; ins=False
for ln in out.splitlines():
    tk=ln.split()
    if not ins:
        res.append(ln)
        if tk==['SCHEDULE']: ins=True
    else:
        for op in tk[1:]: res.append(tk[0]+' '+op)   # 同一 t，一 op 一行
split="\n".join(res)+"\n"
r=evaluate(parse_case_text(inp,'ex2'), split)
print('judge:', r['ok'], r['time'], [(e['category'], e['at']) for e in r['errors']])
PY
```

观察到的结果：

```
judge: False None [('dependency', '1:0:disp'), ('dependency', '1:1:disp'),
                   ('dependency', '1:1:comb_bwd'), ('dependency', '1:0:comb_bwd'),
                   ('dependency', '0:1:comb_bwd'), ('dependency', '0:0:comb_bwd')]
```

其中第一条错误原文是：
`1:0:disp 依赖 1:0:s，但 1:0:s 在调度里出现得更晚（题面 §4.2 第 4 条：因果性）`。
而 `ex2` 里 `s` 的时长是 0（`Fs=0`），两者都在 `t=0`，`t ≥ dep 完成时刻` 成立 → **合法**；用附录 A 的按 `t` 判定的检查器，同一份调度 **合法且 `Time=4880`**。

**为什么必须修（而不是"写法问题"）**
- 同一份映射（同一 `(t,mb,ℓ,op)` 多重集）只因换行方式不同，从 `ok:true` 变 `ok:false`；
- 现有行为**不一致**：`split_ex1`、`split_mini` 恰好因为行内顺序是拓扑序而被接受（我实测 `ok:true`、`592`/`180`），`split_ex2` 被拒。也就是说语义随书写顺序变化；
- 求解器输出"一 op 一行"是很自然的写法（尤其按时间排序后逐条打印），一旦踩到 `t` 相同且依赖时长为 0，整例被判 0 分。

**必须的修复（只改核心，不改题面）**
把"登记"和"检查"分成两趟：
1. 先遍历全部行，登记所有 `(start,end)` 并同时做 §3.2 的格式检查（`t` 非降、`mb/ℓ/op` 合法性、重复/缺失）；
2. 再统一做依赖/因果性检查（`t >= dep_end`）与引擎互斥检查（按 `(卡组, 引擎)` 收集 `[t, t+dur)` 区间，`dur>0` 才参与，排序后要求 `next.start >= prev.end`）。

保持现有语义不变："零时长不占引擎"、"相等时刻释放合法"、"闭区间内存"。
（若团队另有裁定认为"同一 `t` 只允许一行"，则必须在格式检查里**显式**拒绝重复时间戳并给出 `field` 错误，而不是像现在这样按行序偶发接受/拒绝。）

**回归要求**：`split_ex2` 必须 `ok:true, time=4880`；`split_ex1`/`split_mini` 保持 `ok:true`；7 个验收值与 42 个单测不变。

---

## 5. 题面散文手算值逐项对照（第二把尺子）

这些数字全部来自 `problem-fixed.md` 的正文（不是 `solution-report.md`），用来证明"实现读的公式"就是"题面写的公式"。

| 量 | 题面手算 | `judge` 实现 | 一致 |
|---|---|---|---|
| ex1 `H` / `pin,pout` / `m₀` / `X` / `x` | 16 / (1,0) / 4 / 64 / 70 | 同 | ✅ |
| ex1 十个时长 | (16,70,24,70,16,70,24,24,70,16) | 同 | ✅ |
| ex2 `X` / `x` / `m₀,m₁` / `gemm₀,gemm₁` | 32 / 400 / (4,6) / (16,24) | 同 | ✅ |
| ex3 `P=2` `pin,pout,X,x` | (1,0) / 48, 500 | 同 | ✅ |
| ex3 `P=4` `pin,pout,X,x` / `m₀` | (1,2) / 72, 14400 / 3 | 同 | ✅ |
| ex4 `m₀` / `X,x` / `gemm` | 5 / 40,400 / 20 | 同 | ✅ |
| ex5 `pin,pout` / `X,x` / 十个时长 | (0,0) / 0,0 / (16,0,48,0,16,0,48,24,0,8) | 同 | ✅ |
| ex6 `X,x` / 十个时长 | 64,140 / (16,140,4,140,16,140,4,4,140,16) | 同 | ✅ |
| 均分 `T=10,E=4` → 槽数 | (3,3,2,2) | 同 | ✅ |
| 同一均分下 `m`（MAP `0 0 1 1` / `0 1 0 1`） | 6 / 5 | 同 | ✅ |
| 块→卡组：`V=1,K=2` / `V=2,K=4` | `[0,0]` / `[0,1,1,0]` | 同 | ✅ |

---

## 6. 变异用例（从题面推期望，再对照 t1）

`spec` 列是我按题面推的判定；`j_match` 是 t1 是否符合题面。**唯一不符合的就是 F1**。

| 变异 | spec | judge | 独立复算 | 说明 |
|---|---|---|---|---|
| `split_ex2`（一 op 一行） | 合法 | **非法（dependency×6）** | 合法 4880 | **F1** |
| `split_ex1`（一 op 一行） | 合法 | 合法 592 | 合法 592 | 行内顺序恰好是拓扑序 → 被接受（说明行为不一致） |
| `split_mini`（反向 6 条同 t 拆行） | 合法 | 合法 180 | 合法 180 | 同上 |
| `ex1_engine_overlap`（两个 `disp` 重叠） | 非法 | 非法 engine | 非法 | §4.2 第 3 条 |
| `ex1_time_order`（行序倒置） | 非法 | 非法 field | 非法 | §3.2 第 1 条 |
| `ex1_dup` / `ex1_missing` | 非法 | 非法 duplicate / missing | 同 | §3.2 |
| `ex1_grid_bad`（`V·P·D≠R`） | 非法 | 非法 field | 同 | §4.7.1 |
| `ex1_psi_count`（`K=1` 却给切点）/ `ex1_K2V_no_cut`（`K=2` 无切点） | 非法 | 非法 field | 同 | §4.7.2 |
| `ex1_map_count`（`E/P` 次数不对） | 非法 | 非法 field | 同 | §4.7.3 |
| `ex1_U18_closedMovl` | 非法 | 非法 memory | 同 | 闭区间 `Movl`（半开口径会合法） |
| `ex1_M22_closedMem` | 非法 | 非法 memory | 同 | 闭区间合计 |
| `ex6_M23_closedMovl` | 非法 | 非法 memory | 同 | 隔离 `Movl` 闭区间 |
| `mact_M23_valid` / `mact_M22_closedMact` | 合法 / 非法 | 合法 422 / 非法 memory | 同 | 隔离 `Mact` 闭区间 |
| `k2v_M53_valid`（`K=2V`） | 合法 | 合法 705，`groups=(40,9,4)`、`engines=(160,560)` | 同 | 两块同组：`Mexp=40`、`engines` 累加两块 |
| `k2v_M30_mexp` | 非法 | 非法 memory | 同 | 证明 `Mexp` 把两块都算进同一卡组 |
| `k2v_engine_share`（把 `1:0:s` 移到与 `0:0:gemm` 同刻） | 非法 | 非法 engine | 同 | 证明两块共用一对引擎 |
| `ex5` 锚点反事实（`s_dw`） | 非法 | — | 非法 | 证明锚点是 `disp_bwd`（见 §3.3） |

---

## 7. 备注（非 findings，但建议 captain 明确）

### N1 ·低 · 零时长通信操作计入 `Movl`（闭区间语义的退化情形）
`memory.py` 的闭区间峰值会把 `[t,t]` 这种零长度通信也计为"在途"。例子：
- `mini`：`comb` 在 180 结束、`comb_bwd`/`disp_bwd` 在 180 开始 → `Movl = 3U`；
- `K=2V` 合成用例：8 个零时长通信操作与一次 140 时长的 `comb` 端点重合 → `Movl = 9U`。

题面 §4.6 只说"已开始未完成的通信操作"，没有定义零长度传输；CONTRACT §1 冻结了"闭区间"，所以**当前实现符合契约，不是违规**。
但存在一个可被放大的风险：当 `P=1`（`x=0`，全部通信零时长）且求解器把所有通信操作堆在同一时刻时，`Movl` 可达 `8U`；若 `U` 大、`M` 紧，可能把"按半开口径本可合法"的解判非法。7 个验收值不受影响（`ex5` 余量 `43 ≤ 50`、`mini` `24 ≤ 39`）。
建议：由 captain 明确定一条并写进 CONTRACT/求解器指南——(a) 零时长通信不计入 `Movl`（`closed_peak` 跳过 `end==start` 的区间），或 (b) 保持计入并在指南里提示。

### N2 ·信息 · `mini` 是合成用例
`cases/mini.in` 由 §7.1 的参数补全（`nmb=1`、`α×=β×=0`），`mini.out` = §3.2 的四条前向 + 6 条零时长反向。它可以锚定"格式 + 零时长不占引擎 + Time=180"，但**不是题面官方值**，报告中不得称其为官方样例。

### N3 ·信息 · `K=2V` 没有任何官方样例覆盖
6 个官方样例全是 `K=V`。我用了两个合成用例覆盖：块→卡组镜像、两卡组/两块的 `Mexp`、两块共用一对引擎（`k2v_engine_share` 的 engine 冲突）、`engines` 把两块的层累加。结论正确，但建议 t5/e2e 至少保留一个 `K=2V` 用例，否则这条语义只有单测兜底。

---

## 8. 复核范围与未覆盖部分

**已覆盖**
- §4.1–§4.7 全部规则的代码对照（§1）；
- 7 个验收用例：`time`、`lb`、`groups`、`engines`、逐层 10 个时长、`pin/pout`、`m` 全部逐项与独立复算比对（§2）；
- 题面正文给出的手算值（§5）；
- 20 条变异（合法/非法双向，含 `K=2V` 与闭区间判别性变异）（§6）；
- 三个焦点语义的反事实实验（§3）；
- 纯函数/确定性（重复调用结果字节级一致；t1 自带 purity 测试通过）。

**未覆盖（供 t2/t3/t5 与验收注意）**
1. **规模与性能**：`L=64, nmb=1000`（64 万条）只做了代码审读（单趟扁平数组、`ClosedPeak` 流式、`with_ops=False` 不展开），**没有实跑压力**；10 s 求解时限（属服务层）也不在本任务范围。
2. **输入/网格组合抽样**：只抽了 `P∣S`（ex1/ex2/ex4/ex6、ex3 P=2）、`S∣P`（ex3 P=4）、`V>1`、`D>1`、`P=1`；`V>1 且 D>1 且 S∣P` 这类三方组合没有逐例验证（`peer_counts` 的"所有 (v,d) 的 (pin,pout) 必须相同"逻辑读起来正确，但只做了小样本）。
3. **非法输入的错误面**：错误文案、`MAX_ERRORS=64` 截断、`ParseError` 与 `ok:false` 的分界只抽测了几类。
4. **服务/账本/切片/幂等/超时**（t2/t3/t5）完全不在本任务范围；F1 对 t2/t5 的实际影响是：若 `POST /api/evaluate` 的输入来自"一 op 一行"的 solver 输出，合法解会被判 `ok:false`——t5 的 e2e 建议专门造一条这种输出。
5. **解析器的"溢出/换行"便利逻辑**（`parse.py:120-132,169-181`）比题面格式更宽松（允许负载向量跨行），不影响合法性判定，但属于"实现比题面宽松"，未做进一步对抗测试。

---

## 9. 复跑命令

```bash
cd /home/rainy/hackathon

# 1) t1 自带验收（7 值）与单测
python3 -m judge.core.acceptance          # 期望：7/7 通过，exit 0
python3 -m unittest discover -s judge/tests -t . -q   # 期望：Ran 42 tests, OK

# 2) 独立复算（不 import judge）：把附录 A 存成 verify7.py（仓库根目录）后执行
python3 verify7.py                        # 期望：7 行全部 MATCH=True，groups/lb 与 t1 相同

# 3) F1 复现：把 ex2 拆成"一 op 一行"（同一 (t,mb,ℓ,op) 集合）
python3 - <<'PY'
import sys; sys.path.insert(0,'.')
from judge.core.evaluate import parse_case_text, evaluate
inp=open('cases/ex2.in').read(); out=open('cases/ex2.out').read()
res=[]; ins=False
for ln in out.splitlines():
    tk=ln.split()
    if not ins:
        res.append(ln)
        if tk==['SCHEDULE']: ins=True
    else:
        for op in tk[1:]: res.append(tk[0]+' '+op)
r=evaluate(parse_case_text(inp,'ex2'), "\n".join(res)+"\n")
print(r['ok'], r['time'], [(e['category'],e['at']) for e in r['errors']])
PY
# 期望（当前，F1）：False None [('dependency','1:0:disp'), ...]
# 期望（修复后）：True 4880 []

# 4) 闭区间判别性变异（半开口径会给出相反结论）
python3 - <<'PY'
import sys; sys.path.insert(0,'.')
from judge.core.evaluate import parse_case_text, evaluate
def run(case, out, *, m=None, u=None):
    inp=open(f'cases/{case}.in').read()
    lines=inp.splitlines()
    if m is not None: p=lines[0].split(); p[2]=str(m); lines[0]=' '.join(p)
    if u is not None: p=lines[1].split(); p[4]=str(u); lines[1]=' '.join(p)
    r=evaluate(parse_case_text("\n".join(lines)+"\n",case), open(f'cases/{out}.out').read())
    print(case, f'm={m} u={u}', '->', r['ok'], r['time'], [(g['mexp'],g['movl'],g['mact']) for g in r['groups']])
run('ex1','ex1',u=18)   # 期望非法（闭区间 Movl=2*18）
run('ex6','ex6',m=23)   # 期望非法（隔离 Movl：20+2+2>23）
run('ex1','ex1',m=22)   # 期望非法（闭区间合计 23>22）
PY
```

---

## 附录 A：独立复算脚本（`verify7.py`，不 import `judge`）

放在仓库根目录执行 `python3 verify7.py`。算法与 t1 不同：全局登记后再查依赖、按区间排序查引擎、端点扫描算峰值。

```python
"""独立复算 problem-fixed.md §4 的 7 个验收值（不 import judge）。"""
OPS=["s","disp","gemm","comb","s_bwd","comb_bwd","gemm_dx","gemm_dw","disp_bwd","s_dw"]
ENG={"s":"C","disp":"N","gemm":"C","comb":"N","s_bwd":"C","comb_bwd":"N","gemm_dx":"C","gemm_dw":"C","disp_bwd":"N","s_dw":"C"}
DEP={"s":[],"disp":["s"],"gemm":["disp"],"comb":["gemm"],"s_bwd":["comb"],"comb_bwd":["s_bwd"],
     "gemm_dx":["comb_bwd"],"gemm_dw":["comb_bwd"],"disp_bwd":["gemm_dx"],"s_dw":["comb_bwd"]}
def cd(a,b): return -((-a)//b)
def lines(p): return [l.split() for l in open(p) if l.strip()]
def eval_case(inp,out):
    r=lines(inp); N,S,M,Bin,Bout=map(int,r[0])
    L,E,Z,Zs,U,Uact,k,nmb,Fs,Fio,Fin,ax,bx=map(int,r[1]); d,b=map(int,r[2])
    T=[];LO=[]
    for l in range(L):
        v=list(map(int,r[3+l])); T.append(v[0]); LO.append(v[1:] or None)
    H=d*b//k
    o=lines(out); V,P,D=map(int,o[0]); K=int(o[2][0]); psi=list(map(int,o[2][1:]))
    i=4;MAP=[]
    while o[i]!=["SCHEDULE"]: MAP.append(list(map(int,o[i]))); i+=1
    sched=[]
    for x in o[i+1:]:
        ops=[]
        for tok in x[1:]:
            a,b_,c=tok.split(":"); ops.append((int(a),int(b_),c))
        sched.append((int(x[0]),ops))
    pf=[0]+psi+[L]; gb=lambda bk: bk if bk<V else 2*V-1-bk
    go=[];lg=[[] for _ in range(V)]
    for bk in range(K):
        g=gb(bk)
        for l in range(pf[bk],pf[bk+1]): go.append(g); lg[g].append(l)
    if P>1:
        nodes=[[(v*(P*D)+dd*P+p)//S for p in range(P)] for v in range(V) for dd in range(D)]
        pins={tuple(sum(1 for q in range(P) if q!=p and nodes[j][q]==nodes[j][p]) for p in range(P)) for j in range(len(nodes))}
        assert len(pins)==1, pins
        pin=pins.pop()[0]
    else: pin=0
    pout=P-1-pin
    dur=[]
    for l in range(L):
        load=LO[l]
        if load is None:
            base,rem=divmod(T[l],E); load=[base+(1 if e<rem else 0) for e in range(E)]
        pr=[0]*P
        for e,a in enumerate(load): pr[MAP[l][e]]+=a
        m=max(pr); X=cd(T[l]*H*(P-1),P) if P>1 else 0
        x=max(cd(pin*X,Bin),cd(pout*X,Bout))*Fio if X>0 else 0
        s=T[l]*Fs; g=m*Fin
        dur.append({"s":s,"disp":x,"gemm":g,"comb":x,"s_bwd":cd(ax*s,10**6),"comb_bwd":cd(ax*x,10**6),
                    "gemm_dx":cd(ax*g,10**6),"gemm_dw":cd(ax*bx*g,10**12),
                    "disp_bwd":cd(ax*x,10**6),"s_dw":cd(ax*bx*s,10**12)})
    st={};en={}
    for t,ops in sched:
        for mb,l,op in ops: st[(mb,l,op)]=t; en[(mb,l,op)]=t+dur[l][op]
    for (mb,l,op),t in st.items():
        need=[(l,q) for q in DEP[op]]
        if op=="s" and l>0: need.append((l-1,"comb"))
        if op=="s_bwd" and l<L-1: need.append((l+1,"disp_bwd"))
        for dl,dq in need: assert t>=en[(mb,dl,dq)],(mb,l,op,dl,dq)
    ge={}
    for (mb,l,op),t in st.items():
        if dur[l][op]>0: ge.setdefault((go[l],ENG[op]),[]).append((t,en[(mb,l,op)]))
    for ivs in ge.values():
        ivs.sort()
        for a,b2 in zip(ivs,ivs[1:]): assert b2[0]>=a[1],(a,b2)
    def peak(ivs):
        ev=sorted([(s_,1) for s_,e_ in ivs]+[(e_,-1) for s_,e_ in ivs],key=lambda z:(z[0],-z[1]))
        c=best=0
        for _,dz in ev: c+=dz; best=max(best,c)
        return best
    groups=[]
    for g in range(V):
        mexp=len(lg[g])*((E//P)*Z+Zs)
        pc=peak([(st[(mb,l,op)],en[(mb,l,op)]) for mb in range(nmb) for l in range(L) if go[l]==g for op in ("disp","comb","comb_bwd","disp_bwd")])
        pa=peak([(en[(mb,l,"comb")],st[(mb,l,"s_bwd")]) for mb in range(nmb) for l in range(L) if go[l]==g])
        groups.append((mexp,U*pc,Uact*pa))
    lb=0
    for g in range(V):
        lb=max(lb, nmb*sum(dur[l][op] for l in lg[g] for op in OPS if ENG[op]=="C"),
                  nmb*sum(dur[l][op] for l in lg[g] for op in OPS if ENG[op]=="N"))
    ok=all(sum(x)<=M for x in groups)
    return dict(ok=ok,time=max(en.values()),lb=lb,groups=groups)
EXPECT={"ex1":592,"ex2":4880,"ex3":4000,"ex4":3200,"ex5":416,"ex6":1744,"mini":180}
for n,exp in EXPECT.items():
    r=eval_case(f"cases/{n}.in",f"cases/{n}.out")
    print(f"{n:5s} time={r['time']:5d}(题面 {exp}) lb={r['lb']:4d} groups(Mexp,Movl,Mact)={r['groups']} ok={r['ok']} MATCH={r['time']==exp}")
```

实测输出（本报告 §2 的"独立"列即来自它）：

```
ex1   time=  592(题面 592) lb= 560 groups(Mexp,Movl,Mact)=[(20, 2, 1)] ok=True MATCH=True
ex2   time= 4880(题面 4880) lb=3200 groups(Mexp,Movl,Mact)=[(40, 2, 2), (40, 2, 1)] ok=True MATCH=True
ex3   time= 4000(题面 4000) lb=4000 groups(Mexp,Movl,Mact)=[(40, 2, 1)] ok=True MATCH=True
ex4   time= 3200(题面 3200) lb=3200 groups(Mexp,Movl,Mact)=[(40, 2, 1)] ok=True MATCH=True
ex5   time=  416(题面 416) lb= 320 groups(Mexp,Movl,Mact)=[(40, 1, 2), (40, 1, 1)] ok=True MATCH=True
ex6   time= 1744(题面 1744) lb=1120 groups(Mexp,Movl,Mact)=[(20, 2, 2), (20, 2, 1)] ok=True MATCH=True
mini  time=  180(题面 180) lb= 140 groups(Mexp,Movl,Mact)=[(20, 3, 1)] ok=True MATCH=True
```

---

## 附录 B：`mini` 的合成性质（勿称官方值）

`cases/mini.in` 不是题面给出的输入。题面 §3.2 只给了 4 条前向操作的**片段**（按"每层恰好十个操作"它并不完整，直接提交会被判 `missing`）。团队按 §7.1 的参数补成完整映射（`nmb=1`、`α×=β×=0`，反向 6 条零时长挂在 `t=180`），`Time=180` 与题面片段一致。它能验证"格式 + 零时长不占引擎 + `Time=max(t+dur)`"，**不能**当作官方样例或最优值。

---

# 第二轮复核（t8）：t7 修复的独立复验

**结论：verdict = pass**。t7 只改了 `judge/core/sim.py`（`_simulate` 两趟化）与 `judge/core/memory.py`（`ZERO_LEN_COMM_COUNTS`），另外新增 `judge/tests/test_repair_t7.py`（CONTRACT §11 已追认）。第一轮的 F1 修好了、没有修反、默认路径零回归。

## 10.1 复核项总表

| 复核项 | 方法 | 结果 |
|---|---|---|
| F1 原始复现（拆行） | `cases/ex2.out` 一 op 一行，同 `(t,mb,ℓ,op)` 多重集 | `ok:true, time=4880, errors=[]`（第一轮：`ok:false` + 6 条 dependency） ✅ |
| F1 行序无关性 | 4 种等价写法 × 7 用例：`split` / `split+reverse_rows` / `reverse_ops_in_row` / 两者叠加 | 全部合法且 `Time` 不变；7 例的 `split`/`shuffle` 结果字典与原文**逐字节相同** ✅ |
| 防"修反"（真违规仍拒） | 依赖提前、依赖写在更晚行、同 `t` 两行同引擎、通信真重叠、`t` 下降、重复、缺失 | 7 类全部被拒，`category`/`at`/`dep_end`/`conflicts_with` 定位正确 ✅ |
| 默认路径回归 | 7 例 `evaluate` vs **t6 复核基线**（time/lb/groups/engines） + 独立复算 | 逐项相同 ✅ |
| 7 个验收值 | `judge.core.acceptance` + 独立复算 | 7/7，592/4880/4000/3200/416/1744/180 ✅ |
| 闭区间内存回归 | ex1 `U=18`、ex6 `M=23`、ex5 `movl/mact` | 仍按闭区间判（非法/非法/(1,1)+(2,1)） ✅ |
| N1 开关 | 默认两值 / `ZERO_LEN_COMM_COUNTS=False` | 只改 `Movl`（ex5 0,0；mini 1），`time/lb/ok/mexp/mact` 不变 ✅ |
| 单测 | `python3 -m unittest discover -s judge/tests -t . -q` | **Ran 54 tests OK**（42 原有 + 12 新增） ✅ |
| ops 输出顺序 | `evaluate_detailed`（orig 与 split） | 顺序 = 文件声明顺序（ex1 20 / ex2 40 / mini 10） ✅ |
| 性能 | 64 万条（`L=64,nmb=1000`） | `evaluate` **1.60 s**；`evaluate_detailed` **2.05 s** 产 640000 ops ✅ |

## 10.2 F1 复验细节

- 第一轮 §9 的复现命令现在输出 `True 4880 []`（第一轮是 `False None` + `('dependency','1:0:disp')` 等 6 条）。
- 更强的等价性：对 ex1–ex6/mini 的 `evaluate` 结果做 `json.dumps(sort_keys=True)` 比较，`split` 与 `shuffle`（把同 `t` 的多行倒序、且行内 op 倒序）与原文**完全字节相同**——不只是 `time` 相等。
- 代码读审：`_simulate` 第 1 趟只登记 `(start,end)`；第 2a 趟全量比较 `t >= dep_end`（"未登记"分支降级为防御）；第 2b 趟按 `(卡组, 引擎)` 收集 `dur>0` 的 `[t,t+dur)`，`sort()` 后要求 `begin >= previous_end`。冲突时不推进游标——被拒区间仍会作为"已无效"存在，因此不会漏判后续区间，也不会误放行（我用「A 覆盖 B、B 覆盖 C」的三区间场景核对过推理）。

## 10.3 默认路径回归（与 t6 基线逐项相同）

| 用例 | Time | lb | groups(Mexp,Movl,Mact) | engines(comp,comm,first,last) |
|---|---|---|---|---|
| ex1 | 592 | 560 | (20,2,1) | (240,560,16,576) |
| ex2 | 4880 | 3200 | (40,2,2),(40,2,1) | (96,3200,0,4880),(144,3200,816,4064) |
| ex3 | 4000 | 4000 | (40,2,1) | (72,4000,0,4000) |
| ex4 | 3200 | 3200 | (40,2,1) | (120,3200,0,3200) |
| ex5 | 416 | 320 | (40,1,2),(40,1,1) | (320,0,16,392),(320,0,80,320) |
| ex6 | 1744 | 1120 | (20,2,2),(20,2,1) | (120,1120,16,1744),(120,1120,316,1444) |
| mini | 180 | 140 | (20,3,1) | (40,140,16,180) |

独立复算（本文件附录 A 的 `verify7.py`，不 import `judge`）对这 7 行仍逐项一致；`errors=[]`。

## 10.4 N1 开关

- `memory.ZERO_LEN_COMM_COUNTS = True`（默认，保守口径）；`streamed_peaks` 关闭时跳过 `end == start`；`closed_peak` 新增 `count_zero_length`（默认 `True`，向后兼容）。
- 关闭开关：ex5 `movl=(0,0)`、mini `movl=1`；7 例的 `ok/time/lb` 全不变，`mexp/mact` 全不变。
- **`Mact` 不受开关影响**：mini 的激活区间是 `[180,180]`（零长度），两种口径下 `mact` 都是 1 —— 与题面 §4.6「前向恰好在反向开始时结束，该时刻仍持有这份激活」一致。这正是 `group_memory` 对激活显式传 `count_zero_length=True` 的意义。

## 10.5 观察（不构成 finding，无需改代码）

- **O1（建议改 CONTRACT §11 的 TODO 措辞）**：§11 待办写"下一轮 repair 把它提升为 `ZERO_LEN_COUNTS`，同时作用于 `Movl` 与 `Mact`"。但题面 §4.6 明确要求零长度**激活**计入 `Mact`，不能跟着通信口径一起关。当前实现是**对的**；若照该 TODO 字面实现，反而会引入题面违规。建议改成"通信口径开关；`Mact` 不参与切换"。
- **O2（注释）**：`judge/tests/test_negative.py::test_dependency_listed_before_its_predecessor` 的 docstring 仍写"因果性分支「依赖尚未登记」"；该分支已被 t7 降级为防御，实际走 `t < dep_end`。CONTRACT §11 已记为待办，只影响注释。
- **O3（golden 的自证性）**：`test_repair_t7.py` 的 `GOLDEN_SHA256` 是用当前实现生成的，防不住"实现与指纹一起错"。本轮我改用 **t6 复核记录**（time/lb/groups/engines 七例，来自独立复算与旧实现的双方一致值）作为外部基线，逐项相同，所以"默认路径逐字节不变"成立；建议今后 golden 由 captain 在契约冻结后生成。

## 10.6 本轮未覆盖

- 与第一轮相同：`K=2V` 无官方样例、64 万条只测单份 `evaluate`（未跑服务侧压测）、`nmb` 奇数、`V>1 且 D>1 且 S∣P` 组合、错误文案与 `MAX_ERRORS=64` 的完整面。
- t7 只动 `sim.py`/`memory.py`；`model.py`/`parse.py`/`evaluate.py`/`acceptance.py` 的 mtime 未变（11:58–12:05），我未重新逐条审阅它们，沿用第一轮结论。
- 未复验 `judge/service/*`（mtime 12:28，属 t12/t13 范围）。

## 10.7 复跑命令

```bash
cd /home/rainy/hackathon

# 1) 验收 + 单测（54 个，含 test_repair_t7.py 的 12 条）
python3 -m judge.core.acceptance                                   # 7/7
python3 -m unittest discover -s judge/tests -t . -q                # Ran 54 tests OK

# 2) F1 原始复现：拆行后必须 ok:true/4880（第一轮为 ok:false + 6 条 dependency）
python3 - <<'PY'
import sys; sys.path.insert(0,'.')
from judge.core.evaluate import parse_case_text, evaluate
inp=open('cases/ex2.in').read(); out=open('cases/ex2.out').read()
lines=out.splitlines(); i=lines.index('SCHEDULE'); head=lines[:i+1]; rows=[]
for line in lines[i+1:]:
    tk=line.split()
    for tok in tk[1:]: rows.append(tk[0]+' '+tok)
r=evaluate(parse_case_text(inp,'ex2'), "\n".join(head+rows)+"\n")
print(r['ok'], r['time'], r['errors'])     # 期望 True 4880 []
PY

# 3) 4 种等价写法结果字典逐字节相同（split / 同 t 行倒序 / 行内倒序 / 叠加）
python3 - <<'PY'
import sys, json; sys.path.insert(0,'.')
from judge.core.evaluate import parse_case_text, evaluate
from judge.core.acceptance import cases_dir
CASES=str(cases_dir())
def split_ops(t):
    ls=t.splitlines(); i=ls.index('SCHEDULE'); return "\n".join(ls[:i+1]+[f"{x.split()[0]} {tok}" for x in ls[i+1:] for tok in x.split()[1:]])+"\n"
def rev_rows(t):
    ls=t.splitlines(); i=ls.index('SCHEDULE'); rows=ls[i+1:]; out=[]; j=0
    while j<len(rows):
        k=j
        while k<len(rows) and rows[k].split()[0]==rows[j].split()[0]: k+=1
        out.extend(reversed(rows[j:k])); j=k
    return "\n".join(ls[:i+1]+out)+"\n"
def rev_ops(t):
    ls=t.splitlines(); i=ls.index('SCHEDULE')
    return "\n".join(ls[:i+1]+[x.split()[0]+' '+' '.join(reversed(x.split()[1:])) for x in ls[i+1:]])+"\n"
for n in ("ex1","ex2","ex3","ex4","ex5","ex6","mini"):
    inp=open(f"{CASES}/{n}.in").read(); out=open(f"{CASES}/{n}.out").read(); case=parse_case_text(inp,n)
    base=json.dumps(evaluate(case,out),sort_keys=True)
    for label,mod in (("split",split_ops),("split+rev_rows",lambda t: rev_rows(split_ops(t))),
                      ("rev_ops",rev_ops),("shuffle",lambda t: rev_rows(rev_ops(t)))):
        print(n,label,json.dumps(evaluate(case,mod(out)),sort_keys=True)==base)
PY

# 4) N1 开关两值（需要直接 import judge.core.memory）
python3 - <<'PY'
import sys; sys.path.insert(0,'.')
from judge.core.evaluate import parse_case_text, evaluate
from judge.core import memory
from judge.core.acceptance import cases_dir
CASES=str(cases_dir())
def ev(n):
    return evaluate(parse_case_text(open(f"{CASES}/{n}.in").read(),n), open(f"{CASES}/{n}.out").read())
print('default ex5 movl', [g['movl'] for g in ev('ex5')['groups']], 'mini', [g['movl'] for g in ev('mini')['groups']])
old=memory.ZERO_LEN_COMM_COUNTS; memory.ZERO_LEN_COMM_COUNTS=False
try:
    print('off     ex5 movl', [g['movl'] for g in ev('ex5')['groups']], 'mini', [g['movl'] for g in ev('mini')['groups']],
          '| mini mact', [g['mact'] for g in ev('mini')['groups']], '| time', [ev(n)['time'] for n in ('ex1','ex2','ex5','ex6','mini')])
finally:
    memory.ZERO_LEN_COMM_COUNTS=old
PY
```

