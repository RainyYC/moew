# 服务层（HTTP + 账本 + CLI）复核报告（两轮）

- 复核者：verifier（独立复核，未参与 t2/t12 实现；**只读**，未修改 `judge/service` 任何文件）
- 被复核对象：`judge/service/{server,queue,ledger,sse,config,selftest}.py`、`judge/cli.py`、`judge/__main__.py`
- 权威依据：`CONTRACT.md` v2（§2.0–§2.8、§3、§4）与 `problem-fixed.md`（§5.4 的 10 s 时限）
- **当前结论（第二轮 · t13，复验 t12 修复）：verdict = pass**
  - 第一轮的 F5 / F1 / F2 / F4 / F3 **全部修好并被我独立复验**：活动 run 语义、进程组超时 kill（含孙进程）、`deadline_at` 跨重启、切片边界与死循环、64 万条 ops 缓存（首请求 1.88 s 建表 + 后续 ~39 ms/页；32 页全量 **3.18 s** vs 修复前 40.7 s）；
  - §2.1–§2.8 全量回归：**48 条黑盒断言全过**、`judge selftest` **23/23**、单测 **66** 个全绿；账本 fsync/flock、并发幂等、`solver_cmd` 复现、几何平均、SSE、回环绑定均复测通过；
  - 3 条**观察**（不构成 finding）：`?cursor=-1` 在 HTTP 层被 `server.py` 夹成 0（只有 manager 层才 400）、`_kill_process_group` 的 `except` 冗余、Ctrl-C 时在飞的 solver 因独立 session 不会被一起终止。
- 第一轮记录（t9，verdict = needs_revision）保留在 §1–§9 作为审计轨迹；第二轮复验见 §10。

## 第一轮结论摘要（历史）

**verdict = needs_revision**（1 条 medium + 4 条 low，均不影响"能跑"，但都是账本/运行态语义或资源清理上的真实缺陷）。

已确认正确的部分（全部实测）：

| 契约条款 | 结论 |
|---|---|
| §2.1 `/api/evaluate`：合法 200、**非法解 200 + `ok:false`**、输出解析失败 422、用例不存在 400、坏 JSON 400、幂等无副作用（不写账本、不占队列） | ✅ 全过；响应体 `groups/engines` 与 CONTRACT §1 示例逐字段相同 |
| §2.2 `/api/runs`：两种提交方式、202 + queued、`queued→running→done/failed/timeout` | ✅ |
| §2.2 单用例 **10 s** 超时 kill、其余用例继续 | ✅ 直接子进程场景：10.07 s 记 `timeout`，同 run 的 ex2 照常 `done`/4880，无残留进程 |
| §2.2 `idempotency_key` 幂等 | ✅ **并发**两次只落一行、同一 `run_id`；同键不同体不新增；**跨进程重启**仍幂等 |
| §2.3/§2.4 运行视图与用例详情字段 | ✅（`deadline_at` 重启后缺失，见 F2） |
| §2.5 ops 切片：`since` 含 / `until` 不含 / `cursor`=offset / `total` / `next_cursor` | ✅ 40 条与 **64 万条**都不重不漏、顺序与落盘文件一致 |
| §2.6 `/api/versions`：几何平均、rank、非法版本 `score:null` 仍在列表并排最后 | ✅ 用两个非 1 比值验证（1.168919 / 1.081166） |
| §2.7 SSE：`run.queued/running/done/failed/timeout` | ✅ 帧与字段齐全（`hello` 帧内容有误报，见 F5） |
| §2.8 状态码 | ✅ 200/202/400/404/409/422 全部符合 |
| §3 账本：只追加 + fsync + flock + `solver_cmd` 原文可复现 | ✅ 前缀不变、fsync×3、`LOCK_EX`/`LOCK_SH`、同命令同 commit 复现同一 time/sha256 |
| §2.0 只绑 127.0.0.1 | ✅ `ss` 显示 `127.0.0.1:PORT`；`create_server("0.0.0.0")` 拒绝；CLI `serve --host 0.0.0.0` 退出码 3 |
| §4 CLI | ✅ `eval` 退出码 0/1/2、`ls` 表、`acceptance` |

Findings（详 §3）：

| id | 严重度 | 一句话 |
|---|---|---|
| **F5** | **medium** | `RunManager.active()` 把**已终态**的 run 也算作活动：`/api/health.active_runs`、`/api/meta.active_runs`、SSE `hello.runs` 都列出历史 run（CONTRACT §5.3 的"运行态可见"会因此失真） |
| F1 | low | 10 s 超时只 kill 直接子进程，**孙进程残留**（团队 solver 内部会 `subprocess.run("python3 -m judge eval")`，正是这种形态） |
| F2 | low | 账本行不存 `deadline_at` → 服务重启后 `GET /api/runs/{id}` 的 `deadline_at` 变 `null`（§2.3 列了该字段） |
| F3 | low | `read_ops_slice` 每请求整文件解析：64 万条 1.27 s/页，32 页 40.7 s；UI 按 5000/页要发 128 次请求 |
| F4 | low | `limit=0`（或负数被夹到 0）时 `next_cursor == cursor`，跟着 `next_cursor` 走的客户端会**死循环** |

