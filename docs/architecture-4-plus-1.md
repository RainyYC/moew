# 当前求解器的 4+1 架构视图

[打开浅色交互图集](../.archify/architecture-suite-20261031-030904/index.html)。图集包含更新后的整体架构、算法流水线，以及下面五张视图；所有源码引用固定到提交 `e18822f8a3e1f91ea4227d0ffd4138d444c7c829`。

**4+1 是观察同一系统的五个角度。**逻辑视图解释领域概念与功能，开发视图解释源码模块与构建，进程视图解释运行时协作，物理视图解释程序与数据的部署位置；“+1”场景视图用具体用例检查前四个视图是否共同解释了程序行为。它们不表示五套不同算法，也不要求系统必须采用分布式部署。

| 视图 | 读者关心的问题 | 当前系统的回答 |
|---|---|---|
| [逻辑视图](../.archify/architecture-suite-20261031-030904/logical/index.html) | 一个候选怎样成为可行答案？ | 输入确定候选布局和专家映射，时长模型与 DAG 描述操作；资源和内存约束筛选可行调度，最大结束时间决定 Time。 |
| [开发视图](../.archify/architecture-suite-20261031-030904/development/index.html) | 哪些模块承担哪些职责，怎样编译交付？ | `app`、`io`、`model/core`、`placement`、`scheduling`、`search` 按职责协作；共享源清单支持多文件编译和可选单文件导出。 |
| [进程视图](../.archify/architecture-suite-20261031-030904/process/index.html) | 谁调用谁，哪里等待，哪里存在进程边界？ | 求解器内部同步、串行调用搜索与调度；官方 runner 逐例启动求解进程，结束后才启动 grader。 |
| [物理视图](../.archify/architecture-suite-20261031-030904/deployment/index.html) | 可执行文件与题目、答案放在哪里？ | 本机 CPU 执行 C++ 求解器及 Python 验收程序；题目文件与临时答案文件位于本机文件系统。 |
| [场景视图（+1）](../.archify/architecture-suite-20261031-030904/scenarios/index.html) | 默认求解、诊断、帮助和失败怎样贯穿上述结构？ | 有效输入走求解与输出；帮助立即退出；输入错误、无可行配置、进程超时和答案不合法由相应边界处理。 |

## 逻辑视图：问题与约束

`InputData` 保存硬件数量、内存、通信参数、层数、微批次数和专家负载。`Candidate` 保存每组 rank 数 `P`、初始分段数 `V`、切分位置及专家映射。布局展开后得到层到组的对应关系，时长模型为每层生成十种操作的整数时长。

这里的 **DAG** 是操作依赖构成的有向无环图；**调度模式**是从可选操作中做选择的优先规则。事件调度和列表调度采用不同的推进方式与优先规则，但都处理同一题目依赖和资源模型。`ProblemView` 借用层分组、时长及组内层数，具体配置由 `EventConfig` 或 `ListConfig` 提供。

每组包含计算、通信两类引擎；激活值与通信缓冲还受内存约束。调度结果把每个 operation 的开始时间与所属微批次、层和类型关联起来，`Time` 是最大结束时间。`ScheduleResult` 同时保留布局、映射、调度和目标值，避免只替换分数而丢失对应答案。

一般搜索严格降低 Time 才更新当前最优解；局部搜索还接受同 Time 且操作结束时间总和更小的方案。代码依据见 [`model/problem.hpp`](../src/model/problem.hpp)、[`operation_graph.hpp`](../src/core/operation_graph.hpp)、[`expert_mapping.cpp`](../src/placement/expert_mapping.cpp) 和 [`local_engine_polish.cpp`](../src/search/local_engine_polish.cpp)。

## 开发视图：模块和设计模式

`src/solver.cpp` 定义唯一的 `main`。`run` 处理计时、参数、输入、错误和输出，`Solver::solve` 是搜索编排门面。搜索模块通过参数对象和 `Scheduler<Strategy>` 调用事件或列表策略；策略适配器把具名参数转换为相应内核的调用约定。策略在编译期选择，不在每个 operation 上做虚函数派发。

局部搜索直接处理资源序列与重计时，不通过事件/列表策略接口。共享操作值类型供调度器与搜索结果复用；`core/operation_graph.hpp` 集中定义 DAG 边。这样的边界与实际调用一致，新增策略时仍需在搜索模块中安排何时评估候选。

当前 21 个 `.cpp` 按 `src/sources.mk` 联合编译，默认使用 C++17、`-O2`、LTO。相同源清单也供 `scripts/amalgamate.py` 导出 `submission/solver.cpp`；导出是交付形式，不是日常构建的必要步骤。接口检查与官方验收各自保留。详细模块表和参与者见[模块设计说明](module-design.md)与[设计模式说明](design-patterns.md)。

