# MoE 调度求解器（Scale v8）

当前提交件为自包含的 C++17 单文件 [`src/solver.cpp`](src/solver.cpp)。官方 50 个用例全部通过，平均 `Time` 为 **20,407,224.34**，最长记录墙钟为 9.008 秒（官方单例限时 10 秒）。算法模型、完整搜索流程、复杂度、使用方式和逐例结果见[当前求解器完整报告](docs/reports/current-solver-report.md)，也可运行 `make report` 查看。验收汇总保存在 [`results/refactor_v8/`](results/refactor_v8/)。

## 快速开始

直接用 g++ 编译单文件：

```sh
g++ -std=c++17 -O2 -pipe src/solver.cpp -o solver
./solver < data/official/Problem/cases/x01_lr_block_p2.txt > answer.txt
python3 data/official/Problem/grader.py data/official/Problem/cases/x01_lr_block_p2.txt answer.txt
```

也可使用项目构建脚本生成 `build/solver`：

```sh
./scripts/build.sh
```

官方验收 runner 的五个可选参数顺序为：`mode borrow diff case_filter scale`。默认等价于 `run_latest ac auto "" auto`；每例通过 `timeout 10` 运行，再由官方 grader 判分。`mode` 指定 `results/<mode>/`。如需复现旧 v7 搜索，可将第五个参数设为 `off`：

```sh
./scripts/run_acceptance.sh v7_replay ac auto '' off
```

## 本轮重构验收与架构图

重构验收 summary 记录每例退出状态、墙钟和官方 `Time`。所有 50 例通过，官方 `Time` 与冻结 v8 逐例相同；构建脚本、单文件源码、验收表和编码规范的校验值见 [`results/refactor_v8/SHA256SUMS`](results/refactor_v8/SHA256SUMS)。旧验收校验清单 [`results/scale_v8_default/SHA256SUMS`](results/scale_v8_default/SHA256SUMS) 继续指向 `backup/pre-refactor-v8/` 中的原始源码和二进制，作为历史证据保留。

下面两张图描述已经验收的 v8 算法和调度工作流，且均已通过自动浏览器检查。图中证据锁定于整理前已验收的 v8 源码与报告；当前工作树经过本轮单文件重构，50 例逐项验收确认算法行为相同。额外 P/V 扩宽实验另见下文及实验报告，不属于图示范围。

- [v8 搜索架构图](.archify/architecture-moe-v8-20261030-183058/moe-v8-architecture.html)
- [v8 调度工作流图](.archify/workflow-moe-v8-20261030-183058/moe-v8-workflow.html)

## 当前源码与归档

- `src/` 只保留当前唯一提交件 `solver.cpp`；它不依赖项目本地头文件，可直接用 C++17 编译。
- [C++ 编码规范](docs/coding-style.md)和[格式配置](.clang-format)记录命名、格式与算法约束。
- `scripts/build.sh` 和 `scripts/run_acceptance.sh` 提供构建与官方验收入口。
- `results/scale_v8_default/` 保存重构前的 50 例基准；`results/refactor_v8/` 保存本轮重构验收结果。额外 P/V 搜索实验覆盖每例最多前 4 个可行 P、每个 P 前 3 个 V；最终官方 50 例中 0 例改善、50 例持平、0 例退步，全部通过 grader。扩宽阶段额外墙钟平均 0.580 秒、中位数 0.214 秒、最大 2.433 秒，因此实验未并入正式源码。细节见[扩宽 P/V 搜索实验报告](backup/wide_search_experiment/REPORT.md)。
- `data/` 与 `docs/problem/` 保留在原位置。
- 完整原 `algorithm_v5` 目录及历史报告在 `backup/algorithm_v5/`；旧工作区代码、脚本、工具和文档按原相对路径归入 `backup/legacy_workspace/`。重构前的 v8 源码和构建件保存在 `backup/pre-refactor-v8/`。
- `backup/MIGRATION_MANIFEST.json` 记录迁移前后的路径及正式源码、验收程序和结果文件的 SHA256。

当前默认运行启用 scale v8 搜索。`--scale=off` 可关闭扩展布局、波前和局部资源顺序搜索；默认 `--scale=auto` 在 `--borrow=ac`、`--diff=auto` 时启用这些阶段。更多细节、指标和限制见[当前求解器完整报告](docs/reports/current-solver-report.md)。

GitHub 保留源码、报告、架构图和验收汇总；构建二进制及逐例原始输出按 `.gitignore` 留在本地，可通过构建和验收脚本生成。发布文件可用 `sha256sum -c results/refactor_v8/SOURCE_SHA256SUMS` 核对；完整验收的 `SHA256SUMS` 还包含本地二进制及逐例输出，用于保存该次运行的身份。

整理前保存的 10 个顶层与 2 个嵌套 worktree（含未提交内容）位于 [`backup/worktrees/`](backup/worktrees/)，其路径映射见 [worktree 归档说明](backup/worktrees/README.md) 与 [manifest](backup/worktrees/archive_manifest.json)。普通文件迁移清单及校验记录见 [backup/MIGRATION_MANIFEST.json](backup/MIGRATION_MANIFEST.json)；归档目录导航见 [backup/README.md](backup/README.md)。
