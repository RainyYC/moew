# t4 复核（round 3 · 终验）：视图纯渲染 + lint tripwire 边界

- **复核对象**：t21（repair-round-3，只改 `ui/`）及其被审对象 t4（`ui/` 纯渲染视图），依据 `CONTRACT.md` §5
- **复核人**：judge（reviewer），t22 attempt `846701ec-a69c-4a03-9149-fbaf4961a190`
- **环境**：Python 3.14 · Chrome 146.0.7680.153（headless）· `python3 -m judge serve --port 3102`
  （`JUDGE_RUNS_DIR=/tmp/ui22-runs`：A=`ex1+ex2`(592/4880)、B=`ex1` 平移 +100(692)、非法版本(score:null)）；
  复核未改 `ui/`，未动仓库 `runs/`。

**三轮历史**

| 轮次 | 结论 | 关键问题 |
| --- | --- | --- |
| round 1（t14） | needs_revision | lint 是**字面正则**，5 种变量拼接全部绕过 |
| round 2（t18） | needs_revision | 词法器已能抓混淆类，但 `ARITH_OPS` 缺 `%`/位运算、无数据流（局部复制即逃） |
| **round 3（t22）** | **pass** | 上述两类已修；剩余绕过全部落在**已声明**的 tripwire 边界内，且 lint/README 明示「不是证明」 |

---

## 0. 结论

**verdict = `pass`（无阻塞 findings；1 条 low 的边界观察）。**

- `python3 ui/lint_viewer.py` → **20/20 PASS、exit 0**；首行已打印
  「公式扫描是启发式 tripwire（单层变量 taint；不追踪实参传播/闭包/对象属性/Proxy），不是证明；
  触碰 .time/.t/.dur/.score 的关键数字仍需人工对账」。
- `python3 ui/lint_viewer.py --self-test` → **exit 0**：B1–B10 + 夹具代码构造 + 端点白名单 +
  5 个绕过样本注入副本全部被拒。
- **round-2 的否决项已修**：运算符缺口（`% | & ^ << >> >>>` 与复合赋值）补齐；
  `d.time % 8` / `d.time | 0` / `d.dur << 1` 现在命中 `tainted-arithmetic`（§2.1）；
  单层 taint 生效：`var tt = d.time; tt - 6`、`var a = o.t, b = o.dur; a + b`、
  题面 `X = ⌈T·H·(P−1)/P⌉` 形式均被拒（§2.2）。
- **未发现未声明的绕过**：我又补了 6 个变体（`d["time"]`、`d?.time`、`(d).time`、`d.time||0`、
  `Number(d.time)`、`d.time` 作实参）——**全部被抓**（§2.3）。仍能逃过的 4 类
  （函数返回值、解构、参数化 helper、同名白名单）**都在 `ui/README.md` 的「护栏边界」里被明确声明**
  （§3），属于「tripwire 不是证明」的已接受边界，不是新的护栏缺陷。
- **视图本身仍然是纯渲染层**：§5 六必须 + 三禁止与 round 1/2 一样全绿（§4/§5），
  真机 `?sse=0` dump 与 CDP 交互复测通过，console 0 异常。

> 关于验收口径：t21 采纳了我在 t18 给出的选项 (b)——把标准显式降为「启发式 tripwire + 人工复核」，
> 并在 README 与 lint 输出里写明边界。按这个标准，本轮**达标**；如果仍要求「任何写法都挡得住」，
> 那需要完整数据流分析（不现实），建议保持现状并在 CONTRACT §5 补一条人工对账要求（见 finding O1）。

---

## 1. 本轮方法（可复跑）

```bash
python3 ui/lint_viewer.py; echo "exit=$?"              # 20/20 PASS，exit=0
python3 ui/lint_viewer.py --self-test; echo "exit=$?"  # exit=0
python3 /tmp/r3_probes.py     # R/M/T/B/P 矩阵（见 §2）
python3 /tmp/r3_edge.py       # E1–E6 边界变体（见 §2.3）

JUDGE_RUNS_DIR=/tmp/ui22-runs JUDGE_HTTP_LOG=1 python3 -m judge serve --port 3102 &
google-chrome --headless=new --no-sandbox --disable-gpu --user-data-dir=/tmp/c22 \
  --virtual-time-budget=15000 --dump-dom \
  "file:///home/rainy/hackathon/ui/index.html?sse=0&base=http://127.0.0.1:3102&case=ex1&ab=r-0002"
# exit=0，37 517 B

python3 /tmp/r3_cdp.py        # 预览双标 / A-B / 空态 / console
python3 /tmp/r3_f5.py         # demo 截断徽标 + 载入下一页
```

