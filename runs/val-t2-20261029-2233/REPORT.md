# t2 更正报告 —— 真实基线、隔离复现与 b01/b12 改进确认

* 验证人：validator，attempt 1，`e69636d2-2ea4-4fe7-a8a7-4ca64323c6b4`
* 时间：2026-10-29 22:33–22:4x CST
* 生产代码零改动：全部命令结束后 `git status` 仍为 `M solver/sched.py`、`M solver/solve.py`
  （+ 已存在的未跟踪 runs），**没有** checkout / reset / stash / 编辑。
* 本报告**推翻了 t1 的若干结论**，以实际命令输出为准。逐条更正见 §7。

> 目录说明：`runs/val-t2-20261029-2233/` 的根目录是我用 `git archive HEAD | tar -x` 解出的
> **全仓 HEAD 快照**（其中 `README.md` 等是 HEAD 原文件），本报告放在 `REPORT.md`，
> 不覆盖快照；真正的隔离运行目录是 `iso-head/`。

---

## 0. 一句话结论

**t1 的基线是假的。** t1 用 `PYTHONPATH=<影子目录> python3 solver/solve_all.py …` 做基线，但
`solve_all.py` 顶部会把**仓库根**插到 `sys.path[0]`，实际加载的是**当前工作区**的
`solver/sched.py` / `solver/solve.py`——t1 的「基线」和「当前」是同一份代码，于是错误地得出
「改动没有效果」。在**完整隔离**（HEAD 的整个 solver 包，cwd 和 PYTHONPATH 都在 runs 下，
子进程打印 `__file__` 确认）之后复测：

| 用例 | 当前工作区（填充+延后生效） | **真实基线 HEAD b7a6a93** | 差值 | judge 独立判定 |
|---|---|---|---|---|
| b01-loose | **5,904,000,000,000** | **6,912,000,000,000** | −1,008,000,000,000（**−14.58%**） | 两者 `ok=true`，Time 与 solver 一致 |
| b12-compute-bound | **98,307,789,776,000,000** | 98,307,789,776,000,000 | 0（**无改善**） | 两者 `ok=true` |

即：**b01 的改进真实存在（−14.6%），b12 没有改善**；t1「两者都无变化」的结论是错的。
b12 没改善的原因也不是 t1 说的「扩展候选被预算挤掉」，而是三条具体路径（§4）。

---

## 1. 基线是否真的不含 fill_gaps（问题 2）

```bash
git status --short
#  M solver/sched.py
#  M solver/solve.py
git log -3 --oneline
# b7a6a93 新增根 README…  / 3260ada 大样例优化空间分析… / b8bebed 同步独立复算器…
git rev-parse HEAD:solver/sched.py HEAD:solver/solve.py
# 5715beebdb4f0727f567a9f3315415f399535c02
# ba9354a83b6d39a8c57d7b3f061a3e8cc5df0944
```

| 项目 | 工作区（当前） | HEAD / iso-head |
|---|---|---|
| `solver/sched.py` md5 | `4a5b9a7e540c91054b584b4974078fd7` | `ddd9e897ecf9d833e0068e11908e3d32` |
| `solver/solve.py` md5 | `9811e539523a6dd29552d683d47ac728` | `b2649b2eefdc70e43e9751d9e103a886` |
| `fill_gaps` 出现在 solver/ 下？ | 是（`sched.py:143,182,286-322`；`solve.py:279` 传 `fill_gaps=True`） | **否**：`grep -rn fill_gaps iso-head/solver/` 无匹配 |
| `schedule()` 签名含 `fill_gaps`？ | `inspect` → True | `inspect` → **False** |
| `_try_config` 源码含 `fill_gaps` / `gap-fill`？ | True / True | **False / False** |
| 排序剪枝：`break  # 已按 lb 升序` vs `continue  # 按 lb×fill 排序` | `continue`（solve.py:459） | `break`（HEAD solve.py:440） |

