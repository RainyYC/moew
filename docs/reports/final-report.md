# 结项报告：MoE 分块与重叠吞吐优化 · 判题服务（CONTRACT v2）

- 版本：CONTRACT v2（冻结）；工作目录 `/home/rainy/hackathon`；Python 3.14（stdlib only）
- 报告日期：2026-10-20
- 本报告由 verifier 在 t5（端到端联调 + 独立复核）中编写；**不修改** `judge/`、`solver/`、`ui/`、`cases/`
- 一句话结论：**三层链路已真实跑通**（起真服务 → CLI 提交 → 账本 → 相对分/排名 → headless Chrome 渲染），7 个验收值精确复现，独立实现（不 import judge）逐项一致；报告的 4400/384/1588 与 4040/1460 与题面冲突且低于有效下界，**不可达**，本解未采用。

---

## 0. 结论摘要

| 验证 | 命令 | 结果 |
|---|---|---|
| 端到端（起服务 → CLI 提交 → 账本 → 排名 → 浏览器渲染 → 负例） | `python3 scripts/e2e.py` | **exit 0**：17 PASS / 0 FAIL / 1 SKIP（外部映射不可达，按约定 skip） |
| 7 个验收值（判题核心） | `python3 -m judge acceptance` | **7/7**：592 / 4880 / 4000 / 3200 / 416 / 1744 / 180 |
| 独立复算（不 import judge） | `python3 tools/independent_check.py` | **7/7**：Time / lb / groups / engines 与 judge 完全一致 |
| 服务层语义 | `python3 -m judge selftest` | **23/23**，exit 0 |
| 单元测试 | `python3 -m unittest discover -s judge/tests -t . -q` | **Ran 66 tests · OK** |
| 求解器 6 例 | `python3 solver/solve_all.py --check` | exit 0：576/4880/4000/3200/416/1744，全部 judge 合法、≤题面值、≤10 s |
| 视图护栏 | `python3 ui/lint_viewer.py` | **20/20**，exit 0 |

**7 值（题面 expected → judge）：全部精确复现**；**6 例本解**：ex1 **576**（优于题面 592），其余 4880/4000/3200/416/1744 与题面一致。

---

## 1. 交付物与入口

| 层 | 位置 | 入口 |
|---|---|---|
| 判题核心（唯一权威） | `judge/core/`（parse/model/sim/memory/evaluate/acceptance） | `python3 -m judge eval <case.in> <out>` / `python3 -m judge acceptance` |
| HTTP 服务 + 队列/账本 | `judge/service/`（server/queue/ledger/sse/config/selftest） | `python3 -m judge serve [--port 3081]`（只绑回环） |
| CLI（agent 主要入口） | `judge/cli.py`（+ `judge/__main__.py`） | `judge eval / run / ls / serve / acceptance / selftest` |
| 求解器 | `solver/`（+ `solve_all.py`、`exact.py`、`selftests/`） | `python3 solver/solve_all.py <in> <out>`；批量 `--check`；精确搜索 `--exact` |
| 只读视图 | `ui/`（index/app/styles/fixtures/lint_viewer） | 静态托管 `ui/` + `?base=http://127.0.0.1:3081`（见 §6 注） |
| 端到端脚本 | `scripts/e2e.py` | `python3 scripts/e2e.py` |
| 独立复核器 | `tools/independent_check.py` | `python3 tools/independent_check.py` |
| 账本/产物 | `runs/ledger.jsonl`、`runs/ops/<run>/<case>.jsonl`、`runs/out/<run>/<case>.out` | 只追加；`runs/` 不入库 |

---

## 2. 契约逐条对照（CONTRACT v2）

### §0 三个角色，一条铁律
| 要求 | 实现/证据 | 结论 |
|---|---|---|
| 题面公式唯一实现在 `judge/core`；`ui/` 一行公式都没有 | `ui/lint_viewer.py` 词法级禁公式（20/20）；`grep -rn "ceil\|floor\|mexp\|movl\|mact\|/ "` 在 `ui/` 无实现（lint 覆盖） | ✅ |
| 预览（`POST /api/evaluate`）不写账本；正式提交才写 | e2e 断言：evaluate 前后 `ledger_lines` 不变；预览值 592 与已提交 592 分离（UI 真机 t22） | ✅ |