---

## 2. lint 绕过矩阵（本轮实测）

方法：`copytree ui/ → /tmp`，在副本 `app.js` 的 IIFE 末尾注入片段，跑**副本自带**的 lint，看 exit 码与命中规则。

### 2.1 round-1/2 的绕过样本：全部被抓

| 样本 | 注入 | 结果 |
| --- | --- | --- |
| R1 | `window["ce" + "il"]` 取 `ceil` | exit=1 `[computed-global]` |
| R2 | `window["Ma" + "th"]` 取 `Math` | exit=1 `[computed-global]` |
| R3 | `eval(atob(base64))` | exit=1 `[dynamic-code]` |
| R4 | 小写 `mexp` 算术 | exit=1 `[formula-ident]` |
| R5 | `\u0063eil` | exit=1 `[unicode-ident]` |
| M1 | `d.time % 8` | exit=1 `[tainted-arithmetic]` ← round-2 缺口已补 |
| M2 | `d.time \| 0` | exit=1 `[tainted-arithmetic]` |
| M3 | `d.dur << 1` | exit=1 `[tainted-arithmetic]` |
| M4 | `d.time - 1`（对照） | exit=1 `[tainted-arithmetic]` |

### 2.2 单层 taint：局部复制也会被抓

| 样本 | 注入 | 结果 |
| --- | --- | --- |
| T1 | `var tt = d.time; var shown = tt - 6;` | exit=1 `[tainted-arithmetic]` |
| T2 | `var a = o.t, b = o.dur; var e = a + b;` | exit=1 `[tainted-arithmetic]` |
| T3 | 题面 `X = (T*H*(P-1)+P-1)/P`（T 来自 `d.time`） | exit=1 `[tainted-arithmetic]` |

### 2.3 我补的 6 个边界变体：全部被抓

| 样本 | 注入 | 结果 |
| --- | --- | --- |
| E1 | `var x = d["time"]; x - 6` | exit=1 `[tainted-arithmetic]` |
| E2 | `var x = d?.time; x - 6` | exit=1 `[tainted-arithmetic]` |
| E3 | `var x = (d).time; x - 6` | exit=1 |
| E4 | `var x = d.time \|\| 0; x - 6` | exit=1 |
| E5 | `var x = Number(d.time); x - 6` | exit=1 |
| E6 | `_id(d.time)` 之后 `x - 6`（实参传入但返回值直接来自 `d.time` 的同行表达式） | exit=1 |

### 2.4 仍能逃过的 4 类：**已声明**的 tripwire 边界

`ui/README.md`「护栏边界（启发式 tripwire，不是证明）」明确写了：**刻意不做**函数实参传播、闭包、
对象属性、Proxy 的污点传播。实测与声明一致：

| 样本 | 注入 | 结果 | 是否已声明 |
| --- | --- | --- | --- |
| B-a | `function _get(d){return d.time;} var x=_get(d); x-6` | 放行 | 是（函数传播） |
| B-b | `var {time} = d; time - 6` | 放行 | 是（对象属性/解构） |
| B-c | `function _endOf(t,d){return t+d;} _endOf(o.t,o.dur)` | 放行 | 是（实参传播） |
| B-d | 自建同名 `function rangeSpan(r){ return r.t1 - r.t0 + 1; }` | 放行 | 是（白名单按名信任，README 已列白名单并注明「不得新增题面公式」） |

### 2.5 误报检查

| 样本 | 结果 |
| --- | --- |
| `var tt = d.time; var s = tt + " 单位";`（展示拼接） | 放行 ✓ |
| `var x = a.time, y = b.time; return y - x;`（白名单外做 Δ） | 报错（设计如此：Δ 必须落在白名单函数里；`renderDiff` 已在白名单，真机 dump 正常） |

---

## 3. 「不是证明」的声明是否到位

| 位置 | 内容 | 结论 |
| --- | --- | --- |
| `python3 ui/lint_viewer.py` 首行 | 「公式扫描是启发式 tripwire（单层变量 taint；不追踪实参传播/闭包/对象属性/Proxy），不是证明；触碰 .time/.t/.dur/.score 的关键数字仍需人工对账」 | 到位 |
| `ui/README.md`「护栏边界」 | 同内容 + 白名单清单 + 「关键数字必须按 CONTRACT §5 人工数值对账」 | 到位 |
| CONTRACT §5 | 仍是「ui/lint_viewer.py 会检查黑名单」的旧措辞（CONTRACT 冻结，未改） | 建议 captain 在 §5 补一句人工对账（finding O1） |

