# diff_v7 默认优化报告

本轮在完整 AC incumbent 后增加 gap-fill 候选、group 0 的 `s_bwd` 完成释放窗口和离线列表调度候选。每个新结果只有在实际 Time 严格更低时才替换 incumbent；官方 grader 检查最终输出。旧 AC 与冻结 v5 都可按下文命令回放。

## 50 案结果

`results/diff_v7_default/summary.tsv` 是全 50 案官方验收记录，`comparison.tsv` 按案列出新默认、AC 与旧 placement 的 Time。旧 placement 列取自 `results/comparison_history.tsv` 的 `placement_fillboost_time`，没有把 `data/official/official50-placement-decoupled.txt` 的第二列当作基线。

| 对照 | 对照平均 Time | 新默认平均 Time | 改善 / 持平 / 回退 | 总 Time 减少 |
|---|---:|---:|---:|---:|
| AC 默认 `borrow_v6_default` | 20,614,692.44 | 20,589,369.80 | 14 / 36 / 0 | 1,266,132 |
| 旧 placement `placement_fillboost_time` | 21,741,076.58 | 20,589,369.80 | 41 / 9 / 0 | 57,585,339 |

全 50 案均通过官方 grader。单案 solver wall time 为 0.124–8.052 秒，低于 10 秒限制；官方 Time 范围为 1,724,136–106,581,594。AC 对照的平均降幅为 25,322.64（约 0.12284%）。原 8 个退步案例累计改善 957,854，全部回到旧 placement 成绩或更好。

## 8 个重点案例

| Case | 旧 placement | AC | 新默认 | 相对 AC 变化 | 主要来源 |
|---|---:|---:|---:|---:|---|
| r64_v4_c4e | 36,876,336 | 36,913,632 | 36,876,336 | -37,296 | wave priority + gap-fill 复现旧成绩 |
| r64_v8_c16a | 6,278,640 | 6,473,240 | 6,278,640 | -194,600 | 离线列表 + forward boost |
| r64_v8_c8a | 5,142,294 | 5,282,831 | 5,142,294 | -140,537 | 离线列表 + forward boost |
| r64_v8_c8c | 7,130,360 | 7,157,902 | 7,051,060 | -106,842 | 窗口释放 |
| r64_v8_c8d | 5,239,340 | 5,325,485 | 5,239,340 | -86,145 | wave priority + gap-fill 复现旧成绩 |
| x16_vl_trap4_ramp | 4,117,136 | 4,274,914 | 4,073,166 | -201,748 | 扩展列表搜索 |
| x17_vl_tight_block | 5,888,770 | 6,010,628 | 5,888,770 | -121,858 | early variant 4 |
| x18_vl_tight_small | 1,724,136 | 1,792,964 | 1,724,136 | -68,828 | 离线列表 + forward boost |

这里 c4e/c8d 的恢复来自 wave priority 与 gap-fill 复现旧成绩，不是 W=33 窗口释放。窗口释放主要改善 c8c；其他重点收益来自离线列表排序和 forward boost。

## 调度筛选

离线列表候选先构造完整十类 operation schedule，再做逐 group 内存核验。通信 buffer 只统计正时长通信操作；相同结束和开始时间计为两个 buffer。Activation 从 `comb` 结束到 `s_bwd` 开始按闭区间计数，同一时刻先计入新 activation，再释放旧 activation。候选只有在内存核验通过且 Time 严格更低时才替换当前结果。

`diff_v7_default/SHA256SUMS` 记录用于验收的源码、二进制和比较表哈希。

## 复现

```sh
cd /home/rainy/hackathon/algorithm_v5
./build.sh
./run_acceptance.sh
```

默认 `--diff=auto` 只在非 baseline 的 `--borrow=ac` 模式启用本轮优化。用 `./solver --borrow=ac --diff=off < input.txt` 可复现旧 AC；用 `./solver --borrow=none < input.txt` 可回放冻结 v5。验收脚本还接受结果目录、borrow 模式、diff 模式和可选 case 正则表达式四个参数。