---

## 1. 语义 → 代码 → 结论

行号指当前工作区。✅ 与契约一致；⚠️ 有缺陷（见 §3）。

### 1.1 §2.1 `POST /api/evaluate`

| 语义 | 代码位置 | 实测 | 结论 |
|---|---|---|---|
| 合法解 200 + §1 响应体 | `server.py:301-320`（`_evaluate`）→ `judge.core.evaluate` | 200，`ok=true time=592`；`groups=[{"v":0,"mexp":20,"movl":2,"mact":1,"limit":39}]`、`engines=[{"v":0,"comp":240,"comm":560,"comm_first":16,"comm_last":576}]` 与 CONTRACT §1 示例**逐字段相同** | ✅ |
| 非法解 **200 + `ok:false`**（不是 4xx） | `server.py:315-320`（`evaluate` 不抛异常，直接 200） | 篡改 `V P D` 后 200 + `ok:false` + `errors[category=field]`，`time=null` | ✅ |
| 输出解析失败 422 | `server.py:316-318` | `@@@` → 422 `{"error":"parse",...}` | ✅ |
| 用例不存在 400 | `server.py:322-328`（`_case_path`，`SAFE_NAME` 防穿越） | `case:"nope"` / `"../../etc/passwd"` → 400 `case-not-found` | ✅ |
| JSON 坏/空体/非对象/缺字段 400 | `server.py:203-223` | 分别 400 `bad-json` / `bad-json` / `bad-request` / `bad-request` | ✅ |
| 幂等、无副作用、不写账本、不占队列 | `server.py:301-320` 只调 core | 连续 3 次 evaluate 后 `meta.ledger_lines` 不变、`active_runs=[]`；两次同请求响应字节级相同 | ✅ |
| 请求体上限 96 MB | `server.py:44,210-211` | 未实跑（见 §5） | ℹ️ |

### 1.2 §2.2 `POST /api/runs`

| 语义 | 代码位置 | 实测 | 结论 |
|---|---|---|---|
| A 式（outputs）202 + `run_id` + `queued` | `server.py:331-402`（`_submit_run`）→ `queue.py:211-246`（`submit`） | 202 `{run_id,state:"queued",created:true,total:2}` | ✅ |
| B 式（solver）202；命令原文入账本 `solver_cmd` | 同上；`queue.py:480` | 202；账本 `solver_cmd` 与提交串完全一致 | ✅ |
| 状态机 `queued→running→done/failed/timeout` | `queue.py:283-319` | 运行中 `GET /api/runs/{id}`=200 `running`，终态 `done`；`case_states` 可见 pending/running/done | ✅ |
| 单用例 **10 s** 超时 kill → 记 `timeout`，其余用例继续 | `queue.py:437-447`（`subprocess.run(timeout=...)`） | 11 s 假 solver（ex1 睡 11 s、ex2 写官方输出）：run `timeout`（10.07 s），ex1 `state=timeout`+`category=timeout`+`limit_ms=10000`，**ex2 照常 `done`/4880**，`ps` 无残留 | ✅（孙进程见 F1） |
| `idempotency_key` 去重、不新增账本行 | `queue.py:213-222,240-242`；重启回填 `255-265` | 见 §2.3 | ✅ |
| solver / outputs 二选一、参数校验 400 | `server.py:342-385` | 7 类非法提交全部 400（二选一/都缺/空 cases/未知 case/重复 case/缺 version/outputs 缺用例） | ✅ |
| 单进程单 worker、账本 flock | `queue.py:203-205,728-730` | 由 §3 账本实证覆盖 | ✅ |

### 1.3 §2.3–§2.7 读接口

| 语义 | 代码位置 | 实测 | 结论 |
|---|---|---|---|
| §2.3 run 视图字段（`done/total/created_at/started_at/deadline_at/results/errors`） | `queue.py:498-537`；账本回退 `545-582` | live 全有且 `deadline_at` 非空；**重启后 `deadline_at=null`** | ⚠️ F2 |
| §2.3 未知 run 404 | `server.py:269-274` | 404 `run-not-found` | ✅ |
| §2.4 case 详情字段齐备 + `ops_total`/`output_sha256` | `queue.py:132-152,584-619` | 12 个字段齐；`ops_total=40`；`sha256` 与原文一致；`ops_path="runs/ops/<run>/<case>.jsonl"` | ✅ |
| §2.4 运行中取结果 409 | `queue.py:591-593`（case 详情）、`665-670`（output） | 运行中 409 `not-ready`；终态 200 | ✅ |
| §2.5 ops 切片（`since` 含 / `until` 不含 / `cursor`=offset / `total`/`next_cursor`/`limit` 上限 20000） | `server.py:405-425`；`ledger.py:122-165` | 见 §2.6 | ✅（F3/F4 为性能/边界） |
| §2.6 `/api/versions` 几何平均、rank 升序、`score:null` 仍出现且排最后 | `ledger.py:168-231`；`server.py:250-251` | 见 §2.7 | ✅ |
| §2.7 SSE 事件（`run.queued/running/done/...`，带 `run_id` 与进度） | `server.py:428-467`；`sse.py:20-65` | 帧齐全、字段齐全；`hello.runs` 误含已终态 run | ⚠️ F5 |

