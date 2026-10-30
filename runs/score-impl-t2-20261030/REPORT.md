# t2 交付报告：b13 窗口搜索（判定：**无可交付收益，净回退**）

* 作者：score-strategist，attempt 3，`attempt_id = 99ec0e72-79d5-49c1-b44d-4a86078392b6`
* 起点：`HEAD = b7a6a93` + 工作区上轮 gap-fill 改动；起点快照 `start-snapshot/`（见 `SHA256SUMS`）
* 结论：**本轮我引入的 b13 窗口搜索改动没有带来任何改善，b13 相对上一版生产代码是回退（+2.7%），
  因此不作为可交付候选**。13 例与官方 6 例全部合法，但评分没有任何提升。
  唯一站得住的收益仍是**上一版的 4.633e16**，它不是我这一轮的改动。

---

## 1. 真实评分函数（直接读代码，不引用 t1 文字）

| 项 | 位置 | 事实 |
| --- | --- | --- |
| 聚合公式 | `judge/service/ledger.py::geometric_score` | `score = round(exp(mean_i log(time_i / base_i)), 6)`；任一 case `ok=false`、`time` 非 int、`base` 缺省 ⇒ `None`；`time==0` ⇒ `0.0` |
| 排序方向 | `compute_versions` | `entries.sort(key=(score is None, score, created_at, run_id))`，`rank` 从 1 递增 ⇒ **score 越小越好**；`None` 排最后 |
| `base` 来源 | `judge/service/server.py::_load_bases` / `judge/cli.py::_bases` | **只**取 `cases/expected.json` 的 `time` 字段（唯一出处），当前为 `ex1 560 / ex2 4880 / ex3 7000 / ex4 3200 / ex5 416 / ex6 1696 / mini 164` |
| 官方题面 | `official/extracted/Problem/problem-statement.md` §5.3（新提供的官方包） | "the smaller Time is，the higher the score；test cases are aggregated into a ranking by **relative performance**；ties broken by solver CPU time, then submission time" |
| 官方限时 | 同上 / `Problem/README.md` | 每例 **10 s** 墙钟（评测器自身不计）；样例解法内预算 9 s |

数值核对（`score-direction.txt`）：官方 6 例在 `560/4880/6072/3200/416/1696` 下
`score = 0.976575`（ex3 比 base 7000 好，把几何均值拉到 1 以下）。
**注意**：仓库里的 `compute_versions` 只对**已登记 run 的 case 集合**做几何均值，
而官方是"按相对成绩聚合排名"——两者在"哪些 case 参与聚合"上不必相同，但方向一致（Time↓ ⇒ score↓）。

---

## 2. 改前 / 改后（b13，官方 judge 复核）

同一输入 `bigcases/battery/b13-balanced-compute.in`，子进程 + `python3 -m judge eval --json`：

| 变体 | 来源 | Time | lb | 网格 | ok | 内存峰值 | 墙钟 |
| --- | --- | ---: | ---: | --- | --- | ---: | ---: |
| **上一版生产（= A/B 的 base）** | `runs/score-impl-20261030/src-snapshots/prior` | **46 326 548 000 000 000** | 4.011e16 | V=8 P=64 | true | 6.7% | 6.0–6.2 s |
| **我改后（当前工作区）** | `solver/solve.py`（本轮） | **47 572 895 000 000 000** | 4.011e16 | V=8 P=64 | true | 5.1% | 6.0–6.2 s |
| t1 策略实验（把 `early` 窗口钉在 20） | `runs/score-strategy-20261030/b13_patch.py` | 47 572 895 000 000 000 | 4.011e16 | V=8 P=64 | true | 5.1% | ~6 s |

⇒ **我的改动 = 把"上一版"退回到"策略实验"的水平，净回退 +2.69%**。
原始数据：`final-b13-ab/ab.json`、`final-b13-ab/{prior,current}/b13.r0.out`、`final-b13-ab/{prior,current}/b13.r1.out`。
复现命令（本次实际执行的原文）：

```bash
cd /home/rainy/hackathon
PYTHONPATH=. python3 runs/score-impl-t2-20261030/scripts/ab_b13.py --reps 2 \
    --out runs/score-impl-t2-20261030/final-b13-ab
python3 -m judge eval --json bigcases/battery/b13-balanced-compute.in \
    runs/score-impl-t2-20261030/final-b13-ab/current/b13.r0.out
```

## 3. 13 个大用例 + 官方 6 例（当前工作区）

