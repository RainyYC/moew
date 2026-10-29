# 团队契约 v2 · 判题服务（captain 冻结，成员不得单方面修改）

权威依据：**`problem-new.md`（2026-10 最新题面，Markdown 版）**；`problem-fixed.md` 是更早的纯文本抽取版，其上下标曾被压平（`10^3`→`103`、`2^16`→`216`），且 §4.4 的 `X_l` 公式有误，已作废。
参考但**不可信**：`solution-report.md`（较弱模型产物；其"官方样例值"列与题面冲突，见 §8）。
视觉参考（**不是**实现依据）：`design/judge-ui-mock.html`。

> 改动本文件只能由 captain 执行，且必须同步修改受影响任务的验收条件。

---

## 0. 三个角色，一条铁律

| 层 | 职责 | 允许做的事 | 禁止做的事 |
|---|---|---|---|
| **判题核心** `judge/core` | 唯一权威 | 解析、校验、模拟、算 Time 与内存 | 搜索、优化、改题面 |
| **服务 + 账本** `judge/service` | 执行与留痕 | 排队、超时、幂等、追加写 ledger、切片 | 自己判合法性（必须调 core） |
| **视图** `ui/` | 只画 | fetch / 渲染 / 交互 | **实现任何题面公式** |

**铁律：题面公式只有一份实现，在 `judge/core`。** 前端不许出现 `ceil` 形式的时长计算、不许算 `Mexp/Movl/Mact`、不许跑调度器。出现第二套实现 = 两个数字都不可信（`solution-report.md` 正是这样把 ex5 的 416 算成 384，然后拿它当基线优化）。

### 预览 vs 正式

编辑器允许前端做"改动前预览"，但必须：

- 只出现在映射编辑器弹层内，标注 `预览 · 本地试算 · 未提交`；
- 视觉上与正式值区分（虚线边框 + 灰字）；
- 与正式值不一致时，**两个都显示**（`预览 5240 / 已提交 5264`），不得只显示一个。

---

## 1. 判题核心契约（纯函数）

```python
# judge/core/evaluate.py
def parse_case(path: str) -> Case: ...
def evaluate(case: Case, output_text: str) -> dict: ...
```

`evaluate` 的返回即 §3.1 的响应体，且必须满足：

- **纯函数**：同输入同输出，不写文件、不读时钟、不联网；
- 非法解 **不抛异常**，返回 `ok: false` + `errors[]`；
- 解析失败抛 `ParseError`（服务层转 422）。

```python
{"ok": true, "time": 592, "lb": 560,
 "groups": [{"v": 0, "mexp": 20, "movl": 2, "mact": 1, "limit": 39}],
 "engines": [{"v": 0, "comp": 240, "comm": 560, "comm_first": 16, "comm_last": 576}],
 "grid": {"V": 1, "P": 2, "D": 1}, "K": 1, "psi": [],
 "errors": []}
```

> **`ex1` 的 `movl` 为什么是 2**（captain 裁定）：§6 采用**闭区间**——"恰好在下次开始时结束算两块"，
> 否则题面"留出空隙是用一单位时间换一块内存"这句话就不成立。ex1 的 8 次 AllToAll 首尾相接，
> 故峰值为 2，合计 `20 + 2 + 1 = 23 ≤ 39`（半开口径下是 22，同样合法）。
>
> 题面 §7.1 的散文里写"Movl=1"，与 §4.6 的规则是同一件事的两种说法，对一个**合法/非法**的判定没有影响。
> 我们**取保守的闭区间**：闭区间下合法的解，在半开口径下必然也合法，反向不成立。
>
> **下游不得硬编码 `movl == 1`。** 任何断言只应检查 `mexp + movl + mact <= limit` 与最终 `time`。

`ops` 不进这个响应（体积不可控），只通过 §3.5 的切片接口取。

---

## 2. HTTP 服务

`python3 -m judge serve [--port 3081]`，**绑 127.0.0.1**。

### 2.0 部署（已实测）

容器内跑、绑回环，通过 Rainbow 的端口映射对外：`rc port 3081` → 外部端口。
**实测：映射会转发到容器内的 loopback 服务**，所以服务不需要绑 `0.0.0.0`。