### 1.4 §2.8 错误语义矩阵（实测）

| 场景 | 契约 | 实测 |
|---|---|---|
| 映射非法（evaluate） | 200 + `ok:false` | 200 + `ok:false` ✅ |
| 用例不存在 / JSON 坏 | 400 | 400 `case-not-found` / 400 `bad-json` ✅ |
| 输出解析失败 | 422 | 422 `parse` ✅ |
| 运行中取结果 | 409 | 409 `not-ready` ✅ |
| 未知 run | （契约未列，合理为 404） | 404 `run-not-found` ✅ |
| ops 查询参数非整数 | — | 400 `bad-request`（`since/until/group/mb/limit/cursor` 六项）✅ |
| 请求体过大 | — | 413 `too-large`（代码路径，未实跑 96 MB）ℹ️ |

### 1.5 §3 账本 / §4 CLI / §2.0 绑定

| 语义 | 代码位置 | 实测 | 结论 |
|---|---|---|---|
| 只追加、不改历史 | `ledger.py:61-72`（`open("a")`） | 老内容字节前缀在新追加后不变 | ✅ |
| `fsync` 落盘 | `ledger.py:70,119` | 打桩计数：append×2 + write_ops → `fsync` 3 次 | ✅ |
| `flock` 保护 | `ledger.py:66,71,79,92` | 打桩记录：`LOCK_EX(2)`、`LOCK_SH(8)`、`LOCK_UN(1)` 均出现 | ✅ |
| 一行一次运行、`cases[]` 字段齐、`ops` 另存只存路径 | `ledger.py:61-72,108-120`；`queue.py:111-130,469-485` | 16 字段齐；`ops_path` 均为 `runs/ops/...` | ✅ |
| `solver_cmd` + `commit` 可复现同一 `time`/`output_sha256` | `queue.py:480`；`ledger.py` 落盘 | 同一命令提交两次：`{ex1:(592,sha), ex2:(4880,sha)}` 完全一致 | ✅ |
| §4 CLI 退出码 0/1/2 | `cli.py:122-161` | `eval` 合法 0、非法 1、解析错 2 | ✅ |
| `ls` 摘要表 + 相对分 | `cli.py:360-394` | 表格含 RANK/RUN/SCORE/CASES；rank 与 `/api/versions` 同源 | ✅ |
| 只绑回环 | `server.py:485-489`；`config.py:34` | `ss -ltn` = `127.0.0.1:PORT`；`0.0.0.0` 抛 `ValueError`；CLI 退出码 3 | ✅ |

---

## 2. 实证结果（关键数字）

### 2.1 幂等（并发 / 同键不同体 / 跨重启）

| 场景 | 结果 |
|---|---|
| 同 `idempotency_key`、两个线程用 `Barrier` **同时** POST | 两次都 202；`run_id` 相同；`created` = `[False, True]`；账本**只 +1 行** |
| 同键、**不同 outputs** 再提交 | 202，返回同一 `run_id`，`created=false`，账本行数不变 |
| **杀掉服务→重启**（同一 runs 目录）后用同键提交 | 202，同一 `run_id`，`created=false`，账本行数不变（`_restore_idempotency` 从账本回填） |
| 重启后按 `run_id` 读回 | 200 `done`；case 详情 200/592；ops 仍可切片（total=20） |

### 2.2 10 s 超时

| 场景 | 观察 |
|---|---|
| solver：ex1 睡 11 s，ex2 立即写官方输出（cases=[ex1,ex2]） | 终态 `timeout`，**elapsed 10.07 s**；ex1 `state=timeout`、`category=timeout`、`limit_ms=10000`、`solve_ms=10011`；**ex2 `done`、`ok=true`、`time=4880`**；`ps` 无 `JUDGE_REVIEW_MIX` 残留 |
| solver 派生孙进程（`python3 -c` 里 `subprocess.run(["/bin/sleep","30"])`） | 终态 `timeout`，elapsed 10.01 s（超时语义没被拖慢），但 **`/bin/sleep 30` 仍存活**（`ps` 命中，见 F1） |

### 2.3 ops 切片边界（40 条，ex2）

| 检查 | 结果 |
|---|---|
| 全量 `limit=20000` | `total=40, returned=40, next_cursor=null` |
| `since=T`（取第 4 个时间戳） | `total` = 手算 `t>=T` 的条数，且返回项全 `t>=T`（**含**边界） |
| `until=T` | `total` = 手算 `t<T` 的条数（**不含**边界） |
| `since=T&until=T+1` | 只剩 `t==T` |
| `limit=7` 逐页跟随 `next_cursor` | 6 页、拼接结果与全量**逐条相同**（不重不漏、顺序一致） |
| `group=1` / `mb=0` | 过滤后 total 与手算一致（mb=0 → 20） |
| `limit=999999` | 夹到 20000（40 条场景 returned=40） |
| `cursor=1000`（越界） | `returned=0, next_cursor=null, total=40` |
| `since=abc` 等 6 个参数 | 全部 400 |