### §1 判题核心（纯函数）
| 要求 | 实现/证据 | 结论 |
|---|---|---|
| 解析 `.in` / `.out`，格式坏 → `ParseError`（服务层 422） | `judge/core/parse.py`；e2e 非法解走 200+ok:false，解析失败 422（t9/t13 实测） | ✅ |
| 题面 §4 公式唯一实现（时长/内存/Time/engines/groups/lb） | `model.py`/`sim.py`/`memory.py`；`acceptance` 7/7；**独立实现（`tools/independent_check.py`）逐项一致** | ✅ |
| 调度模拟：§4.2 依赖、零时长不占引擎、相等时刻释放、因果性 | `sim.py`；负例 9 类单测 + t8 复核（拆分/重排/same-t 多行变体同判） | ✅ |
| 内存：Mexp/Movl/Mact（闭区间） | `memory.py`；`ZERO_LEN_COMM_COUNTS=True`（§6 题面规则刻意保守） | ✅ |
| 纯函数（无 IO/时钟/随机；AST 检查） | `judge/tests/test_purity.py`（AST + 运行时打桩） | ✅ |

### §2 HTTP 服务
| 条款 | 要求 | 实现/证据 | 结论 |
|---|---|---|---|
| §2.0 | 只绑回环；CORS；不绑 0.0.0.0 | `server.py` `create_server` 拒绝非回环；e2e 起 `127.0.0.1:3081`；`ss` 显示 `127.0.0.1:3081` | ✅ |
| §2.1 | `POST /api/evaluate`：合法 200；非法 **200 + ok:false + time:null**；未知 case 400；坏 JSON 400；解析失败 422；不写账本 | e2e 负例 PASS；t13 48 条断言；`judge/tests/test_api.py` | ✅ |
| §2.2 | `POST /api/runs`：A（outputs）/B（solver）二选一；202 + `{run_id,state}`；幂等 `idempotency_key`；单例 10 s 超时 kill 记 `timeout` | e2e：提交 6 例 done；11 s 假 solver **10.45 s** 终止、state=timeout、category=timeout；同键两次 `created=[True,False]`、同一 run_id、账本只 +1 行（t13 并发测试同） | ✅ |
| §2.3 | `GET /api/runs/{id}`：状态/进度/结果；未知 404 | e2e 轮询到 done；t13 断言 | ✅ |
| §2.4 | `GET /api/runs/{id}/cases/{case}`：ok/time/lb/groups/engines/grid/K/psi/errors/solve_ms/output_sha256/ops_total | e2e 账本与 judge 字段核对；t9 逐字段比对 CONTRACT 示例 | ✅ |
| §2.5 | ops 切片：`since` 含、`until` 不含、`cursor`=过滤 offset、`limit` 上限 20000 | e2e `total=20,limit=5,next=5`、`since=500`→1；t13 40 条六页不重不漏、64 万条 32 页 3.18 s | ✅ |
| §2.6 | `/api/versions`：相对分=各例 `time/base` 几何平均；rank；非法版本 `score:null` 但仍列出 | e2e `score=0.995444` 与手算几何平均一致、rank=1；t13 断言 null 排最后 | ✅ |
| §2.7 | `/api/events` SSE：queued/running/done/failed/timeout + 进度 | t13 SSE 帧断言；UI 用它维护运行态（t22） | ✅ |
| §2.8 | 错误语义 400/404/409/422 | t9/t13 全量断言 | ✅ |

### §3 账本
| 要求 | 实现/证据 | 结论 |
|---|---|---|
| `runs/ledger.jsonl` 只追加、逐行 JSON、`solver_cmd`/`commit`/`output_sha256` 可复现 | e2e 读账本行；t13 打桩 3×`fsync` + `LOCK_EX/LOCK_SH/LOCK_UN`、只追加前缀不变、同命令同 commit 复现同一 time/sha256 | ✅ |
| `ops` 另存 jsonl，只经切片接口暴露 | `runs/ops/<run>/<case>.jsonl`；e2e 只经 `/api/.../ops` 读取 | ✅ |
| 终态在 append + fsync 之后可见 | `queue.py` 顺序；t12 修复并记录在 CONTRACT §11 | ✅ |

### §4 CLI
| 要求 | 实现/证据 | 结论 |
|---|---|---|
| `eval/run/ls/serve/acceptance/selftest` | `judge/cli.py` + `judge/__main__.py`；`--help` 实测 | ✅ |
| 退出码 0/1/2/3/4 | e2e：run 成功 0、超时 **4**、非法/无解 1、用法 2、服务不可用 3；t13 全量 | ✅ |
| `judge run` 阻塞到终态、`--json` 机器可读 | e2e 用 `--json` 解析 run 视图 | ✅ |
| 无服务时本地队列回退（同一账本） | `cli.py` `--local` / 自动回退；t2 实测 | ✅ |

