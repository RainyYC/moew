# 借鉴优化实验报告

本轮 `diff_v7` 默认结果见 [DIFF_REPORT.md](DIFF_REPORT.md)；下方保留 v6 实验历史与原始结果表。

本报告记录 v5 冻结版本之后的 A/B/C 实验。冻结源码、头文件、构建脚本、二进制及基准摘要副本位于 [borrow_v6/base](/home/rainy/hackathon/algorithm_v5/borrow_v6/base)；比较基准是其 50 案平均官方 Time **20,621,198.36**。所有新输出保存在 `results/borrow_v6_*`，没有覆盖旧的 `results/final/` 或历史比较表。

## 方法

- **A：细窗口搜索。** 在 nmb≤64 时扫描窗口 W=1..nmb，使用 mode 0 和自动/全 b=1 两种通信缓冲策略；较大的 nmb 使用固定窗口邻域。分别从 probe 布局和完整 v5 深搜结果生成候选，只有调度器计算的 Time 严格更低才替换，最终输出再由官方 grader 验收。
- **B：前向填充 boost。** 使用事件调度 mode 3。实验包括奖励比率 0、0.5、1、2、5、10 倍，`fill_groups` 取 1、2、G/2、G，`fill_mbs` 取 nmb/4、nmb/2、nmb；另测 flat reward。B 不进入默认模式。
- **C：重复负载分组。** 对符合支持范围（至多 4 种负载值、P≤32、每 rank 容量≤32）的层搜索等容量分组，并按原专家索引回填。新 MAP 作为独立候选，从完整 v5 结果出发；当前负载峰值必须下降，最终实际调度 Time 也必须严格更低才替换。
- **AC 默认：** A、C 都各自从完整 v5 incumbent 出发；C 候选也会额外跑细窗口搜索。保留 v5 解，所有变体仅在 Time 严格更小时采用。

## 消融结果

| Variant | 50 案官方验收 | 平均 Time | 相对冻结 v5 | 改善 / 持平 / 回退 | 最慢求解耗时 |
|---|---:|---:|---:|---:|---:|
| A，`borrow_v6_a2` | 50/50 | 20,615,054.04 | 几何平均 1.000945× | 10 / 40 / 0 | 3.663 s |
| B，mode 3 targeted grid | 3/3 | — | 目标三案均未改善 | 0 / 3 / 0 | 0.237 s |
| C，`borrow_v6_c2` | 50/50 | 20,620,836.76 | 几何平均 1.000014× | 2 / 48 / 0 | 2.225 s |
| AC，默认，`borrow_v6_default` | 50/50 | **20,614,692.44** | **几何平均 1.000960×** | **12 / 38 / 0** | **3.521 s** |

AC 相对单独 A 多改善 2 案，48 案与 A 持平，没有回退；相对单独 C 多改善 10 案，40 案持平，没有回退。A 的主要收益是 `x17_vl_tight_block` 从 6,055,940 降到 6,010,628、`x20_vl_flat_control` 从 2,443,667 降到 2,407,088。C 在 `r256_v8_c8a` 将负载峰值 m 从 240 降到 224，端到端 Time 从 29,258,410 降到 29,243,050；该例仍以通信为主，故 Time 收益较小。

Mode 3 在目标案例的最佳配置仍劣于 v5 incumbent：

| Case | 最佳配置（G, M, ratio, flat, buffer） | Mode 3 Time | v5 Time |
|---|---|---:|---:|
| x16_vl_trap4_ramp | (1, 8, 5, false, b=1) | 4,858,066 | 4,274,914 |
| x18_vl_tight_small | (1, 4, 0.5, false, b=0) | 2,062,604 | 1,792,964 |
| x19_vl_trap4_fs4 | (10, 12, 0.5, false, b=0) | 9,631,971 | 7,697,697 |

上表的 Mode 3 Time 来自调度器诊断日志，并未将这些较差的内部候选逐份输出、调用官方 grader。三个定向实验最终保留的是原有较优时间表，这三份实际输出均通过官方 grader。初轮较窄的 B 参数扫描曾覆盖完整 50 例，结果也没有改善，记录位于 `results/borrow_v6_b/`；扩展参数网格只复查上述三个案例，不代表已经穷尽所有前向填充策略。默认模式不启用 B。

## 最终默认验收

最终通过率为 **50/50**，求解耗时范围 **0.021–3.521 秒/案**（包含输出，不含 grader），每例限时 10 秒。`Time` 范围为 **1,792,964–106,581,594**。本数据没有官方最优值，以上改进只相对冻结 solver 快照，不代表最优性或排名。

实际默认入口已设置为 `--borrow=ac`；显式 `--borrow=none` 重现冻结 v5 时间。构建与重跑默认 50 案：

```sh
cd /home/rainy/hackathon/algorithm_v5
./build.sh
./run_acceptance.sh
```

默认逐案结果、输出和日志在 `results/borrow_v6_default/`。A、C 消融摘要分别在 `results/borrow_v6_a2/summary.tsv`、`results/borrow_v6_c2/summary.tsv`；B-grid 输入输出与摘要在 `results/borrow_v6_boost_grid/`。

逐例 v5 / AC 对照：[`results/comparison_v6.tsv`](results/comparison_v6.tsv)。
