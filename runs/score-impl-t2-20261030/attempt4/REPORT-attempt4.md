# t2 attempt 4：回退我的失败增量 + 官方 50 例基线（小阶段）

* attempt_id：`f1c5f5fd-8f19-4544-a3f4-5b46472f4049`
* 范围：①精确回退我上一轮导致 b13 回退的探窗增量；②官方 50 例基线 + 诊断；③官方评分口径。

## 1. 回退（逐块 diff，非整文件覆盖）

方法：`runs/score-impl-t2-20261030/start-snapshot/solve.py` 是我这一轮改动的起点（已核 `SHA256SUMS`，
它自身包含此前所有来源的 gap-fill / 剪枝修复）。我按 4 个语义块逐一改回：

| 块 | 失败改动 | 回退为 |
| --- | --- | --- |
| 1 | `_PROBE_MAX_EVALS = 12` | `9` |
| 2 | 探窗时"只有可能改进 best 才核内存" | 每个候选都 `memory_usage`（起点写法） |
| 3 | early 分支"先大窗口 + 只扫 8 个变体 + `modes=("early",)`" | 起点的 `quick_windows` 路径 |
| 4 | `[扫窗·候选]` 调试打印 | 删除（减少无害开销） |

验证：`diff -u start-snapshot/solve.py solver/solve.py` **完全一致**（`IDENTICAL-TO-START-SNAPSHOT`）。
未使用 `git reset/checkout`，未整文件覆盖，未触碰其他来源的改动。
（注：我的起点快照本身是 86b4bc63…，而 attempt3 结束时工作区是 dc6be025…；二者差异正是上表 4 块。
start-snapshot 的 `SHA256SUMS` 此前由我写成安装版 6feda52d…，此处**如实标注**这一不一致。）

## 2. 官方评分口径（读官方包，不引用仓库 judge）

`official/extracted/Problem/`：
* `problem-statement.md` §5.3：Time 越小得分越高，按**相对成绩聚合排名**；并列先比求解器 CPU 时间，再比提交时间；
* `README.md`：每例 **10 s 墙钟**（求解器自身），超时记 `TO`；`run_all.py` 逐例调用 `grader.py` 得整数 `TIME` 或 `INVALID`；
* **官方 base（每例参照值）未随包提供**，包里只有 `report_python.txt` / `report_c.txt` 两份**样例解**的成绩。
  ⇒ 本报告只给**相对几何时间比**（vs 我方基线 / vs 样例解），**不称官方绝对分**。

## 3. 官方 50 例基线

命令：
```bash
PYTHONPATH=. python3 runs/score-impl-t2-20261030/scripts/official50.py --label base \
    --out runs/score-impl-t2-20261030/official50-base \
    --src runs/score-impl-t2-20261030/base-src        # = 回退后的 solver 全量副本（SHA256SUMS 有）
PYTHONPATH=. python3 runs/score-impl-t2-20261030/scripts/official50.py --label cur \
    --out runs/score-impl-t2-20261030/official50-cur
```
结果（`official50-base/result.json`、`official50-cur/result.json`）：

| 指标 | base（回退后） | cur（attempt3 结束时） |
| --- | ---: | ---: |
| 合法（grader 给整数 TIME） | **50/50** | 50/50 |
| 超时 TO | 0 | 0 |
| INVALID | 0 | 0 |
| 最大墙钟 | **7.32 s** | 7.42 s |
| 平均 TIME | 22 888 309.6 | 22 888 309.6 |
| 相对几何时间比 vs base | 1.000000 | 1.000000 |

* 两版 50 例 TIME **逐例相同** ⇒ 我的探窗增量在官方 50 例上**没有任何影响**，b13 回退只发生在电池用例上；
  回退不损失官方成绩，也不挽回任何官方成绩。
* 相对样例解（`report_python.txt`，**样例不是 base**）：几何均值 `time/sample = 0.7613`（50 例中所有 OK 的）。

## 4. 逐例诊断（`official50-diag.json`，按"调度浪费"排序）

每个用例给出 `ratio_lb = time/lb`、填充地板 `(nmb+V−1)/nmb`、以及
`excess = ratio_lb / fill_floor`（>1 表示**除填充之外**调度本身还有浪费）：

