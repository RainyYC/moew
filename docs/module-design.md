# 模块结构与构建方式

交互说明见[开发视图](../.archify/architecture-suite-20261031-030904/development/index.html)和[完整 4+1 视图说明](architecture-4-plus-1.md)。开发视图按职责分解模块；运行调用关系另见[整体架构](../.archify/architecture-suite-20261031-030904/architecture/index.html)。

维护代码按职责拆分为多个 `.hpp` 接口/值类型和 `.cpp` 实现文件。日常构建按多个翻译单元编译并链接；全局 `main` 仅在 `src/solver.cpp`，搜索阶段的流程编排由 `src/app/solver.cpp` 中的 `Solver::solve` 负责。`solver::run` 负责计时起点、参数解析、输入读取、错误处理和输出。`make submission` 仍可选地导出自包含的单文件裁判提交件，但它不是日常构建入口。

## 文件职责与依赖

```text
solver.cpp → app/solver.hpp
app/solver.cpp → io/input|options|output.hpp + search 阶段接口头
io/*.cpp → 对应 io/*.hpp + model/problem.hpp（按功能）
placement/*.cpp → placement/*.hpp + model/io/search 接口头（按功能）
scheduling/*.cpp → 自身接口头 + scheduling/schedule_api.hpp + common.hpp + core/operation_graph.hpp
search/*.cpp → 自身接口头 + 所需的 placement/scheduling/io/search 接口头
model/*.hpp → 独立的数据值类型
```

这里表示实际实现文件对接口/模型头文件的依赖类别，不表示所有同目录文件互相依赖。实现逻辑位于 `.cpp`；模型值对象不包含调度或搜索内核实现，`app/solver.hpp` 声明 `solver::run` 和 `solver::Solver` 门面。

| 文件 | 职责 |
|---|---|
| `src/common.hpp`, `src/core/operation_graph.hpp` | 标准依赖、operation 协议定义，以及 inline 节点编码和共享 DAG 边模板。 |
| `src/model/problem.hpp`, `src/model/scheduled_operation.hpp` | 仅含数据模型与 operation 值类型；不依赖调度内核实现。 |
| `src/io/*.hpp/.cpp` | 数值格式化/解析、输入、命令行选项与输出，各由同名 `.cpp` 提供实现。 |
| `src/placement/expert_mapping.hpp/.cpp` | 专家到 rank 的映射和按 operation 计算 duration 的 cost model。 |
| `src/placement/grouped_placement.hpp/.cpp` | 按 slot weight 分组的有界 placement 搜索及方案展开。 |
| `src/scheduling/schedule_api.hpp` | 非拥有的调度问题视图、事件/列表配置、输出视图及编译期 `Scheduler<Strategy>` 调用约定。 |
| `src/scheduling/event_scheduler.hpp/.cpp` | event driven DAG 内核、ready priority 与资源/激活区间约束；`EventScheduleStrategy` 将具名配置适配到原内核。 |
| `src/scheduling/list_scheduler.hpp/.cpp` | list scheduler 内核、稳定 variant 顺序及 wave/gap 参数；`ListScheduleStrategy` 将具名配置适配到原内核。 |
| `src/search/limits.hpp` | 搜索预算、deadline、数值分母和无穷大哨兵。 |
| `src/search/candidate_search`, `layout_search`, `initial_search` (`.hpp/.cpp`) | 初始分区候选、布局评估和 incumbent 选择。 |
| `src/search/window_search`, `window_borrow`, `boost_search`, `placement_search` (`.hpp/.cpp`) | 窗口、借用、forward-fill 与替代 placement 搜索。 |
| `src/search/list_search`, `wave_search` (`.hpp/.cpp`) | list 与 wave 阶段策略。 |
| `src/search/local_engine_polish`, `polish_driver` (`.hpp/.cpp`) | 局部 polish 内核及其预算/阶段编排。 |
| `src/app/solver.hpp/.cpp` | `solver::run` 处理解析、输入、错误和输出边界；`Solver::solve` 按原顺序编排搜索阶段。 |
| `src/solver.cpp` | 只定义全局 `main` 并调用 `solver::run`。 |
| `src/sources.mk` | 构建和 amalgamate 共用的唯一 `.cpp` 源文件清单及编译顺序。 |

各头文件保留自己实际使用的本地依赖。共享数据仍用简单 `struct` 表达，例如 `InputData`、`Candidate`、`ScheduleResult` 和 `solver::ScheduledOperation`。事件调度与列表调度通过 `ProblemView`、独立配置值和 `ScheduleOutput` 传参；`Scheduler<Strategy>` 以模板参数注入静态策略，具体策略在完整调度边界适配既有内核，不用虚调用、运行期多态或逐 operation 转换。list/wave 搜索直接复用共享 operation 类型；`list_search` 在现有 makespan 条件通过后再做安全检查，`wave_search` 保持自己的原有安全检查顺序。`Solver::solve` 是搜索流程门面，`run` 保留计时起点、解析、输入、异常和输出职责。每个 `.cpp` 单独编译为对象文件，头文件主要提供声明、模板、常量和少量 inline 实现。`make` 使用 C++17、`-O2` 与 `-flto`，让链接器优化跨翻译单元调用。有持久状态和递归搜索过程的 grouped placement 搜索封装在 `grouped_placement::detail::Search`：状态为私有成员，外部通过 `solve()` 和 `take_solution()` 取得结果。无状态算法保持具名函数，避免多余对象层级。更详细的参与者与扩展约定见[设计模式说明](design-patterns.md)。