| | |
| --- | --- |
| 容器内 | `http://127.0.0.1:3081` |
| 外部（办公网段） | `http://123.60.231.190:4013`（API）/ `:4014`（视图） |
| 建立顺序 | **必须先起服务、再建映射**。若映射创建时上游没在监听，之后会一直 `Empty reply from server`（TCP 通、无响应），删掉重建即可（`rc port rm <ext> && rc port 3082`）。 |
| 有效期 | 注册项不过期（团队已确认）。**但实测：从容器内访问 `http://123.60.231.190:<外部端口>` 返回 `Empty reply`（TCP 通、上游失败），改用 0.0.0.0 绑定同样失败**；因此外部访问当前**未验证可用**，`scripts/e2e.py` 对它 SKIP 而非 PASS。容器内 `127.0.0.1:3081` 与 SSH 隧道可用 |
| 名额 | 单容器最多 5 个映射，端口池共用，**用完必撤** (`rc port rm <外部端口>`) |

⚠️ 服务端看到的来源恒为 `127.0.0.1`（映射由宿主机代理），因此**无法用来源做访问控制**。

按团队决定：**不做鉴权** —— 该宿主机的对外网段极窄，视为可信网络。据此定两条纪律：

- 服务仍只绑 `127.0.0.1`，对外只经 `rc port` 映射这一个入口（**不绑 `0.0.0.0`**，避免出现绕过映射的第二条路）；
- `POST /api/runs` 允许携带 `solver` 命令字符串（服务端子进程执行，`timeout=10`），但**必须把命令原文记入账本 `solver_cmd`**，保证任何一行结果都能被复现；能复现是这条设计唯一的硬要求。

### 2.1 `POST /api/evaluate`

```jsonc
{"case": "ex2", "output": "<输出文件全文>"}
→ 200 {"ok": true, "time": 4880, ...}          // 见 §1
```

- 非法解返回 **200 + `ok:false`**，不要用 4xx。4xx 表示"请求本身有问题"（case 不存在、JSON 坏了）。
- 幂等、无副作用、不写账本、不占队列。

### 2.2 `POST /api/runs`

两种提交方式，二选一：

```jsonc
// A) 只登记输出（agent 自己跑完求解器，推荐；服务端不执行任何命令）
{"version":"v0.5", "commit":"3ad9f07", "cases":["ex1","ex2"],
 "outputs":{"ex1":"<输出全文>","ex2":"<输出全文>"},
 "notes":"6 种优先级", "idempotency_key":"sha256(...)"}

// B) 让服务端执行求解命令（入队，10s/例超时；命令原文入账本）
{"version":"v0.5", "commit":"3ad9f07", "cases":["ex1","ex2"],
 "solver":"python3 solver/solve_all.py",
 "notes":"6 种优先级", "idempotency_key":"sha256(...)"}
→ 202 {"run_id": "r-0042", "state": "queued"}
```

- `state ∈ {queued, running, done, failed, timeout}`。
- 单用例求解墙钟上限 **10 s**（题面 §5.4），超时 `kill` 并记该用例 `timeout`，其余用例继续。
- 同 `idempotency_key` 重复提交返回**已存在的 run_id**，不新增账本行。

### 2.3 `GET /api/runs/{run_id}`

```jsonc
{"run_id": "r-0042", "state": "running", "done": 1, "total": 2,
 "created_at": "...", "started_at": "...", "deadline_at": "...",
 "results": [{"case": "ex1", "ok": true, "time": 576, "solve_ms": 210}],
 "errors": []}
```

### 2.4 `GET /api/runs/{run_id}/cases/{case}`

一个用例的全部展示字段：`ok / time / lb / groups / engines / grid / K / psi / errors / solve_ms / output_sha256 / ops_total`。

### 2.5 `GET /api/runs/{run_id}/cases/{case}/ops`

```jsonc
?since=0&until=20000&group=0&mb=0&limit=5000&cursor=0
→ {"total": 40, "returned": 40, "next_cursor": null,
   "ops": [{"t": 816, "mb": 0, "l": 0, "op": "disp", "dur": 400, "g": 0}]}
```

- **必须支持切片**：`L=64, nmb=1000` 时全量 64 万条，前端画不动。
- `total` 是该过滤条件的总数，`returned` 是本页数。

### 2.6 `GET /api/versions`

```jsonc
[{"version": "v0.5", "commit": "3ad9f07", "run_id": "r-0042",
  "score": 1.022, "rank": 2, "ok": true,
  "cases": {"ex1": {"time": 576, "base": 592, "ok": true},
            "ex2": {"time": 5240, "base": 4880, "ok": true}}}]
```

- `score` = 各用例 `time / base` 的**几何平均**（题面 §5.3 按相对成绩聚合）；
- 任一用例非法 → `score: null`，仍要出现在列表里（**不许隐藏失败版本**）；
- `rank` 按 `score` 升序，`null` 排最后。