### 2.4 ops 切片（64 万条，`L=64, nmb=1000`）

构造用例：`T_l=0`、`Fs=Fin=α=β=0`、`P=1` ⇒ 全部操作时长为 0，`0` 时刻的 1000 行 × 640 个 op，`time=0`。

| 检查 | 结果 |
|---|---|
| 提交→终态 | 202 → `done`，4.01 s（含求值 + 写 64 万条 ops jsonl） |
| `ops_total` / 文件行数 | 640000 / 640000 |
| 单页 `limit=20000` | `total=640000, returned=20000, next_cursor=20000`，**1.27 s** |
| 32 页走完 | 640000 条、`len(set)==640000`、**与落盘文件逐条同序**，**40.72 s** |
| `since=1` / `until=1` / `until=0` / `since=0&until=1` | total 分别 0 / 640000 / 0 / 640000 |
| `cursor=700000` | `returned=0, total=640000, next_cursor=null` |

> 正确性没问题；`1.27 s/页` 来自"每个请求都从头解析整个 jsonl"（F3）。

### 2.5 `/api/versions` 几何平均

| 版本 | cases | 期望 score | 实测 |
|---|---|---|---|
| `v-score-best` | ex1=592 | 1.0 | 1.0 |
| `v-score-slow` | ex1=692 | `692/592 = 1.168919` | 1.168919 |
| `v-score-mix` | ex1=692, ex2=4880 | `sqrt((692/592)(4880/4880)) = 1.081166` | 1.081166 |
| `v-bad`（非法映射）/ `v-parse`（解析失败） | ex1=null | `score=null`、`ok=false`、**仍出现且 rank=最后** | 一致 |
| rank | 升序 1..n | best(1) < mix(2) < slow(3)，null 最后 | 一致 |

`cases` 里每项含 `{time, base, ok}`，`base` 取自 `cases/expected.json`（唯一出处）。一 ok 一非法（ex1 ok、ex2 非法）→ 该版本 `score=null, ok=false`。

### 2.6 SSE

`hello`（带 `runs` 列表）+ `run.queued` + `run.running`×N + `run.done`；每个 `run.*` 帧含 `run_id/state/done/total/version/commit/at`。运行中每 5 s 有 `: ping` 心跳。

---

## 3. Findings

### F5 · **medium** · `judge/service/queue.py:693-695`（`RunManager.active`）→ `server.py:120,136-145,440-453`

**问题**
`active()` 遍历 `self._order`（**所有提交过的 run**，从不清理）返回视图，没有按状态过滤。于是：

- `/api/health` 的 `active_runs` 把**已终态**的 run 也算进去（我提交 2 个都已 `done` → `active_runs=2`）；
- `/api/meta` 的 `active_runs` 列表里是 `[done, done]`；
- SSE `hello.runs` 把历史 run 全列出来（`[('r-0001','done'), ('r-0002','done')]`）。

CONTRACT §5.3 要求视图"运行态可见：queued / running 3/6 / timeout / failed"，§2.7 的事件流也是"运行进度"语义；把已完成的 run 当"活动"会让状态条/活动列表直接失真（UI 若用 `meta.active_runs` 或 `hello.runs` 建运行列表，会显示一堆历史 `done`）。

**必须的修复**
`active()` 只返回 `state in {"queued","running"}` 的视图（或在 `_execute` 进入终态时把它从 `_order`/`_runs` 摘到一个已完成集合，同时保留 `view()`/`case_view()` 的读回能力）。`health/meta/hello` 调用方不用改。

**复跑**

```bash
# 起服务后提交 2 个会立即完成的 run，然后：
python3 - <<'PY'
import json,urllib.request
b="http://127.0.0.1:$PORT"
E=open("cases/ex1.out").read()
for i in range(2):
    r=urllib.request.Request(b+"/api/runs",data=json.dumps({"version":f"v{i}","commit":"c","cases":["ex1"],"outputs":{"ex1":E}}).encode(),headers={"Content-Type":"application/json"},method="POST")
    urllib.request.urlopen(r).read()
import time; time.sleep(0.5)
print("health.active_runs =", json.load(urllib.request.urlopen(b+"/api/health"))["active_runs"])   # 实测 2，应为 0
print("meta.active_runs  =", [x["state"] for x in json.load(urllib.request.urlopen(b+"/api/meta"))["active_runs"]])  # 实测 ['done','done']
PY
```

### F1 · low · `judge/service/queue.py:437-447`（`_run_solver` 的超时处理）