---

## 4. CONTRACT §5 逐条复测（真机）

### 6 条必须

| # | 条款 | 证据 | 结论 |
| --- | --- | --- | --- |
| 1 | 数值来自 API；ops 只走切片 | 服务端日志（`JUDGE_HTTP_LOG=1`）全部为 §2 端点，ops 请求均带 `?limit=4000&since=0&until=593`；页面数值与 API 相等（下表） | 通过 |
| 2 | 断线空态、不得本地算 | 死端口：`后端未连接 · http://127.0.0.1:52647`、`#vtime=—`、版本表「后端未连接」、重试按钮在 | 通过 |
| 3 | 状态条：地址/账本/SSE/最后 run id·state | dump：`st-base=http://127.0.0.1:3102`、`st-ledger=3`、`st-sse=未连接(?sse=0)`、`st-run=r-0003`、`st-runstate=done`、`st-active=—` | 通过 |
| 4 | 版本表来源 `run_id · commit · actor` | dump：`vR3 cc333 1.000 #1 r-0001 · cc333 · reviewer`；非法行 `vR3Bad ee555 null #3 r-0003 · ee555 · reviewer` | 通过 |
| 5 | 运行态 `queued/running 3/6/timeout/failed` | 运行态在 round 2 已实测（`st-active=r-0005 running 0/1`、结束 done）；本轮 `?sse=0` 快照为 done，未回归；demo 夹具含五种状态 | 通过 |
| 6 | 相对分/排名服务端给 | `#vbars`：`相对分 1.000 · 排名 #1（服务端）`；A/B diff：`1.000 → 1.169`、`#1 → #2`，与 `/api/versions` 一致 | 通过 |

数值对账（dump ↔ API）：

| 界面 | 页面值 | API |
| --- | --- | --- |
| `#vtime`（A） | 592 | `/api/runs/r-0001/cases/ex1` → `time 592` |
| 版本表 | 3 行（含 1 行 `null`） | r-0001 1.0/#1、r-0002 1.168919/#2、r-0003 null/#3 |
| A/B ghost | `[data-ghost="1"]` = 17 | `ops?since=0&until=593&limit=4000` → `total 17` |
| A/B diff | `Time 592 → 692 (+100)`、`相对分 1.000 → 1.169`、`排名 #1 → #2` | B `time 692`、score 1.168919 |

### 3 条禁止

| # | 条款 | 证据 | 结论 |
| --- | --- | --- | --- |
| 1 | 无 ceil/max 题面公式实现 | 原件无公式（算术仅在白名单函数：`xFor/pct/clampPct/rangeSpan/activationHTML/opsHTML/rangeFor/renderVerdict/renderDiff/renderTrend/fmtInt/fmtScore/num` 的几何与显示 Δ）；lint 20/20 PASS | 通过 |
| 2 | 不把预览当正式值 | 预览 +30：`pv-time 622` vs `pv-committed 592`，chip「预览·未提交 622 ≠ 已提交 592」，`#vtime` 仍 592、当前行相对分仍 `1.000`；改坏（删 `0:0:comb`）→ `非法 · 1 条`、已提交仍 592；CDP 捕获 3 次 `POST /api/evaluate`（321/323/314 B），服务端日志 `OPTIONS 204 + POST 200` ×3 | 通过 |
| 3 | 无 CDN / 构建链 | lint PASS；本轮所有 dump 均为 `file://` 直开；无 package.json/node_modules | 通过 |

---

## 5. 真机证据

### dump（`?sse=0` 必带）

```bash
chrome --headless=new --no-sandbox --disable-gpu --user-data-dir=/tmp/c22 \
  --virtual-time-budget=15000 --dump-dom \
  "file:///home/rainy/hackathon/ui/index.html?sse=0&base=http://127.0.0.1:3102&case=ex1&ab=r-0002"
# exit=0，37 517 B
```

