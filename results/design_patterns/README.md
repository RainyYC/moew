# 设计模式与命令行整理验收（2026-10-31）

## 改动与验收边界

当前源码引入参数对象、编译期调度策略、内核适配器与 `Solver::solve` 门面。事件/列表调度内核、候选顺序、DAG 边、整数公式与截止条件保持一致；共享操作类型免去列表结果的逐项转换。命令行只公开 `--mode`、`--force-p`、`--retime-mode`、`--polish-pass-limit`、`--help` 五个选项。默认使用完整搜索，局部扩展累计预算固定 9200 毫秒。

最终验收直接执行原样的官方程序：

```sh
python3 -u data/official/Problem/run_all.py --cmd './build/solver' --timeout 10
```

`run_all.py` 与 `grader.py` 均未修改，前后 SHA256 一致，记录见 [command.json](command.json)。本目录的 TSV/JSON 是对官方原始文本的整理，没有替代官方判定，也没有筛选重跑中的较好成绩。正式成绩原文见 [official-run-all.txt](official-run-all.txt)。

## 官方 50 例

| 指标 | 本轮结果 |
|---|---:|
| 合法 / 用例数 | 50 / 50 |
| 超时 / 失败 | 0 / 0 |
| 平均 Time | 20,369,802.98 |
| 中位 Time | 14,212,582 |
| 最小 / 最大 Time | 1,724,136 / 106,105,860 |
| 平均求解 CPU（由报告逐行值计算） | 9.19714 秒 |
| 平均墙钟（由报告逐行值计算） | 9.19928 秒 |
| 最长墙钟 | 9.225 秒 |

官方文本的 CPU、墙钟逐行值仅保留三位小数，因此上述均值是对已舍入数值的汇总。最长两例为 `r256_v8_c4` 和 `r64_v8_c8g`。逐例数据见 [full50/summary.tsv](full50/summary.tsv)，汇总见 [full50/validation.json](full50/validation.json)。Time 是调度目标，越低越好；CPU 与墙钟是求解程序的运行耗时。

官方 Python 样例报告的平均 Time 为 31,765,363.04。本轮相对该均值下降 35.87%，逐例降幅的算术平均为 31.13%。样例答案不是最优性证明。

## 固定工作量与接口验证

以保留的修改前二进制为基线，在 6 例上按正反执行顺序各重复一次，共 24 次求解。使用 `--polish-pass-limit=24`，所有结果通过官方 grader；12 组配对 stdout 和去除耗时字段后的搜索计数完全相同。

- 基线平均 CPU：4.12776975 秒。
- 当前平均 CPU：4.10955750 秒。
- 差异：−0.4412%。这是本次样本的结果，未见明显性能退步，不宣称稳定加速。

详细记录见 [fixed_work/validation.json](fixed_work/validation.json)。命令为：

```sh
python3 scripts/validate_multi_tu.py --baseline build/solver_before_design_patterns --candidate build/solver --output-dir results/design_patterns/fixed_work
```

另外在 `x18_vl_tight_small`、`x01_lr_block_p2` 上，比较四种模式在基线、当前多文件 LTO 和当前单文件 O2 构建中的输出，共 24 次运行，全部官方有效且逐字节一致。新模式 full/list/event/serial 分别对应原无参数、`--scale=off`、`--diff=off`、`--baseline`。测试还覆盖文件位置、stdin、`-`、保持 stdin 打开时 `--help` 及时退出，以及已删除选项、非法数字和未知参数必须报错。记录见 [cli_modes/validation.json](cli_modes/validation.json)。

多文件构建与独立单 CPP 编译均成功，6 个改动接口头可独立编译，策略注入示例及参数解析检查通过。正式目录重建所得二进制与已配对测试的独立候选二进制 SHA256 相同。导出新鲜度见 [submission-check.log](submission-check.log)。

## 默认截止时间的波动复核

与先前冻结批次比较，本轮 46 例持平、4 例 Time 较高，平均 Time 从 20,365,419.20 到 20,369,802.98。没有用较好的历史答案替换本轮输出。为检查差异，用保留的基线二进制在相同机器上，通过未改官方 runner 单独复核这 4 例：

| 用例 | 冻结基线 Time | 当前正式批次 Time | 原二进制同机复核 Time |
|---|---:|---:|---:|
| r24_p3_flat | 22,031,278 | 22,138,186 | 22,138,998 |
| x09_lr_skew_p6 | 17,147,936 | 17,164,896 | 17,164,896 |
| x10_lr_tight_p8 | 18,903,491 | 18,911,563 | 18,911,563 |
| x12_lr_close_p10 | 27,942,558 | 28,029,807 | 28,031,385 |

同机复核中当前程序 2 例持平、2 例略低，原二进制也未复现此前冻结分数。该结果与时间截止导致迭代次数变化的现象一致；结合固定工作量完全一致的证据，目前未发现此次结构改造造成质量或运行性能退步的证据。它不保证每次默认运行得到相同 Time。

复核原文见 [baseline_recheck/official-run-all.txt](baseline_recheck/official-run-all.txt)，数据见 [baseline_recheck/validation.json](baseline_recheck/validation.json)。复核只作诊断，不改变正式 50 例表。

## 可复核材料

- [设计模式说明](../../docs/design-patterns.md)：参与者、类关系与扩展方法。
- [当前完整报告](../../docs/reports/current-solver-report.md)：算法、运行方式及第 13 章官方逐例对照。
- [构建与运行身份](command.json)、[源文件清单](SOURCE_SHA256SUMS)、[本地完整材料清单](SHA256SUMS)。
- [修改前快照](../../backup/before-design-patterns/ARCHIVE.md)：源码、提交件、配置与文档，文件摘要在 snapshot.json 中。

性能验证及官方全量验收期间，独立长时间优化实验暂停，求解器串行运行。完成后该实验恢复；其搜索结果未混入本次验收。