**问题**
`subprocess.run(..., timeout=10)` 超时后只 `kill()` **直接子进程**（POSIX 下再 `wait()`），没有建进程组、没有 `killpg`。若 solver 自己再派生进程，孙进程会变成孤儿继续跑。本项目的 solver 正是这种形态：`solver/judgedbridge.py:71` 会 `subprocess.run([python3, -m, judge, eval, ...])`。

**实测**：solver = `python3 /tmp/spawn.py`，其中 `subprocess.run(["/bin/sleep","30"])`。用例 10.01 s 记 `timeout`（上限本身没被拖慢），但：

```
INFO 孙进程场景：elapsed=10.01s state=timeout 残留=['381 /bin/sleep 30']
```

（直接子进程的 11 s solver 场景**没有**残留，见 §2.2。）

**必须的修复**
用 `Popen(start_new_session=True)`（或 `preexec_fn=os.setsid`）起 solver；`TimeoutExpired` 时 `os.killpg(os.getpgid(proc.pid), signal.SIGKILL)`，再 `proc.wait(timeout=...)`；或用 `timeout -k` 包装。保留"超时 → 该用例 `timeout`、其余用例继续"的语义。

**复跑**

```bash
cat > /tmp/spawn.py <<'EOF'
import subprocess
subprocess.run(["/bin/sleep","30"])
EOF
# POST /api/runs {"solver":"python3 /tmp/spawn.py","cases":["ex1"]}，等终态后：
ps -eo pid,args | grep "/bin/sleep 30" | grep -v grep   # 实测仍有一条
```

### F2 · low · `judge/service/queue.py:469-485`（`_ledger_row` 缺 `deadline_at`）

**问题**
CONTRACT §2.3 的 run 视图列了 `deadline_at`。live 视图（内存里的 `_Run`）有它，但账本行没写；`_view_from_row`（`queue.py:545-582`）只能回 `row.get("deadline_at")` → `None`。于是**服务重启后**再查同一 run，`deadline_at` 变 `null`（其余字段都在）。

**实测**：重启前 `deadline_at=2026-10-20T04:24:38Z`；重启后同一 `run_id` → `deadline_at=None`。

**必须的修复**
要么把 `deadline_at` 写进账本行（`_ledger_row` + `_view_from_row` 透传），要么在 `_view_from_row` 里按 `started_at + timeout × len(cases)` 重算。前者更简单，也不破坏"只追加"。

**复跑**：起服务 → 提交一个 run → 记下 `GET /api/runs/{id}` 的 `deadline_at` → 杀服务、同 `JUDGE_RUNS_DIR` 重启 → 再查同一 `run_id`。

### F3 · low · `judge/service/ledger.py:122-165`（`read_ops_slice` 每请求整文件解析）

**问题**
每次 ops 请求都从头 `for line in handle` 并 `json.loads` **全部**行（包括被 `cursor` 跳过的部分），只为了数 `total` 和取一页。64 万条实测：**1.27 s/页**，32 页全量 **40.72 s**；UI 若按 `limit=5000` 分页，一轮全量要 128 次请求（约 160 s）。`total` 语义要求知道过滤后总数，所以不做索引就只能全扫。

**必须的修复（建议，非契约硬要求）**
落盘 `runs/ops/<run>/<case>.idx`（每 N 行记一次字节偏移 + 该行 `t`），或在写 ops 时按 `t` 分桶；至少让"跳过 cursor 之前的行"不做 `json.loads`（只做 `line.count`/前缀匹配），可把单页成本降到 ~1/5。

**复跑**：见附录 A 的 64 万条生成器 + `time curl ".../ops?limit=20000"` 重复 32 次。

### F4 · low · `judge/service/ledger.py:161-164`（`next_cursor` 在空页时不前进）

**问题**
`next_cursor = cursor + len(page) if cursor + len(page) < total else None`。当 `limit<=0`（server 把负数夹成 0，`server.py:413`）时 `len(page)==0`，若 `cursor < total` 就返回 `next_cursor == cursor`——客户端按 `next_cursor` 循环会**原地死循环**。

**实测**：`GET .../ops?limit=0&cursor=3` → `returned=0, next_cursor=3`。

**必须的修复**
`limit < 1` 直接 400（`bad-request`）；或 `next_cursor = None if not page else min(cursor+len(page), total) if cursor+len(page) < total else None`。

---

## 4. 复核范围与未覆盖部分

**已覆盖（实测）**
- §2.0 绑定、§2.1–§2.8 全部端点与状态码、§3 账本、§4 CLI 基本退出码；
- 幂等三态（并发/同键不同体/跨重启）、10 s 超时（直接子进程 + 孙进程反例）、"其余用例继续"；
- ops 切片在 40 条与 64 万条两种规模下的边界与分页；
- 相对分（两个非 1 比值 + 混合合法/非法）、rank 与 null 排序；
- 账本 fsync/flock 打桩、只追加前缀、`solver_cmd` 复现；
- SSE 帧与字段、`hello` 语义；
- `/api/evaluate` 与 CONTRACT §1 示例逐字段对齐。