HEAD 的 `sched.py` 里虽有 `bisect_right`（在 `_earliest_fit` / `compact` 中，与本改动无关），
但**没有** `fill_gaps`。结论：**HEAD b7a6a93 确实不含 fill_gaps 与延后策略，基线成立。**

---

## 2. t1 的影子基线为什么错（问题 3）

`runpy` 复刻 `python3 solver/solve_all.py` 的导入过程（`tools/dump_paths.py`，输出
`logs/t1_shadow_repro.txt`）：

```
solver       -> /home/rainy/hackathon/solver/__init__.py      ← 仓库根，不是影子目录
solver.sched -> /home/rainy/hackathon/solver/sched.py
solver.solve -> /home/rainy/hackathon/solver/solve.py
```

* `solver/solve_all.py` 顶部 `sys.path.insert(0, str(_ROOT))`；脚本方式的 `sys.path[0]` 本来就是仓库根，
  任何 `PYTHONPATH` 上的影子 `solver/` 都排在它后面。
* t1 的影子目录只有 `sched.py`、`solve.py`，缺 `formula/casein/...`：若真命中会直接
  `ModuleNotFoundError: No module named 'solver.casein'`（已在 `logs/t1_shadow_files.txt` 中实测复现）。
  即 t1 的「基线」只可能是当前代码，或根本跑不起来。

**本次隔离方式**（`tools/show_files.py` 打印实际文件，见 `logs/iso_head_files.txt`）：

```bash
A=runs/val-t2-20261029-2233
mkdir -p $A/iso-head && git archive HEAD solver | tar -x -C $A/iso-head     # 完整 solver 包
cd $A/iso-head && PYTHONPATH=$PWD python3 solver/solve_all.py $PWD/b01-loose.in $PWD/b01-loose.out
# solver.sched     .../iso-head/solver/sched.py
# solver.solve     .../iso-head/solver/solve.py
# solver.solve_all .../iso-head/solver/solve_all.py
# solver.formula/casein/place/psi .../iso-head/solver/...
# cwd = .../iso-head
```

产物：`iso-head/*.{out,stderr,stdout}`、`judge/iso-head-*.json`；
当前实现：`current/*.{out,stderr,stdout}`（cwd=仓库根、`PYTHONPATH=<仓库根>`，
`logs/prod_files.txt` 打印 `solver.sched -> /home/rainy/hackathon/solver/sched.py`）。

---

## 3. 复测结果（问题 4；以实际命令输出为准）

### 3.1 单例求解 + 判题

| 用例 | 版本 | solve 耗时 | solver 报告 | judge `--json` | 输出 sha256 |
|---|---|---|---|---|---|
| b01 | 当前 | 5.20 s（wall 5.27 s） | V=64 P=1 Time=5,904,000,000,000 | ok, Time=5,904,000,000,000, lb=4,896,000,000,000 | `418d0105…753aa` |
| b01 | iso-head | 4.97 s（wall 5.05 s） | V=64 P=1 Time=6,912,000,000,000 | ok, Time=6,912,000,000,000, lb=4,896,000,000,000 | `52c4bb55…adbc1b` |
| b12 | 当前 | 6.11 s（wall 6.18 s） | V=64 P=8 Time=98,307,789,776,000,000 | ok, Time=同, lb=69,377,771,358,000,000 | `7a8c9177…6ba95b` |
| b12 | iso-head | 6.10 s（wall 6.18 s） | V=64 P=8 Time=98,307,789,776,000,000 | ok, Time=同, lb=同 | `7a8c9177…6ba95b` |