| 用例 | V | P | L | nmb | ratio_lb | 填充地板 | excess | 墙钟 |
| --- | --: | --: | --: | --: | ---: | ---: | ---: | ---: |
| x16_vl_trap4_ramp | 16 | 8 | 16 | 16 | 2.417 | 1.938 | **1.248** | 6.55 |
| x14_lr_twochunk_p15 | 10 | 3 | 60 | 6 | 3.007 | 2.500 | **1.203** | 7.06 |
| x11_lr_deep_p3 | 16 | 3 | 60 | 12 | 2.663 | 2.250 | **1.184** | 7.08 |
| x18_vl_tight_small | 8 | 8 | 8 | 8 | 2.109 | 1.875 | 1.125 | 1.21 |
| x10_lr_tight_p8 | 10 | 4 | 60 | 8 | 2.370 | 2.125 | 1.115 | 7.08 |
| x17_vl_tight_block | 15 | 8 | 15 | 32 | 1.585 | 1.438 | 1.103 | 7.09 |
| r64_v8_c8a | 16 | 4 | 16 | 32 | 1.617 | 1.469 | 1.101 | 7.11 |
| x19_vl_trap4_fs4 | 20 | 6 | 20 | 12 | 2.837 | 2.583 | 1.098 | 7.06 |
| x15_lr_twochunk_p10 | 8 | 5 | 48 | 10 | 1.865 | 1.700 | 1.097 | 7.06 |
| r64_v8_c8c | 15 | 4 | 15 | 64 | 1.330 | 1.219 | 1.091 | 5.45 |

* `excess > 1.02` 的有 **19/50**，`excess ≤ 1.0` 的也有 19/50；`ratio_lb` 中位数 1.322。
* **最重要的分布事实**：官方 50 例的 `nmb` 分布是 **6–64（7–64 区间）**，且 `L` 从 8 到 64 都有；
  电池 13 例的 `nmb` 只有 102/256/512/1000。⇒ 官方用例的**填充惩罚普遍更高**（地板 1.13–2.58），
  而我们的 V 选择几乎总是 `V = min(L,64,R/P)`，在这批用例上**不一定是 `(nmb+V−1)·seg` 的最优点**。
* **但必须注意**：这些大 `ratio_lb` 用例的 `excess` 只有 1.1–1.25，说明**主要差距是填充（V 太大）**，
  不是调度器崩了；缩小 V 会让 `seg` 变大，需要实测（`(nmb+V−1)·seg` 联合比较），
  不能因为 `nmb` 小就断言 V 小更好。
* 另有 6 例墙钟 7.0–7.1 s 逼近预算（x10–x19 这些 `L=48–64, nmb=6–12` 的实例），
  它们同时是"填充最大 + 预算最紧"的点 —— 若今后要加候选，先从这批开始，并且必须先用
  `auto_budget` 的余量验证不超 10 s。

## 5. 结论与建议（交 captain 决策）

1. **回退已完成且零损失**：官方 50 例 50/50 合法、TIME 逐例与 attempt3 完全相同，b13 回退只影响电池。
2. **官方基准不可得**：只有样例解成绩，任何"绝对分"都无法计算；后续报告请统一使用
   相对几何时间比 + 合法率 + 最差 `excess`。
3. **下一批最值得打的点**（按 `excess` 与预算余量）：x16 / x14 / x11 / x18 / x10；
   它们的共同点是 `L ≥ 16` 且 `nmb ≤ 16`（填充 1.88–2.50）。
4. 建议的下一步（**需 captain 批准后再做，且要单独成任务**）：
   * 小规模多 V 候选：对 `nmb ≤ 32` 的用例，把 `V ∈ {vmax, vmax/2, vmax/4}` 的真机时间与
     `(nmb+V−1)·seg` 预测对比，先离线验证"多 V 是否真的能降 Time"；
   * 负载非均匀切层：在 `psi_candidates` 里加入"按逐层时长做 DP 的折半切分"，同样先离线对拍；
   * 填隙优先级按关键路径加权：只作为 `fill_gaps` 的另一个排序键试，不改默认。
   三项都要求：改前/改后各 50 例、≥1 次重复、给出 `excess` 变化，不达标即弃。

## 6. 产物

```
runs/score-impl-t2-20261030/
├── attempt4/REPORT-attempt4.md        本报告
├── attempt4/{solve.W-round.py, W-vs-start.diff}   回退前的失败版本与差异（可复核）
├── base-src/                          回退后的 solver 全量副本 + SHA256SUMS（官方 50 例 base 跑的就是它）
├── official50-base/{result.json, maps/}   官方 50 例（回退后）逐例 TIME/状态/墙钟 + 映射
├── official50-cur/{result.json, maps/}    attempt3 结束时状态的官方 50 例
├── official50-diag.json               逐例 ratio_lb / 填充地板 / excess / vs_sample
└── scripts/{official50.py, official_diag.py, ab_b13.py, final_13.py, ...}
```