```
st-base   http://127.0.0.1:3102      st-ledger 3      st-sse 未连接
st-run    r-0003                     st-runstate done  st-active —
#vtime    592                        #oplcnt 匹配 total 20 · 本页 20 · 显示 20 · 视口 [0, 593)
#versions vR3 cc333 1.000 #1 r-0001 · cc333 · reviewer / vR3B dd444 1.169 #2 / vR3Bad ee555 null #3
ghost     [data-ghost="1"] = 17（== 后端 total 17）
```

### 交互（CDP over WebSocket）

| 场景 | 结果 |
| --- | --- |
| 预览初始 | `pv_time 592` = `pv_committed 592` |
| 改好 +30 | `pv_time 622` vs `pv_committed 592`，chip「预览·未提交 622 ≠ 已提交 592」，`#vtime` 仍 592，当前行相对分仍 `1.000` |
| 改坏（删 `0:0:comb`） | `pv_time —`、`pv_committed 592`、`非法 · 1 条` |
| 预览请求 | 3 次 `POST /api/evaluate`（321/323/314 B）；服务端日志 `OPTIONS 204 + POST 200` ×3 |
| A/B | ghost 17、幽灵泳道 3 条、`#cmpsel=r-0002`、diff `Time 592 → 692 / 1.000 → 1.169 / #1 → #2` |
| F5 截断（demo `?run=r-0011`） | `Gantt 截断：本页 20 / 640000 条 ops · 视口 [0, 577)` + 「载入下一页」→「已到末页」+ footer「已追加下一页 ops（本页 20 / 640000）」 |
| 空态 | 「后端未连接 · http://127.0.0.1:52647」、`#vtime=—`、版本表「后端未连接」、重试按钮 |
| console | 0 异常 |

### 服务端日志（F3 回归）

整轮 40+ 条请求：**0 次** `/api/runs?limit`、**0 条 404**；`/api/health`、`/api/versions`、`/api/meta`、
`/api/runs/{id}`、`/api/runs/{id}/cases/{case}`、`/ops?since&until&limit`、`/output`、`/api/events`、
`OPTIONS+POST /api/evaluate` 全部 200/204。

---

## 6. Findings

> 本轮无阻塞 findings（verdict=pass）。以下为边界观察。

### O1 · low · CONTRACT §5 未写明「lint 是 tripwire、关键数字需人工对账」

- **file/line**：`CONTRACT.md` §5（禁止第 1 条）；对照 `ui/README.md`「护栏边界」、`ui/lint_viewer.py` 首行声明
- **问题**：lint 与 README 已明确「启发式 tripwire，不是证明」，但 CONTRACT §5 仍写「`ui/lint_viewer.py`
  会检查黑名单」——读者可能以为 lint 通过就等于「没有第二套实现」。剩余 4 类已声明绕过
  （函数返回值、解构、实参传播、同名白名单）正是这个误差的来源。
- **requiredFix**（captain 决定，CONTRACT 冻结、我未改）：在 §5 补一句「静态检查为启发式护栏；
  每个涉及 `.time/.t/.dur/.score` 的数字需与同一次 API 响应人工对账」，或在 CONTRACT 附一份
  ui 复核清单（本轮 §4 的对账表可直接复用）。

> 非 findings 的说明：B-a–B-d 四类绕过属 README 已声明的设计边界（tripwire 不做数据流），
> 不构成本轮否决项；若未来要收紧，方向是「实参 taint 传播 + 返回值传播」，但那会开始误报
> 合法展示代码，需要同步扩白名单，收益有限。

---

## 7. 附：复跑脚本骨架

```bash
# 副本注入（B/R/M/T/E 任一）
cp -r ui /tmp/ui-probe
python3 - <<'PY'
from pathlib import Path
text = Path("/tmp/ui-probe/app.js").read_text()
marker = text.rfind("})();")
Path("/tmp/ui-probe/app.js").write_text(text[:marker] + "  var shown = d.time % 8;\n" + text[marker:])
PY
python3 /tmp/ui-probe/lint_viewer.py; echo "exit=$?"   # 应 exit=1 并给 [tainted-arithmetic]
```

CDP 场景见 §1 的 `/tmp/r3_cdp.py`、`/tmp/r3_f5.py`：`Page.enable/Runtime.enable/Network.enable` →
`Page.navigate` → `Runtime.evaluate` 读 `#pv-time/#pv-committed/#draftchip/[data-ghost]/#gtrunc/#emptystate`。
真机复核务必：临时 `JUDGE_RUNS_DIR` + `JUDGE_HTTP_LOG=1` + `--dump-dom` 带 `?sse=0`。