### 2.7 `GET /api/events`（SSE）

`run.queued / run.running / run.done / run.failed / run.timeout`，每条带 `run_id` 与进度。

### 2.8 错误语义

| 情况 | 状态码 | 体 |
|---|---|---|
| 映射非法 | 200 | `{"ok": false, "errors": [...]}` |
| 用例不存在 / JSON 坏 | 400 | `{"error": "case-not-found"}` |
| 输出解析失败 | 422 | `{"error": "parse", "detail": "..."}` |
| 运行中取结果 | 409 | `{"error": "not-ready", "state": "running"}` |

---

## 3. 账本

`runs/ledger.jsonl`，一行一次运行，**只追加**，不改历史：

```jsonc
{"run_id":"r-0042","created_at":"2026-10-20T11:40:00Z","origin":"cli","actor":"solver",
 "version":"v0.5","commit":"3ad9f07","solver_cmd":"python3 solver/solve_all.py",
 "idem":"sha256:…","notes":"6 种优先级",
 "cases":[{"case":"ex2","ok":true,"time":5240,"lb":3200,"solve_ms":812,
           "output_sha256":"…","grid":{"V":2,"P":2,"D":1},"K":2,"psi":[1],
           "groups":[{"v":0,"mexp":40,"movl":2,"mact":2,"limit":79}],
           "engines":[{"v":0,"comp":96,"comm":3200,"comm_first":0,"comm_last":4880}],
           "ops_path":"runs/ops/r-0042/ex2.jsonl","errors":[]}]}
```

- 写完 `fsync` 再返回 202 之后的终态，避免掉电丢行；
- `ops` 另存 `runs/ops/<run_id>/<case>.jsonl`（每行一个 op），账本只存路径；
- 并发：单进程写，`flock` 保护；
- 只增不改：修正错误版本用新 run，不编辑旧行。

---

## 4. CLI（agent 的主要入口）

```bash
python3 -m judge eval cases/ex2.in out/ex2.out [--json]   # 纯评估，不写账本
python3 -m judge run --version v0.5 --commit $(git rev-parse --short HEAD) \
        --solver "python3 solver/solve_all.py" --cases ex1 ex2   # 排队并等待
python3 -m judge ls [--case ex2] [--limit 20]             # 打印账本摘要表
python3 -m judge gc --keep 50 [--max-size 2G] [--dry-run]  # 清理旧 run 的 ops 明细（不动账本）
python3 -m judge serve [--port 3081]
python3 -m judge acceptance                               # 7 个验收值
```

退出码：`0` 合法/成功；`1` 映射非法；`2` 解析错误；`3` 服务或队列错误；`4` 超时。

`run` 默认阻塞到终态并打印可读摘要（几行、适合贴进对话），`--json` 给机器读。

---

## 5. 视图契约（`ui/`）

必须：

1. 所有数值来自 API；`ops` 只用 §2.5 的切片接口；
2. 连不上服务时显示明确空态（`后端未连接 · 127.0.0.1:3081`），**不得**回退到本地算；
3. 顶部状态条：服务地址、账本条数、SSE 连接状态、最后一次 run 的 `id/state`；
4. 版本表带 `来源`：`run_id · commit · actor`；
5. 运行态可见：`queued / running 3/6 / timeout / failed`；
6. 相对分、排名由服务端给，前端只格式化。

禁止：

- 任何 `ceil`/`max` 形式的题面公式实现（`ui/lint_viewer.py` 做词法级扫描 + `--self-test` 回归）。

> **护栏的威胁模型（captain 记录）**：静态 lint 的目标是防**维护时误写**，不是防刻意绕过。已实测：`Reflect.get(window,"ce"+"il")`、`[window][0]` 仍可绕过（`new Function`、`Object.getOwnPropertyDescriptor`、Unicode 转义、拼接键、小写字段算术均已被拦）。
> 不追求"不可绕过"——JS 是动态语言，任何静态检查都做不到；真正的保障是 §5 第 1 条（所有数值来自 API）在真机 dump 上做**数值对账**。
>
> **每次复核必须做的人工检查（不依赖 lint）**：① 抓 `ui/README.md` 里列出的"触碰数值字段的算术"清单；② 起真服务 + `?sse=0` dump，把页面上出现的每个关键数字（Time/lb/内存三块/引擎占用/相对分/排名）与同一次 API 响应逐一对账；③ 任何一处不等，无论 lint 是否通过，一律 `needs_revision`。
- 把本地预览值当作正式值展示；
- 依赖外部 CDN / 构建链（单文件或同目录静态资源，双击或静态托管即可打开）。

