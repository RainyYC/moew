# MoE 调度求解器

维护源码按职责拆分在 `src/`，通过 24 个 C++17 实现文件联合编译，另有 29 个头文件；[`src/solver.cpp`](src/solver.cpp) 定义入口，流程编排在 `src/app/solver.cpp`。裁判需要单文件时，可导出自包含的 [`submission/solver.cpp`](submission/solver.cpp)。

当前算法加入资源头尾下界布局 DP、镜像切点与插值、随机优先级和非均匀微批次间距，并在原有 **9.2 秒**内部预算中分配搜索时间。未修改的官方 `run_all.py` 本轮验收 **50/50 合法、0 超时，平均 Time 20,247,910.26**；官方记录平均墙钟 9.23112 秒、最长 9.262 秒，包含记录适配器。对原主线在线记录，13 例改善、32 例持平、5 例退步，平均降低约 0.60%。详见[完整解题报告](docs/reports/current-solver-report.md)和[本轮验收记录](results/optimization_integration/README.md)。

[`20327`](https://github.com/RainyYC/moew/tree/20327) 标记合入前源码。20.327M 是离线参考集合的简称；该源码的原在线记录为 20.370M 左右，两种口径在报告第 12 节分别列出。

## 快速开始

从多个模块源文件增量构建：

```sh
make -j2 build
./build/solver data/official/Problem/cases/x01_lr_block_p2.txt > answer.txt
python3 data/official/Problem/grader.py data/official/Problem/cases/x01_lr_block_p2.txt answer.txt
```

也可使用项目构建脚本生成 `build/solver`：

```sh
./scripts/build.sh
```

导出裁判单文件并检查是否过期：

```sh
make submission
make submission-check
g++ -std=c++17 -O2 -pipe submission/solver.cpp -o solver
```

`src/sources.mk` 是多翻译单元构建和单文件导出共用的源清单。`make -j2 build` 生成对象与依赖文件并增量重编译，采用 C++17、`-O2` 和 LTO。`make submission` 是可选的单文件导出工作流；导出版本与联合编译版本使用相同模块源码，但不承诺二进制逐字节相同。

最终 50 例验收使用未修改的官方脚本 `data/official/Problem/run_all.py`；`make official` 与 `make official-serial` 都逐例串行调用它：

```sh
python3 data/official/Problem/run_all.py --cmd "./build/solver" --timeout 10
```

`run_all.py` 会把用例路径作为命令行参数追加给 solver，不会把用例送入标准输入。求解器同时支持 `solver case.txt`、`solver < case.txt` 和 `solver - < case.txt`；路径可以放在搜索选项之前或之后。文件无法打开、输入为空或缺少必要字段时会明确报错并退出。不要在 `--cmd` 中直接写 `< {case}`，该参数按程序参数列表解析，不经过 shell 重定向。

开发时可用辅助脚本 `scripts/run_acceptance.sh` 保存逐例输出；它的三个位置参数为：`result_dir search_mode case_regex`。默认使用完整搜索，每例通过 `timeout 10` 运行，再由官方 grader 判分。最终全50结果仍以原样的官方 `run_all.py` 输出为准。搜索模式可选 `full`、`list`、`event`、`serial`：

```sh
./scripts/run_acceptance.sh list_probe list ''
```

求解器公开 `--mode=full|list|event|serial`、`--force-p=N`、`--retime-mode=auto|wide`、`--polish-pass-limit=N` 和 `--help`。不带模式时等价于 `full`；输入路径仍可放在选项前后，也可用 `-` 表示标准输入。未知或不合法参数会报错退出。

## 当前架构、工作流与 4+1 视图

从[浅色交互图集](.archify/architecture-suite-integration-20261031-085057/index.html)进入当前七张图。整体架构图展示求解门面、搜索控制、参数对象与静态调度策略，流水线展示算法阶段、四种搜索模式和累计预算；4+1 从逻辑、开发、进程、物理部署四个角度描述系统，并用场景串联。具体解释见[4+1 视图说明](docs/architecture-4-plus-1.md)。

- [当前整体架构图](.archify/architecture-suite-integration-20261031-085057/architecture/index.html)
- [当前算法流水线图](.archify/architecture-suite-integration-20261031-085057/pipeline/index.html)
- [逻辑视图](.archify/architecture-suite-integration-20261031-085057/logical/index.html) · [开发视图](.archify/architecture-suite-integration-20261031-085057/development/index.html)
- [进程视图与调用时序](.archify/architecture-suite-integration-20261031-085057/process/index.html) · [物理部署视图](.archify/architecture-suite-integration-20261031-085057/deployment/index.html) · [场景视图（+1）](.archify/architecture-suite-integration-20261031-085057/scenarios/index.html)
- [operation 时间线与依赖 DAG 全 trace](docs/visualizations/case-flow-r64-v4-c4b/index.html)

求解器内部同步、串行搜索；题目中的计算/通信引擎并行属于输出调度的模型。官方 runner 在求解子进程结束后启动 grader。进程视图与 operation trace 的粒度不同；源文件职责与设计模式细节分别见[模块设计说明](docs/module-design.md)和[设计模式说明](docs/design-patterns.md)。

全 trace 对应 `r64_v4_c4b`：4,480 个操作、6,016 条模型 DAG 依赖边、14 条 group/engine 泳道。颜色表示操作方向与引擎：前向计算为蓝色 C、前向通信为青色 N、反向计算为橙色 C、反向通信为紫色 N；7 个 group 的平均利用率为 C 82.85%、N 82.30%。

本轮源码身份、单文件编译、模块检查和 full50 实测保存在 [`results/optimization_integration/`](results/optimization_integration/)。较早的 P/V 扩宽搜索实验作为历史实验归档在[实验报告](backup/wide_search_experiment/REPORT.md)。

## 当前源码与归档

- `src/solver.cpp` 定义唯一的 `main`；`src/sources.mk` 列出联合构建源文件，`make -j2 build` 增量编译为多翻译单元程序。裁判单文件 `submission/solver.cpp` 由 `make submission` 可选生成，`make submission-check` 检查导出是否过期。
- [模块设计说明](docs/module-design.md)列出各文件职责、operation 编号、统一 DAG 边来源和常量命名原则。
- [设计模式说明](docs/design-patterns.md)解释静态策略、配置对象、内核适配器和求解门面。
- [C++ 编码规范](docs/coding-style.md)和[格式配置](.clang-format)记录命名、格式与算法约束。
- `scripts/build.sh` 提供构建入口；`scripts/run_acceptance.sh` 是保存逐例结果的开发辅助检查。官方最终验收由未修改的 `data/official/Problem/run_all.py` 执行。
- 较早的 P/V 扩宽搜索实验见[历史实验报告](backup/wide_search_experiment/REPORT.md)。
- `data/` 与 `docs/problem/` 保留在原位置。
- 完整原 `algorithm_v5` 目录及历史报告在 `backup/algorithm_v5/`；旧工作区代码、脚本、工具和文档按原相对路径归入 `backup/legacy_workspace/`。重构前的 v8 源码和构建件保存在 `backup/pre-refactor-v8/`。
- `backup/MIGRATION_MANIFEST.json` 记录迁移前后的路径及正式源码、验收程序和结果文件的 SHA256。

当前默认 `full` 模式启用完整搜索，局部 retiming 默认采用经安全界验证的 64 位评估路径，不能证明安全时回退到 128 位。`--retime-mode=wide` 可强制 128 位；`--polish-pass-limit=N` 可限制 extension pass 数（0 不限），两者用于诊断对照。正式预算固定为 9200 毫秒；长时间实验应使用独立实验驱动。更多细节、指标和限制见[当前求解器完整报告](docs/reports/current-solver-report.md)。

GitHub 保留模块源码、导出的裁判单文件、报告、图表和验收汇总；构建二进制及逐例原始输出按 `.gitignore` 留在本地，可通过构建和验收脚本生成。当前构建的代码身份见 [`results/optimization_integration/command.json`](results/optimization_integration/command.json) 与 [`results/optimization_integration/SOURCE_SHA256SUMS`](results/optimization_integration/SOURCE_SHA256SUMS)；逐例 full50 成绩见[本轮验收说明](results/optimization_integration/README.md)。

整理前保存的 10 个顶层与 2 个嵌套 worktree（含未提交内容）位于 [`backup/worktrees/`](backup/worktrees/)，其路径映射见 [worktree 归档说明](backup/worktrees/README.md) 与 [manifest](backup/worktrees/archive_manifest.json)。普通文件迁移清单及校验记录见 [backup/MIGRATION_MANIFEST.json](backup/MIGRATION_MANIFEST.json)；归档目录导航见 [backup/README.md](backup/README.md)。