`make -j2 build` 按 `src/sources.mk` 编译对象文件并生成依赖文件，支持增量重编译。该清单同时供单文件导出器使用，避免构建与导出遗漏或顺序不一致。当前构建共含 21 个 `.cpp` 和 26 个 `.hpp`。固定工作量记录见[配对验证](../results/design_patterns/fixed_work/validation.json)，命令行模式等价记录见[模式验证](../results/design_patterns/cli_modes/validation.json)，官方 full50 记录见[设计模式验收说明](../results/design_patterns/README.md)。

## Operation 编号

`operation::Code` 使用协议规定的整数值，因为 operation 数组、节点编号和输出顺序都以该值为索引。算法代码应使用语义名；`operation::kCount` 是 operation 维度长度。

| 索引 | 枚举名 | 协议名 |
|---:|---|---|
| 0 | `kSharedForward` | `s` |
| 1 | `kDispatchForward` | `disp` |
| 2 | `kExpertForward` | `gemm` |
| 3 | `kCombineForward` | `comb` |
| 4 | `kSharedBackward` | `s_bwd` |
| 5 | `kCombineBackward` | `comb_bwd` |
| 6 | `kExpertInputGradient` | `gemm_dx` |
| 7 | `kExpertWeightGradient` | `gemm_dw` |
| 8 | `kDispatchBackward` | `disp_bwd` |
| 9 | `kSharedWeightGradient` | `s_dw` |

duration 数组按这些名字逐槽赋值；序列化名字表则按同一协议索引顺序排列，并在代码处注明这一对应关系。

## DAG 边与确定性

`operation_graph::append_layer_edges` 是三个 scheduler/搜索图构造路径共享的每层边来源。每层内部按这个顺序添加边：

1. `disp → gemm`
2. `gemm → comb`
3. `s → comb`
4. `comb → s_bwd`
5. `comb → comb_bwd`
6. `comb_bwd → gemm_dx`
7. `comb_bwd → gemm_dw`
8. `comb_bwd → s_dw`
9. `gemm_dx → disp_bwd`
10. `s_bwd → disp_bwd`

之后，若存在前一层，依次添加 `previous comb → current s`、`previous comb → current disp`；若存在后一层，依次添加 `next disp_bwd → current s_bwd`、`next disp_bwd → current comb_bwd`。调用方仍按 microbatch 外层、layer 内层遍历。

边容器是有序 vector，ready queue 的比较规则还会用 node id 和其他字段打破平局。边插入顺序会影响 predecessor/successor 遍历以及同优先级候选的处理次序，所以集中边定义时保留原逐边顺序，不排序、不去重，也不把不同 scheduler policy 合并。

## 常量命名与保留

具有领域含义或控制预算的常量使用具名枚举/常量：operation 和 engine 编号、通信 operation 集合、搜索 deadline 与迭代上限、节点/窗口门槛、百万/万亿分母、placement 搜索预算及 `i128` 无穷大哨兵分别表达用途和单位。数值与检查顺序保持原样；例如 polish prefix 的 3000 是每轮最大 evaluation 数，不是毫秒，额外 layout 的 `mb ≤ 16` 和节点上限 8000 也与 wave 的实际运行 deadline 分别命名。

以下字面值仍保留是因为它们直接表达局部数学或枚举，而不是隐含的 operation 编号：

- `io/numeric.cpp` 中十进制数字解析/格式化使用的 `10` 是数制基数；`ceil_div` 仍是 `numeric.hpp` 中的小型 inline 数值函数。
- 成本前缀中的 `4 * com + 2 * g + 2 * s` 及若干 `2 * ceil_div(...)` 表示公式内固定出现次数；比把每个系数抽成独立常量更直接。
- `0`、`1` 常用于 bool/状态初始化、空容器和循环边界；只有承担固定语义的 event kind、engine 与 operation 值才另起名字。
- list、wave、boost 和窗口搜索中的候选序列（例如比例 `{5, 10, 20, 50, 100}`、优先级/变体索引、窗口宽度及有理数 pitch 列表）是有顺序的启发式枚举。保留原列表和值可避免改变遍历/tie 顺序；它们不是通用单位或领域状态。
- grouped placement 的 `StateHash` 保留 `0x9e3779b97f4a7c15ULL` 以及 `<< 6`、`>> 2` 的 hash-combine 混合式。它们只用于哈希桶混合；保留实现可避免因哈希遍历次序变化而影响有界搜索中的访问顺序。

## 导出单文件

日常构建使用 `make -j2 build` 编译多翻译单元。若裁判环境要求单源文件，可运行 `make submission`；`scripts/amalgamate.py` 按 `src/sources.mk` 顺序展开实现文件及本地 include，保留标准库 include，为模块添加 begin/end 注释并去除 `#pragma once`。展开范围限制在 `src/` 内；缺失、越界、宏形式或无法解析的 include 会明确报错。该导出件是另一种源文件打包形式，不承诺与多翻译单元构建的二进制逐字节相同。

导出结果是确定性的，不写时间戳。`make submission-check` 会比较现有 `submission/solver.cpp` 与当前展开结果；最终文件可按独立 C++17 源文件编译。

设计模式候选的固定工作量共运行 24 次，均通过官方 grader；12 组配对运行的 stdout 与非时间搜索计数一致。CPU 对照数据与解释见[设计模式验收说明](../results/design_patterns/README.md)，不据此推断稳定加速。当前多翻译单元构建与当前版本的单文件导出使用相同模块源码，但二进制不要求逐字节相同；完整记录也见该说明。

未修改的官方 `run_all.py` 全 50 例为 50/50 合法、0 超时，平均 Time 20,369,802.98，平均墙钟 9.19928 秒，最长 9.225 秒（`r256_v8_c4`、`r64_v8_c8g`）。逐例结果和完整统计见[设计模式验收说明](../results/design_patterns/README.md)。默认截止预算下，搜索迭代数与 Time 会波动，不保证逐次分数相同。
