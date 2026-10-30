# MoE 调度求解器（Scale v8）

维护源码按职责拆分在 `src/`，由 [`src/solver.cpp`](src/solver.cpp) 作为唯一 C++17 编译入口；裁判提交件是可独立编译的自包含 [`submission/solver.cpp`](submission/solver.cpp)。模块版本当前 full50 记录为 **50/50 通过、0 超时，平均 Time 20,367,560.88**；相对固定基线 47 例相同、3 例 Time 较高。平均墙钟为 9.21923433584 秒，最长 9.236006493 秒（`x15_lr_twochunk_p10`）。这批 full50 数据保持冻结。针对性复测已完成，表明默认截止预算会使搜索迭代数和最终 Time 波动，因此默认运行不保证每次得到相同 Time；详情见[模块重构验证记录](results/module_refactor/README.md)。算法模型、完整搜索流程、复杂度、使用方式和验收结果见[当前求解器完整报告](docs/reports/current-solver-report.md)，也可运行 `make report` 查看。

## 快速开始

从模块化源码编译：

```sh
g++ -std=c++17 -O2 -pipe src/solver.cpp -o solver
./solver data/official/Problem/cases/x01_lr_block_p2.txt > answer.txt
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

`src/solver.cpp` 只编译为一个翻译单元；`scripts/amalgamate.py` 会递归展开 `src/` 内项目头文件，生成可独立提交的 `submission/solver.cpp`。

直接使用官方批量验收脚本：

```sh
python3 data/official/Problem/run_all.py --cmd "./build/solver" --timeout 10
```

`run_all.py` 会把用例路径作为命令行参数追加给 solver，不会把用例送入标准输入。求解器同时支持 `solver case.txt`、`solver < case.txt` 和 `solver - < case.txt`；路径可以放在搜索选项之前或之后。文件无法打开、输入为空或缺少必要字段时会明确报错并退出。不要在 `--cmd` 中直接写 `< {case}`，该参数按程序参数列表解析，不经过 shell 重定向。

仓库验收脚本 `scripts/run_acceptance.sh` 的五个可选参数顺序为：`mode borrow diff case_filter scale`。默认等价于 `run_latest ac auto "" auto`；同样以文件参数传入用例，每例通过 `timeout 10` 运行，再由官方 grader 判分。`mode` 指定 `results/<mode>/`。如需关闭扩展搜索，可将第五个参数设为 `off`：

```sh
./scripts/run_acceptance.sh v7_replay ac auto '' off
```

## 当前架构与工作流

原搜索架构图和工作流图展示算法运行阶段、搜索控制及累计时间预算，不表示 C++ 文件布局。源代码模块职责见[模块设计说明](docs/module-design.md)。新增的两张图分别呈现模块调用顺序、返回与预算边界，以及一个实例内 operation 的调度和依赖关系；模块调用时序按函数/模块层级展示，operation dataflow 按任务/DAG 层级展示，两者粒度不同。

- [当前搜索架构图](.archify/architecture-moe-budget-20261030-211601/moe-budget-architecture.html)
- [当前算法工作流图](.archify/workflow-moe-budget-20261030-211601/moe-budget-workflow.html)
- [模块调用时序图（浅色）](.archify/sequence-solver-runtime-20261030-222608/index.html)
- [operation 时间线与依赖 DAG 全 trace](docs/visualizations/case-flow-r64-v4-c4b/index.html)

全 trace 对应 `r64_v4_c4b`：4,480 个操作、6,016 条模型 DAG 依赖边、14 条 group/engine 泳道。颜色表示操作方向与引擎：前向计算为蓝色 C、前向通信为青色 N、反向计算为橙色 C、反向通信为紫色 N；7 个 group 的平均利用率为 C 82.85%、N 82.30%。

本次模块重构及固定/full50 验收记录保存在 [`results/module_refactor/`](results/module_refactor/)。较早的 P/V 扩宽搜索实验作为历史实验归档在[实验报告](backup/wide_search_experiment/REPORT.md)。

## 当前源码与归档

- `src/solver.cpp` 是唯一编译入口；其余维护源码按 `common/core/model/io/placement/scheduling/search/app` 职责拆分。裁判单文件为 `submission/solver.cpp`，由 `make submission` 生成，`make submission-check` 检查与模块源码一致。
- [模块设计说明](docs/module-design.md)列出各文件职责、operation 编号、统一 DAG 边来源和常量命名原则。
- [C++ 编码规范](docs/coding-style.md)和[格式配置](.clang-format)记录命名、格式与算法约束。
- `scripts/build.sh` 和 `scripts/run_acceptance.sh` 提供构建与官方验收入口。
- 较早的 P/V 扩宽搜索实验见[历史实验报告](backup/wide_search_experiment/REPORT.md)。
- `data/` 与 `docs/problem/` 保留在原位置。
- 完整原 `algorithm_v5` 目录及历史报告在 `backup/algorithm_v5/`；旧工作区代码、脚本、工具和文档按原相对路径归入 `backup/legacy_workspace/`。重构前的 v8 源码和构建件保存在 `backup/pre-refactor-v8/`。
- `backup/MIGRATION_MANIFEST.json` 记录迁移前后的路径及正式源码、验收程序和结果文件的 SHA256。

当前默认运行启用 scale v8 搜索。局部 retiming 默认采用经安全界验证的 64 位评估路径，不能证明安全时回退到 128 位。`--retime-mode=wide` 可强制 128 位；`--polish-pass-limit=N` 可限制 extension pass 数（0 不限），两者用于诊断对照。局部资源顺序搜索在保留小例有限前缀后，还会按绝对时间预算扩展；`--budget-ms=9000..9500` 设置扩展预算，默认 9200 毫秒。`--scale=off` 可关闭扩展布局、波前和局部资源顺序搜索；默认 `--scale=auto` 在 `--borrow=ac`、`--diff=auto` 时启用这些阶段。更多细节、指标和限制见[当前求解器完整报告](docs/reports/current-solver-report.md)。

GitHub 保留模块源码、导出的裁判单文件、报告、图表和验收汇总；构建二进制及逐例原始输出按 `.gitignore` 留在本地，可通过构建和验收脚本生成。全量验收代码身份见 [`results/module_refactor/full50/command.json`](results/module_refactor/full50/command.json) 和 [`results/module_refactor/full50/SOURCE_SHA256SUMS`](results/module_refactor/full50/SOURCE_SHA256SUMS)；前者记录运行版本与二进制身份，后者列出正式源码和提交件校验值。

整理前保存的 10 个顶层与 2 个嵌套 worktree（含未提交内容）位于 [`backup/worktrees/`](backup/worktrees/)，其路径映射见 [worktree 归档说明](backup/worktrees/README.md) 与 [manifest](backup/worktrees/archive_manifest.json)。普通文件迁移清单及校验记录见 [backup/MIGRATION_MANIFEST.json](backup/MIGRATION_MANIFEST.json)；归档目录导航见 [backup/README.md](backup/README.md)。