## 进程视图：真实执行与时间边界

官方 `run_all.py` 顺序处理用例。每例启动一个求解子进程，捕获 stdout 与 stderr，并统计求解进程的墙钟和 CPU 时间；求解成功后再启动官方 grader。求解器内部的 `run`、`Solver::solve`、搜索模块和调度内核属于同一 C++ 进程中的同步调用，没有为每种策略启动独立线程或进程。

`run` 在解析参数之前记录绝对计时起点。列表阶段、独立波前阶段和局部搜索按这一共同起点检查截止时间；默认内部搜索目标为累计 9200 毫秒。检查是协作式的，不能将它解释成操作系统保证的硬限时。官方 runner 的 10 秒外部限制独立约束求解进程，grader 耗时不计入该求解墙钟。

**题目模型中的引擎并行与求解程序的执行方式分属两个层次。**输出的调度可以安排计算和通信重叠，但本项目计算的是这些操作的时间安排，并不执行真实 GPU 训练。进程图的纵轴只表示调用先后，长度不代表测量耗时。代码依据见 [`app/solver.cpp`](../src/app/solver.cpp)、[`polish_driver.cpp`](../src/search/polish_driver.cpp) 和[官方 runner](../data/official/Problem/run_all.py)。

## 物理视图：本机程序和文件

多文件构建产生一个 `build/solver` 可执行文件；若裁判要求单源文件，则编译同一源码导出的 `submission/solver.cpp`。求解器从文件路径或 stdin 读取输入，从 stdout 写出 `PSI`、`MAP`、`SCHEDULE`，诊断写入 stderr。

批量验收时，runner 把用例路径追加到求解命令。runner 将捕获的答案写入临时文件，再将题目路径和答案路径交给 grader，最终回收临时文件。grader 模拟并检查答案，返回 Time 或不合法原因；最终逐例状态与统计由 runner 输出。这里的存储节点都是文件，没有数据库或网络服务部署要求。代码依据见 [`Makefile`](../Makefile)、[`io/output.cpp`](../src/io/output.cpp)、[官方 runner](../data/official/Problem/run_all.py) 和[官方 grader](../data/official/Problem/grader.py)。

## 场景视图：用例如何连接四个视角

| 场景 | 逻辑视图 | 开发视图 | 进程视图 | 物理视图 |
|---|---|---|---|---|
| S1：默认 full 求解并验收 | 生成完整可行调度，优化 Time | `run → Solver → search → scheduling/local` | 同步搜索结束后，再由独立 grader 判定 | 题目文件 → 求解 stdout → 临时答案 → 验收输出 |
| S2：限定候选或诊断工作量 | 限定 P，或限制局部扩展次数；可行性规则不变 | `Options` 控制阶段、候选限制和重计时路径 | `auto/wide` 不增加进程；pass 上限只影响局部扩展调用 | 使用同一可执行文件和输入渠道 |
| S3：查看帮助或输入无效 | 帮助无需构造调度问题；无可行配置不能产生答案 | 参数解析、输入边界或求解门面报告原因 | 帮助返回 0；参数/输入错误、无可行配置返回 2 | 帮助写 stdout；错误写 stderr |
| S4：外部超时或答案不合法 | 不合法答案违反题目条件，不能计入有效成绩 | 官方 runner / grader 负责最终判断 | 进程错误是 ERROR，超时是 TO，判题拒绝是 INVALID | 求解失败时不进入正常判题路径；仅成功答案交给 grader |

公开接口为 `--mode`、`--force-p`、`--retime-mode`、`--polish-pass-limit`、`--help` 五项；`-h` 是帮助别名。`--mode` 的 full/list/event/serial 是搜索阶段选择，不等同于事件内核的数字优先模式，也不等同于软件设计中的策略模式。

`list` 模式仍可能在列表阶段使用快速波前排序填隙；后续独立波前阶段与局部搜索只在 `full` 中启用。`--polish-pass-limit=0` 表示不额外限制扩展调用数，并不取消时间截止。`serial` 先探测可行布局，再由输出模块按依赖顺序生成完全串行的操作序列。

## 图与验收材料的边界

本次只更新图文，没有改变算法、官方验收脚本和正式成绩。已有当前代码的官方 50 例记录见[验收说明](../results/design_patterns/README.md)，本次图集的源码引用、浏览器检查与视觉审阅记录保存在[图集目录说明](../.archify/architecture-suite-20261031-030904/README.md)所列文件中。

题目 operation 的颜色始终按方向与引擎区分：前向计算蓝色、前向通信青色、反向计算橙色、反向通信紫色，并配合文字标签。软件模块节点颜色按各图图例表示职责；更细粒度的 operation 关系见[完整时间线与 DAG](visualizations/case-flow-r64-v4-c4b/index.html)。