```bash
A=runs/val-t2-20261029-2233
(cd /home/rainy/hackathon && PYTHONPATH=/home/rainy/hackathon python3 solver/solve_all.py bigcases/battery/b01-loose.in $A/current/b01-loose.out) > $A/current/b01-loose.stdout 2> $A/current/b01-loose.stderr
(cd $A/iso-head && PYTHONPATH=$A/iso-head python3 solver/solve_all.py $A/iso-head/b01-loose.in $A/iso-head/b01-loose.out) > $A/iso-head/b01-loose.stdout 2> $A/iso-head/b01-loose.stderr
python3 -m judge eval bigcases/battery/b01-loose.in $A/current/b01-loose.out --json > $A/judge/current-b01-loose.json
# b12 同理
```

* b01 两份输出**内容不同**（第 72 行起分歧，`cmp` 实测）；b12 两份输出**逐字节相同**。
* 内存（judge `groups`，limit 2,147,483,648 B）：
  * b01 当前 max used **590,413,824**（中位 555,024,384；Movl/Mact 峰值 26,738,688）；
    b01 iso-head max used **590,413,824**（中位 554,237,952）——峰值相同，分布不同；
  * b12 两者相同：max used **94,437,376**（Movl 524,288、Mact 26,738,688）。
* **`stderr` 里没有搜索日志**：`solve_all.py` 以 `log=None` 调 `solve_case`，stderr 只有最后一行 `[solve] …`。
  为此另写 `tools/search_log.py`（隔离 root 内 import，带 `log=` 回调）与
  `tools/trace_tryconfig.py`（进程内包装 `_try_config`，不改文件）补采。

### 3.2 搜索轨迹（`logs/search_*.txt`、`logs/trace_*.txt`）

```
# 当前 b01
[枚举] 124 个候选，最小 lb=4896000000000
[填隙] P=1 V=64 → Time=5904000000000 (lb=4896000000000)          ← 最终解来自这里
RESULT grid P=1 V=64 Time=5904000000000 mode=gap-fill

# iso-head b01
[探窗] W=3 early → 7.0781e13 ; W=12 → 1.9978e13 ; W=102 → 6.967e12
[贪心] P=1 V=64 W=102 early 变体=(False,False,False,False) → Time=6912000000000
RESULT grid P=1 V=64 Time=6912000000000 mode=early

# 当前 b12 / iso-head b12（两份轨迹完全一致）
[探窗] W=3 early → 1.008289e18 ; W=12 → 2.877524e17 ; W=102 → 9.8307789e16
RESULT grid P=8 V=64 Time=98307789776000000 mode=early
```

`trace_tryconfig`：当前 b01 **只调用 1 次 `_try_config`**（P=1，1.26 s 进、5.12 s 出）；
iso-head b01 也只 1 次（1.24–4.95 s）。b12 两版都 2 次：P=8（1.26–4.43 s）、P=4（4.43–5.99 s，无改进）。
**两版都在 6.5 s 预算下被 `search_deadline` 截断**，b12 的 P=2（lb 1.53e17）、P=1（lb 3.06e17）根本没被尝试。

### 3.3 直接调度矩阵（绕过 `_try_config`，`tools/direct_p1.py`，两棵树对比）

b01（V=64，lb 4.896e12）：

| P | custom prio fill=0 | custom prio fill=1 | variant0 fill=0 | variant0 fill=1 | 最大内存 |
|---|---|---|---|---|---|
| 1 | 6.912e12 | **5.904e12** | 6.912e12 | 6.912e12 | 590,413,824 |
| 2 | 5.425116e14 | 5.421576e14 | 5.421576e14 | 5.421576e14 | 295,763,968 |
| 4 | 8.117848e14 | 8.117848e14 | 8.117848e14 | 8.117848e14 | 161,546,240 |

iso-head 在 P=1 上只有 custom fill=0 与 variant0 fill=0，均 6.912e12（`fill_gaps available: False`）。

b12（lb 6.9378e16）：