### §5 视图
| 要求 | 实现/证据 | 结论 |
|---|---|---|
| 只画不算、所有数值来自 API、ops 只按视口切片 | `ui/app.js`（无公式）；`lint_viewer.py` 20/20；t22 真机 6 必须 + 3 禁止全绿 | ✅ |
| 空态/连不上只显示「后端未连接」，不回退本地计算 | t22 空态 dump；e2e Chrome dump 断言已连上 | ✅ |
| 版本列表来自 `/api/versions`，无集合端点 `GET /api/runs` | t21/t22；lint 白名单拒绝 `/api/runs?limit=50` | ✅ |

### §7 验收与 §7.1 有效下界
| 要求 | 实现/证据 | 结论 |
|---|---|---|
| 7 值精确复现 | `judge acceptance` 7/7；`tools/independent_check.py` 7/7 | ✅ |
| 有效下界（t10 修正后） | `solver/NOTES.md` §6；`CONTRACT.md` §7.1：576/4832/4000/3200/416/1736 | ✅ |

### §9 边界
| 要求 | 实现/证据 | 结论 |
|---|---|---|
| `judge/` 不 import `solver/` 或 `ui/` | `judge/tests/test_purity.py` + 静态检查 | ✅ |
| `solver/` 只通过子进程调 `python3 -m judge`，不读 core 内部 | `solver/judgedbridge.py`；t10 复核 | ✅ |

---

## 3. 7 个验收值：三方对照

| 用例 | 题面 expected | judge | 独立复算（不 import judge） | lb | groups (Mexp,Movl,Mact) | engines (comp,comm) |
|---|---|---|---|---|---|---|
| ex1 | 592 | 592 | 592 | 560 | (20, 2, 1) | (240, 560) |
| ex2 | 4880 | 4880 | 4880 | 3200 | (40,2,2) (40,2,1) | (96,3200) (144,3200) |
| ex3 | 4000 | 4000 | 4000 | 4000 | (40, 2, 1) | (72, 4000) |
| ex4 | 3200 | 3200 | 3200 | 3200 | (40, 2, 1) | (120, 3200) |
| ex5 | 416 | 416 | 416 | 320 | (40,1,2) (40,1,1) | (320,0) (320,0) |
| ex6 | 1744 | 1744 | 1744 | 1120 | (20,2,2) (20,2,1) | (120,1120) (120,1120) |
| mini（合成，非官方） | 180 | 180 | 180 | 140 | (20, 3, 1) | (40, 140) |

> `mini` 是题面 §3.2 的**合成**样例（`nmb=1`、α=β=0），**不是**官方值；CONTRACT §7 已说明。
> 复跑：`python3 -m judge acceptance`、`python3 tools/independent_check.py`。

---

## 4. 6 例 Time 三方对照（题面 / 报告声称 / 本解）

| 用例 | 题面（`cases/expected.json`） | `solution-report.md` 声称 | 本解（solver/judge） | 判定 |
|---|---|---|---|---|
| ex1 | 592 | 592（报告"持平"） | **576** | 本解优于题面 16（= 有效下界 576） |
| ex2 | **4880** | 4400（官方值）/ **4040**（目标） | **4880** | 报告值低于有效下界 4832 → **不可达**（CONTRACT §8 已判报告错） |
| ex3 | 4000 | 4000 | **4000** | 一致（= 下界，最优） |
| ex4 | 3200 | 3200 | **3200** | 一致（= 下界，最优） |
| ex5 | **416** | 384（官方值/目标） | **416** | 报告值 384 低于有效下界 416 → **不可达** |
| ex6 | **1744** | 1588（官方值）/ **1460**（目标） | **1744** | 报告值 1460 低于有效下界 1736 → **不可达** |

**为什么报告的 4400/384/1588 与 4040/1460 不可信**（CONTRACT §8 / `solver/NOTES.md` §6）：
- 题面 §7.2/§7.5/§7.6 的权威值与 `cases/exN.out` 一致（4880/416/1744）；报告给出的"官方值"（4400/384/1588）与题面公式冲突，CONTRACT §8 已标"报告错"。
- 报告声称的"更优" 4040/384/1460 全部**低于有效下界** 4832/416/1736（下界证明见 `CONTRACT.md` §7.1 与 `solver/NOTES.md` §6：头段 + 引擎工作量 + 跨卡组回落尾段，均为题面 §4.2 硬约束）→ 在题面模型下**不可能达到**，不是"没找到"。
- 本解 6 例：ex1/ex3/ex4/ex5 **已达有效下界（证明最优）**；ex2 距下界 ≤48（≤1.0%）、ex6 ≤8（≤0.5%），可达性未证（`solver/NOTES.md` §9 明确写了"不构成不可达的证明"）。

