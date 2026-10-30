# MoE Judge · 只读视图（`ui/`）

CONTRACT §5 的纯渲染层：**只画，不算**。题面公式的唯一实现在 `judge/core`，本目录
一行都没有。所有数值（Time / lb / 三块内存 / 相对分 / 排名 / 运行态）都来自 HTTP API；
`ops` 只通过切片接口按视口取。

## 文件

| 文件 | 作用 |
| --- | --- |
| `index.html` | 页面骨架（无外链、无构建步骤） |
| `styles.css` | 样式（视觉参考 `design/judge-ui-mock.html`） |
| `app.js` | fetch / EventSource / 渲染 / 交互 |
| `fixtures.js` | **仅演示**用的静态响应夹具（由 `judge.core` 生成，`?demo=1` 时才加载） |
| `lint_viewer.py` | 静态验收：禁公式、禁 CDN、必需 API 调用、DOM id 一致性 |

## 打开方式

```bash
# 方式 A：静态托管（推荐）
python3 -m http.server 3082 --directory ui
# 打开 http://127.0.0.1:3082/

# 方式 B：直接双击 index.html（file://）
# 服务端已带 Access-Control-Allow-Origin: *，可直接跨源 fetch 127.0.0.1:3081
```

服务地址默认：

- 页面从 `http(s)://` 打开 → 默认同源（本仓库的 `judge serve` **不托管** `ui/`，请用 `?base=http://127.0.0.1:3081` 或静态托管时同源反代）；
- 页面从 `file://` 打开 → `http://127.0.0.1:3081`；
- 覆盖：`?base=http://127.0.0.1:3099` 或点右上角「服务设置」。

连不上服务时只显示 **`后端未连接`** 空态 + 重试按钮，**不会回退到任何本地计算**。

## 数据来源（CONTRACT §2）

| 界面 | API |
| --- | --- |
| 顶部状态条：账本条数、SSE、最后 run | `GET /api/health`（可选）、`GET /api/meta`（可选）、`GET /api/events` |
| 版本账本（相对分 / 排名 / 来源） | `GET /api/versions` |
| 运行记录（活动 / 历史） | `GET /api/runs/{id}`、`GET /api/versions`、`GET /api/meta`、SSE |
| 判分条、校验清单、内存三块、引擎 | `GET /api/runs/{id}/cases/{case}` |
| Gantt、操作清单、A/B 叠加 | `GET /api/runs/{id}/cases/{case}/ops?since=&until=&group=&mb=&limit=&cursor=` |
| 编辑器「载入已提交输出」 | `GET /api/runs/{id}/cases/{case}/output`（可选） |
| 编辑器「预览」 | `POST /api/evaluate`（服务端判题；不写账本） |

`health` / `meta` / `output` 缺失时对应位置显示 `—` 或提示，不影响其它面板。
**没有**集合端点 `GET /api/runs`（CONTRACT §2 未定义）：run 列表由 `/api/versions` +
`/api/meta.last_run` + `/api/meta.active_runs` + SSE 维护。

**活动 run 的口径**：`queued` / `running` 才算活动。面板分两段——活动（来自
`/api/meta.active_runs` 与 SSE `hello`/`run.*`）与历史（`done` / `failed` / `timeout`，
来自 `/api/versions` 与 `/api/runs/{id}`）。顶部「最后 run」取 `S.runs ∪ runList` 中
`created_at` 最新者（含刚提交的 queued/running；`active_runs`/SSE 不带时间戳时用
`run_id` 序号兜底），旁边的「活动」pill 显示 `active_runs[0]` 的 id/state/进度。`active_runs` **不能当全部 run 数**；总数看账本条数。

## 预览 vs 正式（CONTRACT §0）

编辑器只改**文本**，预览值一律回服务端判定：

- 徽标固定为 **`预览 · 本地试算 · 未提交`**；
- 底部**同时**显示 `预览 Time` 与 `已提交 Time`；两者不同时顶部还会出现
  `预览·未提交 616 ≠ 已提交 592`，绝不把预览当正式值；
- 视图不提交 run、不写账本；要固化请走 CLI / `POST /api/runs`。

## 演示模式（`?demo=1`）