**未覆盖**
1. **请求体 96 MB 上限 / 413**、以及 `Content-Length` 与实际 body 不一致（keep-alive 请求走私）——代码路径读过，未构造 96 MB 请求。
2. **多进程并发写账本**：契约规定单进程写 + flock；只验证了单进程多线程 + 打桩，未起两个服务指向同一 `runs/`。
3. **崩溃恢复**：`_execute` 先置终态、再 `ledger.append`；若 append 抛错会走 `_fail` 再 append 一行（同一 `run_id` 两行）。属代码审读，未打桩复现；进程在 append 前崩溃则该 run 完全丢失（不在账本、不在列表），契约未定义。
4. **SSE 背压**：慢客户端（队列满丢事件）与多订阅者未压测。
5. **服务层单测**：`judge/tests/` 只有 core 的测试；服务语义全靠 `judge/service/selftest.py`（自测 23/23，但那是 t2 自己写的，**没有**独立 unittest 覆盖 F1/F5 这类边界）。
6. **端口映射 / 外部访问**（CONTRACT §2.0 `rc port`）未验证；只验证了本地回环。
7. **CLI 的 `run` 远端/本地两条路径**只做了 `eval`/`ls`/`acceptance` 冒烟；`run --local`、`--idempotency-key`、离线回退由 selftest 覆盖，未独立重放。
8. **大 case 的 10 s 求解超时**：服务侧超时用假 solver 验证；真实 solver 在 64 万条规模下的耗时属 t4/t5。

---

## 5. 复跑命令

```bash
cd /home/rainy/hackathon

# 0) 背景（t2 自带，不作结论依据）
python3 -m judge acceptance            # 7/7
python3 -m judge selftest              # 23/23

# 1) 起一个隔离的真服务（临时账本 + 随机端口）
W=$(mktemp -d); mkdir -p "$W/runs" "$W/cases"; cp cases/*.in cases/*.out cases/expected.json "$W/cases/"
JUDGE_RUNS_DIR="$W/runs" JUDGE_CASES_DIR="$W/cases" python3 -m judge serve --port 0 &
# 从 stdout 拿端口后：export PORT=…; ss -ltn | grep ":$PORT"   # 期望 127.0.0.1:PORT

# 2) 快速语义探针（状态码 / 幂等 / ops 边界）——完整版见附录 B 的 probe 清单
#    关键几条：
#    非法解 → 200 + ok:false；解析错 → 422；未知 case → 400；未知 run → 404；运行中 case → 409
#    ops: since 含 / until 不含 / cursor=offset / limit=7 分页拼接 == 全量

# 3) F5 复现：提交 2 个已完成的 run 后
#    health.active_runs = 2（应 0）；meta.active_runs = ['done','done']；SSE hello.runs 含历史 run

# 4) F1 复现：solver 派生 /bin/sleep 30，超时后 ps 仍能看到它（见 §3 F1）

# 5) F2 复现：重启后 deadline_at = null（见 §3 F2）

# 6) F3 复现：64 万条 ops 生成器（附录 A）+ 分页计时（1.27 s/页，32 页 40.7 s）

# 7) F4 复现：GET .../ops?limit=0&cursor=3 → returned=0, next_cursor=3
```

### 附录 A：64 万条 ops 用例生成器

```python
W="<临时目录>"; L=64; nmb=1000; E=2
open(f"{W}/cases/big.in","w").write("\n".join(
    ["1 2 1000000000 10 1", f"{L} {E} 0 0 1 1 1 {nmb} 0 10 0 0 0", "8 2"] + ["0"]*L) + "\n")
ops=["s","disp","gemm","comb","s_bwd","comb_bwd","gemm_dx","gemm_dw","disp_bwd","s_dw"]
out=["1 2 1","PSI","1","MAP"] + ["0 1"]*L + ["SCHEDULE"]
for mb in range(nmb):
    out.append("0 " + " ".join(f"{mb}:{l}:{op}" for l in range(L) for op in ops))
open(f"{W}/cases/big.out","w").write("\n".join(out)+"\n")
```

（`T_l=0`、`Fs=Fin=α=β=0`、`P=1` ⇒ 全零时长、`Time=0`、640000 个 op、`Mexp=0`、`Movl=256000·U`、`Mact=64000·Uact`、`M≤10^9` 时合法。）

### 附录 B：探针清单（均为一次性 `python3 - <<'PY'` 脚本，落在 `/tmp`）

