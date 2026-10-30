# 重定时加速实验记录

## 结论

以 `results/budget_search/full50/summary.tsv` 为逐例基线，D 加速版在完整 50 例中全部通过校验、没有超时：3 例 checker time 下降、47 例持平、0 例退步。总体平均 checker time 从 20,368,250.60 降至 20,366,017.76，平均每例减少 2,232.84；按逐例相对改善率取算术平均为 0.009884%。这是一项幅度很小、集中在 3 例的改进，更多的搜索评估没有让所有用例变好。

## 比较口径

- **基线**：`results/budget_search/full50/summary.tsv`，即此前完整 50 例预算搜索候选，不是更早的 `runner_input_fix` 结果。基线本身 50/50 有效、无超时。
- **候选**：`results/retiming_speed/full50/summary.tsv`，完整 50 例；验证记录在同目录的 `validation.json`。
- **收益符号**：`基线 checker time - 候选 checker time`；正数表示候选更快。checker time 是主要成绩指标，wall time 单列描述运行成本。
- 两种总体相对均值可能略有不同：逐例相对改善率的算术平均是 **0.009884%**；用两组平均 checker time 计算的相对降幅是 **0.01096%**。前者对每个案例等权，后者反映平均分数之差。

## 三个改善用例

| 用例 | 基线 checker time | D checker time | checker time 降幅 | 逐例改善率 |
|---|---:|---:|---:|---:|
| `r24_p3_flat` | 22,118,310 | 22,058,128 | 60,182 | 0.272091% |
| `x09_lr_skew_p6` | 17,164,896 | 17,147,936 | 16,960 | 0.098806% |
| `x12_lr_close_p10` | 27,980,136 | 27,945,636 | 34,500 | 0.123302% |

其余 47 例与基线 checker time 完全相同；没有退步用例。50 例逐行结果见候选 `summary.tsv`，全量有效、失败与超时统计见 `validation.json`。

## 运行时间与评估数量

| 指标 | budget_search 基线 | D 加速版 |
|---|---:|---:|
| 平均 solver wall time | 9.2209 秒 | 9.2230 秒 |
| 最长 solver wall time | 9.2337 秒 | 9.2344 秒 |
| 扩展阶段 `extension_evaluated` 总数 | 6,753,234 | 8,250,476 |
| 每例扩展评估均值 | 135,064.68 | 165,009.52 |

D 每例扩展阶段评估次数增加约 22.17%（总计增加 1,497,242 次），平均 wall time 基本相同。评估数量是搜索过程指标，不等于目标值改善：50 例中仍有 47 例持平。

## 输出结构与数值等价检查

对 baseline 与 D 的 50 个 `.out` 文件逐一比较，`SCHEDULE` 标记之前的字节内容在 **50/50** 用例中相同；本实验只改变排程正文，没有改变前置布局。

另有固定 24 个扩展 pass 的 `auto` 与 `wide` 对照，产物位于 `equivalence/auto/` 和 `equivalence/wide/`。四个案例均通过有效性校验，`equivalence/comparison.json` 记录它们的输出逐字节相同。该截断运行中 auto 平均用时 3.632689618 秒，wide 为 3.970925859 秒，auto 快 8.517817%。这组固定 pass 诊断相对完整基线有 checker time 退步，是主动在 24 pass 截止搜索的结果；它用于比较两种重定时实现，不代表默认完整预算版的退步，默认版全 50 例结果见上表。

边界测试 `equivalence/boundary_test.txt` 覆盖时长 `10`、`1e17`、`1e19`，三档均通过，结果包含对应 Time 与节点起始时间。边界和模式等价检查不替代官方全量成绩。

`full50/official_smoke.txt` 记录三例官方 smoke 全部通过：`r128_v4_c4a`、`r256_v8_c4`、`x01_lr_block_p2` 均为 OK，solver wall time 分别为 9.205、9.225、9.180 秒（TIME valid 3/3）。

## A、B、C 邻域实验未推广

这些实验及其四例 pilot 的完整记录见 [search_neighborhood/pilot_summary.md](../search_neighborhood/pilot_summary.md)。样本为 4 例，只能用于排查搜索方向，不能替代完整 50 例比较：

- **A 多关键点**和 **A hybrid**：各自四例中 1 改善、2 持平、1 退步；`x12_lr_close_p10` 退步，hybrid 的四例平均 checker time 也高于基线。
- **B 联合资源交换**：四例中 1 改善、2 持平、1 退步，同样在 `x12_lr_close_p10` 退步。
- **C 受限逃逸**：四例中 1 改善、3 持平、0 退步；只有 `x10_lr_tight_p8` 改善 12,742（0.0674%）。小样本下这点收益不足以支持推广；`x12_lr_close_p10` 的最好结果由正常搜索 pass 找到，escape episode 没有触发。

D 采用的是重定时评估加速，继续使用完整 DAG 与内存合法性判定，并保留 128 位回退；A/B/C 是改变候选邻域的搜索实验，结果没有显示足够稳定的完整集合收益，因此没有合并进本次正式版本。