---

## 6. 判题规则要点（细节以题面为准）

全整数运算，禁浮点；`α = α×/10^6`、`β = β×/10^6`。

| 量 | 公式 |
| --- | --- |
| `s_l` | `T_l * Fs` |
| `gemm_l` | `m_l * Fin` |
| `H` | `(d*b)//k` |
| `X_l` | `ceil(T_l * H / P)` —— **每个对端**的字节数（见下注） |
| `x_l` | `max(ceil(pin*X_l/Bin), ceil(pout*X_l/Bout)) * Fio` |

> **`X_l` 的口径修订（2026-10 题面）**：新版写 `X_l = ceil(T_l·H/P)`，是**发给单个对端**的字节数；
> 旧版 `problem-fixed.md` 写的是 `ceil(T_l·H·(P-1)/P)`（发给所有对端的总量），再乘 `pin/pout` 会重复计费。
> P=2 时两式相同（只有一个对端），所以六个官方样例都掩盖了差别；**P≥3 时旧式会把通信时间放大约 (P-1) 倍**。
> 证据：新版 §7.3 的 P=4 例子 `X=24, x=4800`（旧版同一处写 `X=72, x=14400`，但它自己又说 Time=38400=8×4800，
> 说明旧文本的公式本身就是错的）。`judge/core` 与 `solver/formula.py` 已按新版修正，并加了单测锁定 `P=4 ⇒ x=4800`。
| `s_bwd` | `ceil(α * s_l)` |
| `comb_bwd = disp_bwd` | `ceil(α * x_l)` |
| `gemm_dx` | `ceil(α * m_l * Fin)` |
| `gemm_dw` | `ceil(α * β * m_l * Fin)` |
| `s_dw` | `ceil(α * β * s_l)` |

- `m_l = max_r Σ_{e: σ_{l,e}=r} a_{l,e}`；无负载向量时把 `T_l` 均分给 `E` 个专家（前 `T_l % E` 个各多 1）。
- `P ∣ S` → `pin = P-1, pout = 0`；`S ∣ P` → `pin = S-1, pout = P-S`；须按 `q = v*(P*D)+d*P+p` 从物理卡复核。
- 引擎：计算 `{s,gemm,s_bwd,gemm_dx,gemm_dw,s_dw}`，通信 `{disp,comb,comb_bwd,disp_bwd}`；每个卡组各一套；`K=2V` 时两块共用。
- **时长为 0 的操作不占用引擎**（`ex2`/`ex5` 若不如此则自相矛盾）。
- 依赖：层内 `s→disp→gemm→comb`；反向路径 `s_bwd→comb_bwd→gemm_dx→disp_bwd`，`gemm_dw`/`s_dw` 只依赖 `comb_bwd`；`s_bwd ≥ 本层 comb 结束`；`s(l) ≥ comb(l-1)`；`s_bwd(l) ≥ disp_bwd(l+1)`。
- 内存逐卡组：`Mexp = Σ_{该卡组的层}((E/P)Z + Zs)`；`Movl = U × 通信并发峰值`（**闭区间**：恰好在下次开始时结束算两块）；`Mact = Uact × [comb 结束, s_bwd 开始] 内的激活峰值`（闭区间）。三者之和 ≤ `M`。
- `Time = max(start + dur)`；`lb = max_v nmb*max(ΣC_v, ΣWc_v)`。

---

## 7. 验收数值（题面原文给出，`judge acceptance` 必须精确复现）

| 用例 | Time | 出处 |
| --- | --- | --- |
| ex1 | 592 | §7.1 |
| ex2 | 4880 | §7.2 |
| ex3 | 4000 | §7.3 |
| ex4 | 3200 | §7.4 |
| ex5 | 416 | §7.5 |
| ex6 | 1744 | §7.6 |
| mini | 180 | §3.2（**合成**，见下注） |

> `mini` 是**合成用例**，不是题面官方样例：§3.2 只给了 4 条前向操作的片段（按"每层恰好十个操作"
> 它并不完整，直接提交会被判 `missing`）。我们按其参数补全为完整映射（`nmb=1`、`α×=β×=0`、
> `t=180` 的 6 条零时长反向条目），用来锚定"格式 + 零时长不占引擎 + Time 计算"。
> 报告与验收里**不得**把它称作题面官方值。