| P | custom fill=0 | custom fill=1 | variant0 fill=0 | variant0 fill=1 | 最大内存 |
|---|---|---|---|---|---|
| 8 | 9.888983e16 | **8.384350e16** | 9.860024e16 | 9.830779e16 | 94,437,376 |
| 4 | 1.109322e17 | 9.421897e16 | 1.106840e17 | 1.104333e17 | 161,546,240 |
| 16 | 1.635402e17 | 1.574082e17 | 1.702875e17 | 1.699742e17 | 121,241,600 |

这些候选**全部经 judge 判合法**（`tools/emit_candidate.py` → `logs/cand_*.txt`）：

* b01 `P=1 custom fill=1`：solver 5.904e12 / **judge Time=5,904,000,000,000, ok, errors=0**
  （与最终解 sha256 相同）；
* b12 `P=8 custom fill=1`：solver 8.38435e16 / **judge Time=83,843,497,367,000,000, ok**
  （比当前最终解 9.83078e16 好 **14.72%**）；`P=4 custom fill=1`：judge 9.42189e16，也比当前好。
  → **b12 还有现成的 ~14.7% 空间，只是当前搜索路径没走到。**

---

## 4. b12 为什么没改善（实际轨迹）

1. **`configs[0]` 两例不同**（问题 5 实测）：b01 为 `P=1 V=64 lb=4.896e12`；
   b12 为 `P=8 V=64 lb=6.9378e16`（`configs[1]` 是 P=4 lb=7.8003e16）。不能假设两例一致。
2. `configs[0]` 的 `window_candidates`（nmb=102 → 返回全部 102 个窗口）在第一段烧完预算
   （b12 1.26→4.43 s），进入 P=4 时只剩 1.7 s。
3. `solve.py:458-459` 的 `continue`：b12 best.time=9.83078e16；后续 P=16（1.35e17）、P=2（1.53e17）、
   P=1（3.06e17）裸 lb 都 ≥ best.time → 被剪（**合法**）；P=4（7.80e16）放行但时间不够。
4. **新增的 P=1 扩展候选对 b12 从不触发**：`solve.py:269` 条件是 `config.P == 1`，b12 的
   `configs[0].P = 8`。b01 能改善正因为 `configs[0].P == 1`。
5. 因此 **t1 的「扩展候选先抬高 cost.est、挤掉普通列表调度」不成立**：b01 的最终解
   `mode=gap-fill` 就是扩展候选本身（trace：`[填隙]` 之后 5.12 s 退出，`best_now=5904e9`）。

---

## 5. lb 与剪枝（问题 4 后半）

* `lb = max_v nmb·max(ΣC_v, ΣWc_v)` 是同一网格下的合法下界；不同网格用同一公式计算，
  因此 **lb 可以跨网格比较**：`lb(X) < best.time` 只说明 X 未被排除，不说明 X 更差。
  t1「不要跨网格比较 lb」是过度保守的表述，本报告不再使用。
* 例：b12 的 P=8/4/16/1 的 lb = 6.94e16 / 7.80e16 / 1.35e17 / 3.06e17，
  与 §3.3 实测绝对 Time（9.83e16 / 9.42e16 / 1.57e17 / 3.69e17）方向一致。
* **撤回** t1 的建议「剪枝键要与 P 对齐」：`config.lb >= best.time` 剪枝本身合法。

---

## 6. 对「继续优化」的可执行事实（陈述实测，不代替实现方决策）

1. b01 已从 6.912e12 改善到 5.904e12（judge 确认），这是真实改进，应保留。
2. b12 当前仍 9.83078e16；直接调度 + judge 已证明 `P=8 custom-prio fill=1` 可达
   **8.38435e16（−14.7%）**，当前没有任何搜索路径产生它。
3. 预算被 `configs[0]` 的 102 个窗口吃光是两版共同现象；b01 因为 `configs[0].P==1` 而受益，
   b12 因 `P != 1` 完全没触发扩展分支。
4. `stderr` 无搜索日志（`log=None`）：线上/官方调用无法复盘搜索轨迹。