| 脚本 | 覆盖 |
|---|---|
| probe1 | §2.1 evaluate 全语义；§2.2 A 式流程；§2.3/§2.4 字段；§2.5 40 条切片；409；提交校验；**并发幂等**；§2.6 versions；§3 账本 schema/只追加；`solver_cmd` 复现；§2.7 SSE |
| probe2 | 10 s 超时（ex1 睡 11 s + ex2 正常）、错误字段、`ps` 残留；孙进程反例 |
| probe3 | 重启后幂等 + 按 run_id/case/ops/versions 读回 |
| probe4 | `append`/`write_ops` 的 fsync、`flock` 打桩计数、只追加前缀、`read_ops_slice` 边界（独立于服务） |
| probe5 | 64 万条：提交、`ops_total`、单页耗时、`limit` 截断、`since/until` 极端值、32 页不重不漏且与落盘文件同序 |
| probe6 | 几何平均两个非 1 值、rank、SSE 字段与 `hello`、ops 参数 400、解析失败 run、运行中 output 409 |
| probe7 | 重启后 `deadline_at`（F2） |
| probe8 | evaluate 响应体与 CONTRACT §1 示例逐字段、混合合法性 score=null、`since>until`、未知 run ops、meta/versions 与账本一致 |
| probe9 | `active_runs` / `meta.active_runs` / SSE `hello.runs` 的终态误报（F5） |

所有探针都用 `JUDGE_RUNS_DIR`/`JUDGE_CASES_DIR` 指向临时目录、`--port 0` 随机端口，跑完即杀进程，**不写仓库 `runs/`**。

---

# 第二轮复核（t13）：t12 修复的独立复验

**结论：verdict = pass**。t12 改了 `judge/service/queue.py`（`active()` 过滤、`Popen(start_new_session=True)` + `killpg`、`deadline_at`、`ops_view` 参数校验）与 `judge/service/ledger.py`（列式 `_OpsTable` 缓存 + `bisect` 切片），另新增 `judge/tests/test_service_repair_t12.py`（12 条，CONTRACT §11 已声明"新增测试文件免前置审批"）。`server.py` 内容与我第一轮复核时一致（`_ops` 仍是 `limit=max(0,min(limit,20000))`、`cursor=max(0,cursor)`）。

## 10.1 复核项总表

| 第一轮 finding | 修复点 | 我的独立复验 | 结论 |
|---|---|---|---|
| F5 medium：`active()` 含终态 run | `queue.py:54 ACTIVE_STATES`、`739-755 active()` | 2 个 done run 后 `health.active_runs=0`、`meta.active_runs=[]`、SSE `hello.runs=[]`；1.0 s 慢 solver 运行中 `active_runs=1`、`meta.state="running"`、`hello.runs=[该 run]`；结束后归 0；终态 run 的 `view/case/ops` 仍可读 | ✅ |
| F1 low：超时只杀直接子进程 | `queue.py` 的 `_run_solver`（`Popen(start_new_session=True)` + `communicate(timeout)` + `killpg` + 回收） | 11 s solver：**10.046 s** 终止、`state=timeout`、同 run 的 ex2 `done/4880`、`ps` 无残留；孙进程场景（solver 内 `subprocess.run(['/bin/sleep','4243'])`）：**10.027 s** 终止、`ps` 精确匹配残留 `[]` | ✅ |
| F2 low：账本缺 `deadline_at` | `_ledger_row` 写入 + `_view_from_row` 对老行按 `started_at+timeout×len(cases)` 重算 | 杀进程重启后同一 run 的 `deadline_at` 与重启前**完全一致**（`2026-10-20T04:38:14Z`）；账本每行都有该字段 | ✅ |
| F4 low：`limit=0` 时 `next_cursor==cursor` | `queue.py:676-679`（`limit<1`/`cursor<0` → 400）、`ledger.py:182`（空页 `next_cursor=None`） | HTTP `?limit=0/-1/-5` → **400**；`?limit=5&cursor=999` → `{total:40, returned:0, next_cursor:null}`；过滤为空 → `next_cursor:null`；最后一页 `next_cursor:null`；in-process `limit=0` → 空页 null；in-process `cursor=-1` → 400 | ✅ |
| F3 low：每页整文件解析 | `ledger.py` 的 `_OpsTable`（列式 `array` + 名字表）+ `_ops_table` 缓存（`mtime_ns`+`size` 失效、`OPS_CACHE_LIMIT=4`）+ `_slice_table` 的 `bisect` 窗口 | 64 万条：首请求 1.88 s（建表），后续 **~39 ms/页**（修复前 1.27 s/页）；32 页全量 **3.18 s**（修复前 40.7 s），640000 条不重不漏、与落盘文件同序；同大小重写 ops 文件（`mtime_ns` 变化）→ 缓存失效并读到新内容；缓存条数封顶 4；列式还原的字段与逐行 `json.loads` 完全相同；`since/until/group/mb/cursor` 边界与 40 条场景一致 | ✅ |

## 10.2 §2.1–§2.8 全量回归（48 条黑盒断言，全部 PASS）

覆盖：evaluate 合法/非法（200 + `ok:false` + `time:null`）/解析失败 422/未知 case、坏 JSON、空体、非对象、缺字段 400/无副作用；runs 202 + `queued` + 终态 `done` 2/2（592/4880）；case 详情字段与 `ops_total=40`；ops 全量/since 含/until 不含/`since=T&until=T+1`/`limit=7` 六页不重不漏/group/mb 过滤/limit 夹 20000/cursor 越界；未知 run 404、未知 case 404、运行中 case 详情 409；并发同 `idempotency_key` 两次 → 同一 `run_id`、`created=[False,True]`、账本只 +1 行，同键不同体不新增；`/api/versions` 两例合法 `score=1.0`、`rank=1..n`、非法版本 `score:null` 且 `rank=最后`；账本行 schema、只追加前缀、`solver_cmd` 原文 + 同命令同 commit 复现同一 `time/sha256`；SSE `run.queued/running/done` 帧字段。