> 复跑：`python3 solver/solve_all.py --check`、`python3 -m judge eval cases/ex2.in out/ex2.out --json`、`python3 tools/independent_check.py`。

---

## 5. 端到端链路（`scripts/e2e.py`）实测明细

```
PASS judge serve 起在 loopback :: http://127.0.0.1:3081
PASS judge run 提交 6 例 :: run_id=r-0001 state=done
PASS run 终态 done 且 6 例 Time = solver 结果 :: {'ex1':576,'ex2':4880,'ex3':4000,'ex4':3200,'ex5':416,'ex6':1744}
PASS 账本落行且 state=done
PASS 账本 cases Time 与 solver 一致
PASS 账本每例都有 output_sha256
PASS versions 相对分 = 各例 time/base 的几何平均 :: 0.995444
PASS versions 排名 :: rank=1
PASS ops 切片（total=20, limit=5, next=5）
PASS ops since 过滤可用（since 含） :: total=1 ts=[506]
PASS 负例·非法解 200 + ok:false + time:null
PASS 负例·11s 假 solver 记 timeout :: exit=4 {'ex1':'timeout'} category=timeout limit_ms=10000
PASS 超时在 10s 附近终止 :: elapsed=10.45s
PASS 负例·同 idempotency_key 只落一行 :: 202/202 created=True,False rows=3 唯一=3
PASS Chrome dump-dom 含该 run 的版本行 :: run_id=r-0001
PASS Chrome dump-dom 的 #vtime = 该 run 的 ex1 Time :: vtime='576'
PASS UI 已连上后端（账本条数/最后 run 来自 API） :: st-ledger=3 st-run=r-0003
SKIP 外部映射地址 :: http://123.60.231.190:4014 不可达（RemoteDisconnected）
合计：PASS 17 / FAIL 0 / SKIP 1；exit 0
```

- **loopback**：`127.0.0.1:3081`（`E2E_PORT` 可覆盖；端口被占直接失败，避免测到别的服务）。
- **外部映射**：默认 `http://123.60.231.190:4014`（`JUDGE_URL` 可覆盖）；本环境不可达 → **明确 SKIP**（不计失败）。
- **Chrome**：`google-chrome --headless=new --dump-dom`，`--user-data-dir` 指向工程内临时目录；因为 `judge serve` 不托管 `ui/`（`GET /` 返回端点清单 JSON），脚本按 `ui/README.md` 的"方式 A"静态托管 `ui/` 并用 `?base=http://127.0.0.1:3081&sse=0` 指向后端；临时目录（含 chrome profile）跑完删除。
- 账本/临时数据：`JUDGE_RUNS_DIR` 指向工程内临时目录，**不写仓库 `runs/`**（实测 `runs/ledger.jsonl` 仍是 3 行、mtime 不变）。

---

## 6. 未覆盖 / 偏离契约的条目

| 项 | 说明 | 影响 |
|---|---|---|
| `judge/__main__.py` | t2 为实现 `python3 -m judge …` 补的 6 行 dispatch，超出其 inScope；CONTRACT §11 已追认 | 无 |
| `judge/tests/test_repair_t7.py`、`test_service_repair_t12.py` | 修复轮补的测试文件，CONTRACT §11「新增测试文件免前置审批」已记录 | 无 |
| `mini` 用例 | 题面 §3.2 只给 4 条前向操作的输出，不构成完整映射；`cases/mini.*` 按 §7.1 参数 + `nmb=1` + α=β=0 重建，Time=180 与题面一致，**始终标注为合成用例** | 无（不参与 6 例目标） |
| `?cursor=-1` | HTTP 层被 `server.py` 夹成 0（200），manager 层才 400；契约未规定负 cursor，语义无害（t13 观察 O1） | 低 |
| 服务端不托管 `ui/` | `GET /` 返回端点清单 JSON；UI 需静态托管 + `?base=`（`ui/README.md` 的"服务自托管 ui/ 时无需配置"一句与此不符） | 低（文档措辞） |
| `ui/` 护栏是**启发式 tripwire** | 不做函数实参/闭包/对象属性/Proxy 传播；`ui/README.md` 与 lint 首行已声明"关键数字需人工对账"（t22 已接受该口径） | 已知边界 |
| `--exact` 精确搜索只做**部分**计算顺序枚举 | 通信交错穷举（70/4900），计算顺序只对 top-4 通信交错枚举；NOTES §9 明确声明，未写成"不可达" | 已知边界 |
| `--exact` "找到更优解"的渲染路径 | 6 例全部"无改进"，该分支未被用例覆盖（t23 观察 O2） | 未验证代码 |
| 报告 `big1–big4` / 题外 big | 无输入可复核，CONTRACT §8 标"不可复核" | 不验收 |
| 外部映射地址 | 本环境不可达，e2e SKIP；未在真实映射环境验证 | 低 |