```bash
PYTHONPATH=. python3 runs/score-impl-t2-20261030/scripts/final_13.py --reps 1
python3 solver/solve_all.py --check --skip-selftests --out runs/score-impl-t2-20261030/final-official
```

* `final-13/result.json`：13/13 `ok=true`、`n_errors=0`；**`geomean_cur_over_base = 1.000000`**（同一份代码自比，
  见 §4 的说明）；最大墙钟 **7.93 s**（b11），全部 <10 s；内存最紧 b04 = 93.8%。
* `final-official/check.log`：`560 / 4880 / 6072 / 3200 / 416 / 1696`，judge 同值，"合法 是 / 10s 内 是 / 不劣于题面值 是"。

## 4. 失败点（如实）

1. **b13 回退 +2.69%**（§2）。根因：本轮的"探窗锚点按预算截断 + `early` 变体优先"把
   预算从 `W=102 的变体扫描`移走了。上一版在 `W=102/early` 的第 4 个变体上拿到 1.155×lb（4.633e16）；
   本轮探窗固定在 `W=20`，而 `W=20` 的 8 个变体最好只有 1.186×lb（4.757e16）。
2. **上一版的 4.633e16 是"预算 + 调用序"碰巧凑出来的，不稳**：`autobudget.jsonl` 实测，
   同一份上一版代码在 `--budget 7.0` 下 b13 给 **4.757e16**（= 回退值），8.0/8.4 下才是 4.633e16；
   三份历史产物（`runs/score-impl-20261030/v1probe`、`v2probe`、`b13-strategy-w20.out`）**全部是回退值 4.757e16**。
   ⇒ 交付时应把"b13 稳定拿到 4.633e16"当作**待验证目标**，而不是既成事实。
3. **b12 本身不稳**：默认预算下近几次是 3.69e17（P=1,V=64；lb=3.06e17），而更早的交付基线是 8.384e17。
   这一差别**发生在我的改动之前**（`probe-current/probe.json` 3 次重复一致为 3.69e17），属既有波动，
   但它意味着 A/B 判定至少要 3 次重复 + 同步记录内存。
4. **`sched.compact` 在大用例上不可用（既有缺陷，本轮确认）**：`_topological_order` 只把每个 mb 的 0 号节点入队，
   `disp` 永远入不了队 ⇒ 65k op 上直接 `RuntimeError: 依赖图存在环`。修好后实测仍是 **0.00% 改进**
   且 `peak_act` 160→816，所以本轮没有启用它。

## 5. 建议

1. **不要合入本轮 `solver/solve.py` 的探窗改动**；保留上一版（`src-snapshots/prior`）的 b13 行为 ——
   它在默认预算下一次就赢，且 13 例仍全部合法。
2. 若要让 b13 稳，应把"预算是否够扫到 `W=102/v4`"做成**显式条件**（例如对 `n_ops ≤ 120k` 的用例
   用固定 8.7 s 内预算，并把探窗锚点按"先大后小"），而不是靠探窗顺序碰运气 —— 这需要独立的一轮，
   并用 ≥3 次重复 + 固定预算的 A/B 判定。
3. 隐藏点保护（`v_candidates` / `_dominated_over(P)`）**没有证据支持**：官方 50 个 case 在
   `official/extracted/Problem/cases/`，下一轮应直接在它们上面跑（这才是隐藏分布的真样本），
   而不是用电池用例外推。

## 6. 文件索引

```
runs/score-impl-t2-20261030/
├── REPORT.md                    本报告
├── score-direction.txt          评分公式 + 方向 + base 来源的数值核对
├── start-snapshot/              起点快照（solve/sched/solve_all + selftests .out）+ SHA256SUMS(.installed)
├── t2-solve.diff / t2-solve_all.diff / t2-sched.diff   本轮工作区增量（相对 HEAD，含上轮 gap-fill）
├── final-13/{result.json, base/, cur/}   13 例 base vs cur（judge 复核）
├── final-b13-ab/{ab.json, prior/, current/}  b13 A/B，原始输出
├── final-official/check.log     官方 6 例 --check 结果
├── b13-ab/ , b13-probe/         过程中的 A/B 与单例调试日志（含 SOLVER_DEBUG_LOG 轨迹）
├── budget-cal/calibration.json  预算 vs 墙钟（证明上一版 4.633 依赖 8.7 s 预算）
├── probe-current/probe.json     当前代码 3 次重复（噪声评估）
└── scripts/                     ab_b13.py / final_13.py / scan.py / autobudget.py / b13_debug_variants.py
```