---

## 7. t1 报告逐条更正

| t1 结论 | 状态 | 更正 |
|---|---|---|
| 「b01/b12 当前与基线完全相同（b01 5.904e12 = 基线）」 | **错误** | t1 基线影子导入失效，实际加载工作区代码（§2）。真实基线 b01=**6.912e12**，当前=**5.904e12**（−14.58%），judge 确认。 |
| 「两版 b01 输出逐字节无差别」 | **错误** | 隔离后两份 b01 输出自第 72 行起不同（sha256 `418d0105…` vs `52c4bb55…`）。 |
| 「新调度部件在 b01 得 5.904e12 但没参与竞争 / 被预算挤掉」 | **错误** | b01 最终解就是扩展候选（`mode=gap-fill`）。 |
| 「b12 的扩展候选被 cost.est 挤掉」 | **错误** | b12 `configs[0].P=8`，扩展分支（`config.P == 1`）不触发。 |
| 「b12 的 P=1 候选 3.69e17 是潜在改进」 | **未证实/不相关** | P=1 对 b12 是更差网格（lb 3.06e17，实测 3.69e17）；现成改进是 P=8 custom+fill=1 = 8.38435e16。 |
| 「break→continue 零收益」 | **部分正确** | b01 上后续配置裸 lb 全更大且预算已尽；b12 上 `continue` 放行了 P=4，但时间不够；P=1/P=2/P=16 被 lb 剪属合法。 |
| t1 建议「剪枝键与 best.plan.P 对齐」 | **撤回** | `config.lb >= best.time` 剪枝合法；lb 可跨网格比较。 |
| 「六个官方样例 560/4880/6072/3200/416/1696」 | **维持** | t1 的官方样例用当前代码（未设 PYTHONPATH），不受基线问题影响。 |
| 「COMP/COMM 索引/依赖与 judge 一致；fill_gaps 只在 dur>0 且 comm_gap==0；零时长语义不变；judge fuzz 200 点全绿」 | **维持** | 基于当前代码，独立于基线问题（`runs/val-t1-20261029-2228/cmp-deps.json`、`judge-fill-fuzz.json`）。 |
| 「stderr 里有搜索日志」 | **更正** | `log=None`，stderr 只有末行 `[solve]`；搜索日志是本次用工具补采的。 |
| 「模型路由无法确认」 | **维持** | 本会话无可观测 provider/model 信息。 |

---

## 8. 文件索引

```
runs/val-t2-20261029-2233/
├── REPORT.md                           ← 本报告
├── iso-head/                           git archive HEAD solver → 完整 HEAD solver 包 + 复制的 .in/.out/.stderr
├── current/{b01-loose,b12-compute-bound}.{out,stderr,stdout}
├── judge/{current,iso-head}-{b01-loose,b12-compute-bound}.json
├── candidates/current-*.out            direct 候选输出（已交 judge）
├── logs/
│   ├── prod_files.txt / iso_head_files.txt            模块 __file__ 证据
│   ├── t1_shadow_repro.txt / t1_shadow_files.txt      t1 影子导入失效证据
│   ├── prod_feature.txt / iso_head_feature.txt        fill_gaps 存在性证据
│   ├── search_{current,isohead}-*.txt                 搜索轨迹（log 回调）
│   ├── trace_{current,isohead}-*.txt                  _try_config 进出/est/best 轨迹
│   ├── direct_{PROD,ISOHEAD}_*.txt                    直接调度矩阵
│   ├── cand_current-*.txt                             direct 候选的 judge 判定
│   └── sha256_outs.txt / md5_sources.txt              可复现哈希
├── tools/{show_files,dump_paths,search_log,trace_tryconfig,direct_p1,emit_candidate}.py
├── solver/                             （全仓 HEAD 快照的一部分，对照用）
└── 其余文件 = git archive HEAD 的全仓快照（只读对照）
```
