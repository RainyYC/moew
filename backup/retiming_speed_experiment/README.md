# Retiming 评估器速度实验 D

本目录保留 local engine polish 评估器的验收候选、边界测试和说明。候选源码已纳入正式 `src/solver.cpp`，与其字节相同；提交给裁判仍只需该正式单文件。实验仅优化每个候选排序的 DAG retiming 计算；候选生成顺序、严格接受规则、memory 闭区间检查和输出语义保持不变。

## 实现与安全界

`polish` 准备阶段把二维 `dur[layer][op]` 展平成每节点 `node_duration`，避免候选评估时重复计算层号和操作号、再访问二维 duration 表。候选遍历通过一个泛型 `run_typed` 实现，wide 和 auto 共用同一套 Kahn 队列、拓扑更新、Time/secondary 比较、memory 合法性判定及候选生成逻辑。

默认 `auto` 在以下条件全部成立时使用 `int64` 时间数组和累计量，否则完整回退到现有 `i128` 计算：

1. 每个节点 duration 非负；累计正 duration 可安全表示。
2. 令 `T_bound = sum(所有节点的正 duration) + n`，其中 `n` 为节点数。无环路径最多经过 `n` 个节点，资源链每条边的额外 gap 至多为 1，因此任一路径时间不超过 `T_bound`。
3. `n * T_bound <= INT64_MAX`。每个节点结束时间不超过 `T_bound`，因此所有节点结束时间之和不超过 `n * T_bound`。
4. 当前 `best_time` 以及该次调用的 `best_secondary` 均非负且能由 `int64` 表示。

界限累计和乘法检查本身使用避免溢出的比较方式；若不能证明 64 位安全，不会截断或饱和时间，而是选择 i128 路径。64 位路径中 `time_limit` 在每次候选评估开始时转换为同类型；此时已证明可表示，且 `best_time` 在 polish 期间只会下降。memory 检查仍以 i128 时间事件和 i128 的 `U`、`Ua` 乘法执行，闭区间端点处理不变。

预计算是每次 `polish` 调用开始时的一次 O(J) 准备工作，其中 J 是节点数；候选搜索内部不重复展开 duration。准备阶段位于已有截止时间检查之后，后续候选遍历仍使用原有软截止检查。官方 50 例最大 J 为 76,800；这项准备开销不会改变现有搜索截止策略，也不声称为任意规模输入提供 10 秒硬保证。

## 诊断参数

- `--retime-mode=auto`：默认模式，满足上述安全界时走 64 位快路径，否则回退 i128。
- `--retime-mode=wide`：强制使用 i128，便于与 auto 对照。
- `--polish-pass-limit=N`：最多执行 N 个 extension pass；`0` 表示不限制（默认）。仅用于固定搜索 pass 数的诊断，原始 prefix 轮次及其逻辑保持不变。

这两个参数用于评估器数值路径与运行成本的对照，不改变候选邻域或接受标准。固定 pass 对照时可比较两种模式的完整输出和局部 polish 计数；常规运行无需指定参数。

## 固定 24-pass 对照

最终源码固定 pass 复核结果目录：

- [wide 结果](../../results/retiming_speed/equivalence/wide)
- [auto 结果](../../results/retiming_speed/equivalence/auto)
- [逐字比较记录](../../results/retiming_speed/equivalence/comparison.json)

最终源码的两组均使用 `--polish-pass-limit=24`，覆盖 `x01_lr_block_p2`、`x10_lr_tight_p8`、`x12_lr_close_p10`、`r128_v4_c4a`。四例输出逐字一致，官方 checker 均判合法。wide 平均墙钟 3.970926 秒，auto 平均 3.632690 秒；auto 平均快 8.517817%。这是固定搜索预算下的评估器运行时间对照，不能将其 Time 均值用于替代不限制 pass 的官方 full50 结果。

## 边界测试

独立测试源 [test_retiming.cpp](test_retiming.cpp) 通过宏重命名 solver 的 `main` 并直接调用 `local_engine_polish::polish`。它对 wide 与 auto 比较每个操作起始时间、Time、evaluated、accepted、tie_moves 和 strict_improve，并检查 DAG 依赖及两类 engine 资源不重叠。

三个 duration 分别覆盖：普通 64 位快路径；duration/路径 Time 可由 i64 表示、但 `n * B` 超出 i64 而回退；单节点 duration 本身超出 i64 而回退。复现命令：

```sh
g++ -std=c++17 -O2 -pipe -Wall -Wextra backup/retiming_speed_experiment/solver.cpp -o build/solver_retiming_speed
g++ -std=c++17 -O2 -pipe -Wall -Wextra backup/retiming_speed_experiment/test_retiming.cpp -o build/test_retiming_speed
build/test_retiming_speed
```

最终测试结果见 [boundary_test.txt](../../results/retiming_speed/equivalence/boundary_test.txt)：三例均通过，wide/auto 的所有对照值一致，每例 `evaluated=114`、`accepted=1`、`tie=0`、`strict=1`；Time 依次为 `70`、`700000000000000000`、`70000000000000000000`。

## 官方 50 例运行状态

全量指标目录为 [results/retiming_speed/full50](../../results/retiming_speed/full50)。运行已完成：50/50 全部通过，0 失败、0 超时；相对基线 3 例改善、47 例持平、0 例退步。Time 算术平均值为 20,366,017.76，基线为 20,368,250.60，平均逐例绝对改善 2,232.84，平均逐例相对改善 0.0099%。求解器平均墙钟 9.223027 秒，最长 9.234449 秒（`r64_v8_c16b`）。全量验证详情见目录内 `summary.tsv` 和 `validation.json`。最终源码的 24-pass wide/auto 逐字一致复核及数值边界测试均已完成，见上述 equivalence 目录。

## 可纳入正式报告的说明文字

### 10.1 数值计算的 64/128 位精确路径

候选重定时需要在 DAG 上反复计算最长路径及所有节点的结束时间总和。为了避免在每个候选上执行较宽整数运算，求解器先展平节点 duration，并用正 duration 总和、节点数和资源边最大 gap 构造路径上界 `T_bound`。只有当 `T_bound`、`n × T_bound`、当前 Time 与 secondary 比较值均可精确表示为有符号 64 位整数时，评估器才使用 64 位路径；任一条件无法证明时就完整采用 128 位路径。两条路径共用相同的拓扑传播和接受逻辑，内存检查及乘法仍使用 128 位整数。因此该优化只缩窄可证明安全的中间运算，不改变时间值或排程判定。

### 评估器诊断参数

`--retime-mode=auto` 默认启用安全的 64 位快路径，并在安全界不成立时自动回退到 128 位；`--retime-mode=wide` 强制使用 128 位，可用于逐项对照。`--polish-pass-limit=N` 限制 local polish 的 extension pass 数，`N=0` 表示不限制；它用于让不同数值路径在相同搜索 pass 数下进行诊断比较，不改变候选顺序或接受判据，也不影响原有 prefix 搜索。