`fixtures.js` 是**静态夹具**：用 `judge.core.evaluate_detailed` 预先生成的服务端响应
快照（ex1–ex4，含一个非法版本与 A/B 变体）。它只在显式 `?demo=1` 时通过本地
`<script>` 注入，实时路径永远不会加载；页面顶部会显示「演示夹具（静态）」，SSE 状态
显示「演示（模拟事件）」。

演示模式覆盖：4 个版本（含 `score:null` 非法行）、queued / running / done / failed /
timeout 运行态、A/B 叠加、非法调度错误定位、编辑器双标。

## 便于验收的深链

```
?demo=1                      静态夹具演示
?base=http://127.0.0.1:3099  指定服务地址
?case=ex2                    打开指定用例
?ab=r-0003                   直接把某 run 设为对比 B
?sheet=1&tab=text&preview=1  打开编辑器、切到输出原文并自动预览
?sse=0                       不连 SSE（截图/离线调试用；默认连接）
?run=r-0011                  演示「640000 条 ops」截断徽标（仅 ?demo=1 的静态夹具）
```

## 自检

```bash
python3 ui/lint_viewer.py              # 正常验收
python3 ui/lint_viewer.py --self-test  # 绕过样本回归（B1–B5 注入副本必须被拒）
```

护栏是**词法级**的（t17 起，取代第一版字面正则）：真正分词后再判——禁
`window[...]`/`globalThis[...]`/`self[...]`/`document[...]` 计算键、禁
`eval`/`atob`/`btoa`/`Function(`/`setTimeout("…")`、解析标识符 `\uXXXX` 转义、
识别全局对象别名/括号包裹（`var w = window; w[…]`、`(window)[…]`）、关键字大小写不敏感；
字段/taint 算术覆盖 `+ - * / % | & ^ << >> >>>` 与复合赋值。
`fetch`/`EventSource`/`api` 的调用点还必须从 `init` 或事件回调**可达**
（死函数里的 fetch 不算证据）。`--self-test` 会把复核的 5 个绕过样本注入临时副本，
断言 5/5 被拒、原件仍通过。

### 护栏边界（启发式 tripwire，不是证明）

- **单层变量 taint**：`var x = <含敏感字段（.t/.dur/.time/.lb/.mexp/.movl/.mact/.score）
  或禁用标识符的表达式>` → `x` 记为 taint，随后参与算术即失败。复核的
  `var tt = d.time; tt - 6`（M1）与 `var a = o.t, b = o.dur; a + b`（M2）都在回归里。
- **刻意不做**：函数实参传播、闭包、对象属性、Proxy 的污点传播。因此它挡的是
  “最常见的误写形态”，**不是静态证明**；任何触碰上述字段的关键数字，必须按
  CONTRACT §5 做人工数值对账（页面数字 vs 同一次 API 响应）。
- **展示/几何白名单**：`xFor/pct/clampPct/rangeSpan/activationHTML/opsHTML/rangeFor/
  renderVerdict/renderDiff/renderTrend/fmtInt/fmtScore/num`。这些函数体里的算术只允许
  画图比例、像素定位、显示用 Δ，不得新增题面公式。
- 字符串拼接（`+` 任一侧是字符串字面量/字符串变量）按展示处理，不算数值算术；
  `t + 1 + "s"` 的内层 `t + 1` 仍会被抓。

退出码 0 表示：

- ui 源码中不存在 `ceil` / `Math.*` / `Mexp|Movl|Mact` 计算 / `schedule(` / 题面参数；
- 存在 `fetch(`、`new EventSource(`、`/api/versions`、ops 切片参数、`POST /api/evaluate`；
- 有 `后端未连接` 空态与重试按钮；预览双标与「已提交」并存；
- 版本表含 `run_id · commit · actor` 与 `score/rank`，运行态含四种状态；
- 无 CDN / 无 `package.json` / 无构建链；JS 引用的 DOM id 全部存在；
- `fixtures.js` 是合法 JSON 数据字面量（无 `function`/`=>`/`eval`/`atob`/`window[`/`\u`）；
- ops 超过一页时 Gantt 顶部有「本页 N / total」截断徽标 + 「载入下一页」（`next_cursor`）。

视图的算术仅限：画图比例（`value / limit`）、像素定位、以及显示用 `Δ = B − A`。
时长、内存、调度、Time、lb、相对分、排名全部原样展示 API 返回值。