求解目标：6 例全合法且 `Time ≤` 上表；每例 ≤10 s。

### 7.1 最优性判定（CP-SAT，2026-10-29 规则）

2026-10-29 两条改动：网格由 `V·P=R` 放松为 `V·P ≤ R`（可有空闲卡）；共享专家 `s`/`s_bwd`/`s_dw` 与同层其余操作解耦（`disp` 不再等 `s`，`comb_bwd` 改等本层 `comb`）。逐步说明见 `docs/rule-change-1029.md`。

**六个可见用例的 Time 均为全局最优**，由 OR-Tools CP-SAT 构造性证明（每例 `OPTIMAL`，0.5–0.7 s）：

| 用例 | 题面值 | 本解 = 全局最优 | 判题器 |
| --- | --- | --- | --- |
| ex1 | 592 | **560** | 合法 |
| ex2 | 4880 | **4880** | 合法 |
| ex3 | 4000 | **4000** | 合法 |
| ex4 | 3200 | **3200** | 合法 |
| ex5 | 416 | **368** | 合法 |
| ex6 | 1744 | **1696** | 合法 |

方法：枚举全部 `(V,P,D)` / 切点 / 每层可达 `m_ℓ`，对每个候选建 CP-SAT（每卡组双引擎 `NoOverlap` + 题面 §4.2 依赖 + 零时长不占引擎），取最小 makespan；每个解落盘后由 `judge eval` 复验。详见 `docs/optimality.md`，复现见 `tools/cpsat_global.py`。

**下界口径的修正（重要）**：早先"有效下界 = 头段 + 引擎工作量 + 尾段"的三段相加**不成立**——尾段里的 `comb_bwd`/`disp_bwd` 本已含在通信工作量里，相加会重复计数（ex2 重复了 800）。今后：

- 下界只按**单一来源取 max**（`max(引擎工作量, 链头+工作量, …)`）；
- **不要**用"各段相加"的式子宣称"已证明最优"；
- 判定最优必须用 CP-SAT 这类构造性搜索。

报告声称的 4040 / 384 / 1460 仍然不可达（低于可达值 4880 / 416 / 1744），结论不变。

---

## 8. 已知的题面冲突（以题面为准）

| 用例 | 报告"官方值" | 题面 | 判定 |
| --- | --- | --- | --- |
| ex2 | 4400 | 4880 | 报告错 |
| ex5 | 384 | 416 | 报告错 |
| ex6 | 1588 | 1744 | 报告错 |
| big1–big4 / 题外 big | 有数值 | 无输入 | 不可复核 |

---

## 9. 目录

```
judge/__init__.py
judge/__main__.py  （`python3 -m judge …` 的分发入口；由 t2 在实际实现中补上，captain 追认）
judge/core/        parse.py model.py sim.py memory.py evaluate.py acceptance.py
judge/service/     server.py queue.py ledger.py sse.py selftest.py
judge/cli.py       （thin wrapper）
judge/tests/       unittest
cases/             ex1..ex6.in/.out、mini.in/.out、expected.json
solver/            solve_all.py + 模块（报告 §2 复原）
ui/                index.html app.js styles.css lint_viewer.py
runs/              ledger.jsonl、ops/<run_id>/<case>.jsonl
scripts/e2e.py     端到端
docs/final-report.md
```

`judge/` 不得 import `solver/` 或 `ui/`；`solver/` 可以调 `python3 -m judge eval`（子进程），不得读 `judge/core` 内部状态。

---

## 10. 非目标

- 不模拟真实时钟、不建模 NPU 硬件特性（题面 §2 已声明抽象时间单位）；
- 不做 NPU 实际执行、不做训练数值正确性；
- 不做鉴权与多用户隔离：按团队决定，宿主对外网段极窄，服务视为可信；仍只绑回环、只经端口映射进入；
- 不在前端做任何优化或搜索；
- 不做报告里无法复核的 `big*` 用例复现。

## 11. 已记录的实现偏差与已知问题