---

## 7. 残余风险 / 未解决歧义

1. **Movl 闭区间与零长度通信**（题面 §4.6）：`ZERO_LEN_COMM_COUNTS=True`，`[t,t]` 的通信操作在最坏情况可叠到 `8U`（`P=1` 时 `x=0`）。这是**刻意的保守选择**（宁可放弃一个配置，也不交可能被判非法的解）；官方口径一旦确认可一行切换（`judge/core/memory.py`）。
2. **零时长激活必须计入 Mact**：题面 §4.6 明文"前向恰好在反向开始时结束，该时刻仍持有这份激活"；CONTRACT §11 早先的 `ZERO_LEN_COUNTS` 说法已撤销。
3. **零时长不占引擎、相等时刻释放**：`sim.py` 按题面 §4.2 实现；等价输出的行序/行内顺序不影响判定（t8 复核 28 变体同判）。
4. **报告数值不可复核**：`solution-report.md` 的 4400/384/1588 与题面冲突，4040/384/1460 低于有效下界；big 系列无输入。结项报告只以题面 + judge 为准。
5. **10 s 预算**：服务端硬超时 10 s（e2e 实测 10.45 s 终止）；solver 默认预算 8.5 s、`--exact` 最慢 ex5 ≈5.9 s；极端规模（`L=64,nmb=1000`）单 run 约 5.5 s、峰值 RSS ≈0.57 GB（CONTRACT §11），仍在预算内但内存是已知上限。
6. **账本长期增长**：只追加、无轮转；64 万条 ops 单份约 34 MB，缓存 4 份封顶 ≈76 MB；如需长期运行需外部归档（非目标）。
7. **视图护栏非证明**：lint 是启发式 tripwire；关键数字必须与同一次 API 响应人工对账（t22 结论）。
8. **端口/映射**：服务只绑回环，外部映射由环境提供；e2e 对外部地址只做可达性探测。

---

## 8. 复跑命令（每条结论对应）

```bash
cd /home/rainy/hackathon

# 0) 端到端（服务/CLI/账本/排名/浏览器/负例/外部探测）
python3 scripts/e2e.py

# 1) 7 个验收值（判题核心）
python3 -m judge acceptance

# 2) 独立实现（不 import judge）复算 7 值并与 judge 对照
python3 tools/independent_check.py

# 3) 服务层语义 + 单元测试
python3 -m judge selftest
python3 -m unittest discover -s judge/tests -t . -q

# 4) 求解器（6 例合法 + ≤题面 + ≤10s + 退化形态）
python3 solver/solve_all.py --check

# 5) 视图护栏
python3 ui/lint_viewer.py
python3 ui/lint_viewer.py --self-test

# 6) 手工起服务 + CLI（e2e 的底层动作）
python3 -m judge serve --port 3081 &
python3 -m judge run --version v-manual --commit manual --cases ex1 ex2 ex3 ex4 ex5 ex6 \
    --outputs out --url http://127.0.0.1:3081
python3 -m judge ls
curl -s http://127.0.0.1:3081/api/versions | python3 -m json.tool | head -30
```

---

## 9. 附录：关键文件

```
judge/__init__.py  __main__.py  cli.py
judge/core/       parse.py model.py sim.py memory.py evaluate.py acceptance.py
judge/service/    server.py queue.py ledger.py sse.py config.py selftest.py
judge/tests/      test_acceptance.py test_api.py test_negative.py test_purity.py
                  test_repair_t7.py test_service_repair_t12.py
solver/           solve_all.py solve.py sched.py psi.py place.py formula.py casein.py
                  judgedbridge.py exact.py NOTES.md selftests/
ui/               index.html app.js styles.css fixtures.js lint_viewer.py README.md
cases/            ex1..ex6.in/.out、mini.in/.out、expected.json、README.md
runs/             ledger.jsonl、ops/<run_id>/<case>.jsonl、out/<run_id>/<case>.out
scripts/          e2e.py
tools/            independent_check.py
docs/             review-judge-core.md review-judge-service.md review-solver.md
                  review-solver-exact.md review-ui.md final-report.md
```