另外：
- `python3 -m judge selftest` → **23/23 通过、exit 0**（t2 自带，仅作对照）；
- `python3 -m unittest discover -s judge/tests -t . -q` → **Ran 66 tests OK**（54 原有 + 12 新增 `test_service_repair_t12.py`）；
- 账本打桩：`append×2 + write_ops` 共 3 次 `os.fsync`；`flock` 记录 `LOCK_EX(2)`、`LOCK_SH(8)`、`LOCK_UN(1)`；只追加前缀不变；
- 账本回退路径（无内存 `_runs`，模拟重启后）：`ops_view` 仍可切片（total=20/returned=7/next=7）、`limit=0` 400、`cursor=-1` 400、未知 run 404；
- 绑定：`ss -ltn` 显示 `127.0.0.1:PORT`（沿用第一轮 `create_server` 拒绝 `0.0.0.0` 的结论，本轮未改该文件）。

## 10.3 观察（不构成 finding、无需改代码）

- **O1**：t12 说"`cursor<0` → 400"，但该 400 只在 `RunManager.ops_view` 层生效；HTTP 入口 `server.py:_ops` 仍先做 `cursor = max(0, cursor)`，所以 `GET …/ops?cursor=-1` 实测是 **200**（返回第 0 页 5 条）。负 cursor 契约未规定，夹成 0 是合理行为；若希望 HTTP 也 400，需要把校验前移到 `_int_param` 之后、夹取之前。
- **O2**：`_kill_process_group` 的 `except (ProcessLookupError, PermissionError, OSError)` 里前两者是 `OSError` 子类，属冗余（不影响行为）。
- **O3**：`start_new_session=True` 让 solver 进入独立 session，`serve` 收到 Ctrl-C 时 `manager.shutdown()` 只等 worker ≤5 s，**在飞的 solver 不会被一起终止**（独立 session 收不到终端的 SIGINT），会在后台跑到自己的 10 s 超时。契约未要求优雅终止子进程，属可接受的取舍；若在意，可在 `shutdown()` 里对当前进程组补一次 `killpg`。

## 10.4 本轮未覆盖

- 与第一轮相同：96 MB/413 请求体未构造；多进程并发写账本未测；SSE 背压未压测；端口映射/外部访问未验；CLI `run` 远端/本地两条路径只做冒烟（selftest 覆盖）。
- 新增未覆盖：`_OpsTable` 对"非按 t 排序"的 ops 文件走线性回退分支（服务自己写出的文件天然有序，本轮只用合成坏文件走过代码路径，未做性能验证）；缓存内存上限（4×~19 MB）只做了条数验证，未测 RSS。
- 未复核 t12 新增测试 `test_service_repair_t12.py` 的断言强度（只确认它被 discover 收集、66 个全绿）；未复核 `judge/core`（t8 已通过）。

## 10.5 复跑命令

```bash
cd /home/rainy/hackathon

# 0) 对照（非结论依据）
python3 -m judge selftest                                   # 23/23, exit 0
python3 -m unittest discover -s judge/tests -t . -q         # Ran 66 tests OK

# 1) 起隔离服务（临时账本 + 随机端口）
W=$(mktemp -d); mkdir -p "$W/runs" "$W/cases"; cp cases/*.in cases/*.out cases/expected.json "$W/cases/"
JUDGE_RUNS_DIR="$W/runs" JUDGE_CASES_DIR="$W/cases" python3 -m judge serve --port 0 &
# 取 stdout 里的端口后 export BASE=http://127.0.0.1:<port>

# 2) F5：2 个 done run 后
#    GET /api/health → active_runs=0；GET /api/meta → active_runs=[]；GET /api/events 的 hello.runs=[]
#    1s 慢 solver 运行中 → active_runs=1、meta.active_runs[0].state="running"

# 3) F1：solver 内派生 /bin/sleep 4243，超时后
#    ps -eo pid,args | grep "/bin/sleep 4243"   → 空（整组被杀）；elapsed ≈ 10.03s

# 4) F2：记下 run 的 deadline_at → 杀服务、同 JUDGE_RUNS_DIR 重启 → 同 run 的 deadline_at 不变

# 5) F4：GET …/ops?limit=0 / ?limit=-1 → 400；?limit=5&cursor=999 → returned=0,next_cursor=null

# 6) F3：64 万条（L=64,nmb=1000）走一遍 32 页 →
#    首页 ~1.9s（建表）、后续 ~39ms/页、全量 ~3.2s，且与 runs/ops/<run>/<case>.jsonl 逐条同序
```