| 项 | 说明 |
| --- | --- |
| `judge/__main__.py` | t2 超出其 inScope 补的文件（6 行 dispatch）。`python3 -m judge` 必须有它，captain 追认，已纳入 §9 目录。 |
| `judge/tests/test_service_repair_t12.py` | t12 按"补快测"要求新增的 12 条（不启 HTTP）。按本节"新增测试文件免前置审批"追认。 |
| 服务层已知行为（t13 观察） | ① `?cursor<0` 在 HTTP 层被夹成 0（返回 200），只有 manager 层才 400——契约未要求 400，语义无害；② `Ctrl-C` 不会终止在飞的 solver（它跑在独立会话组里，为的是能整组 kill 超时），最多等到各自的 10s 超时，属可接受。 |
| 终态可见性顺序 | 终态必须在**账本 append + fsync 之后**才对读者可见（否则会出现"`GET` 已 `done` 但账本还没有这行"的窄竞态）。t12 已修；任何后续改动不得把顺序倒回去。 |
| `judge/tests/test_repair_t7.py` | t7 超出其 inScope 补的文件（12 条：行序无关、真违规仍拒、`GOLDEN_SHA256` 不变、开关两值）。captain 追认。新增测试文件属于**追加性改动**，不修改既有测试语义，可免于 scope 前置审批；今后同类"为验收新增测试文件"照此办理。 |
| 极端规模内存 | `L=64, nmb=1000` 单 run 约 5.5 s、峰值 RSS ≈0.57 GB，大头是 core 返回的 64 万 ops dict。当前可接受；若后续要压，给 core 加流式 ops 生成器，而不是加大内存。 |
| ops 切片语义 | `since` 含、`until` 不含、`cursor` = offset（t2 实测口径，UI 与 t5 按此对齐）。 |
| 零长度开关的适用范围（**已修订**） | `ZERO_LEN_COMM_COUNTS` **只作用于 `Movl`**。`Mact` 的零长度激活（`[t,t]`）**必须计入**——题面 §4.6 明文"前向恰好在反向开始时结束，该时刻仍持有这份激活"。本节早先写过"提升为 `ZERO_LEN_COUNTS` 同时作用于两者"，**那是错的，已撤销**：照字面做会引入题面违规。 |
| 预算按规模自动下调 | 单例默认预算不再固定 8.5 s：`n_ops>200k → 5.0`、`>20k → 6.5`、否则 8.5；显式 `--budget` 优先。目的：给进程启动/落盘/并发留余量（实测 big-wide 从 8.07 s 降到 6.10 s，解不变）。 |
| commit 记录 | `judge run` 缺省记录 `<sha>`，工作区脏时为 `<sha>-dirty`；无 git 仓库时退回 `src-<solver+core 源码 sha256 前 12 位>`，不再是 `unknown`。 |
| 数据范围按 2026-10 版 | `nmb ≤ 10^3`（旧文本压平成 103）、`U,Uact ≤ 2^18`、`d ≤ 2^16`、`M ≤ 10^18`；另新增两条输入保证：`T_ℓ` 是 `k` 的倍数、`max T/min T ≤ 1.2`。`bigcases/` 已按此重生成。 |
| 改求解器前先记 hash | `--check` 会**覆盖** `out/*.out`。想在后证明"零回归"，必须在改动前把 `out/` 与 `cases/*.out` 的 sha256 记下来；t11 复核因缺备份，只能用"门控 A/B + Time/judge 不变"间接证明。今后任何改 solver 的修复任务，第一步先落一份 hash 清单。 |
| 已过时的注释（待清） | `solver/sched.py::_simulate` 里 `best_idx<0` 的注释写"不会发生"，实际它是死锁检测点（ex2 触发 2346 次）。不影响行为。 |
| `out/` 目录 | 求解器 `--check` 的产物目录，**生成物不入库**，随时可重算；正式交付解以账本 `runs/ledger.jsonl` 里登记的 run 为准（`runs/out/<run_id>/<case>.out`）。 |
| 待办 · 过时注释 | `judge/tests/test_negative.py::test_dependency_listed_before_its_predecessor` 注释仍写"依赖尚未登记"，实际已是 `t < dep_end` 分支。留下轮 repair 顺手改。 |
| 零长度通信计入 Movl | 闭区间下 `[t,t]` 的通信操作在其瞬间算一份缓冲（`P=1` 时 `x=0`，最坏可叠到 `8U`）。这是**刻意的保守选择**：宁可放弃一个配置，也不交一个可能被判非法的解。实现必须留一个常量开关（如 `ZERO_LEN_COMM_COUNTS = True`），官方口径一旦确认可一行切换。 |
| 依赖检查与书写顺序无关 | 合法调度必须**先登记全部 `(start, end)`，再统一做依赖与引擎区间检查**；不得依赖 `SCHEDULE` 的行序/行内顺序判断依赖（题面 §3.2 只要求 `t` 非降，§4.2.4 只比较时刻）。换行方式不同的等价输出必须同判。 |
