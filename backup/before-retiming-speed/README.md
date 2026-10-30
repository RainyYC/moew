# MoE 调度求解器（Scale v8）

当前提交件为自包含的 C++17 单文件 [`src/solver.cpp`](src/solver.cpp)。50 个官方用例均通过官方 grader，平均 `Time` 为 **20,368,250.60**，平均墙钟为 9.22093 秒，最长为 9.23372 秒（单例限时 10 秒）。算法模型、完整搜索流程、复杂度、使用方式和逐例结果见[当前求解器完整报告](docs/reports/current-solver-report.md)，也可运行 `make report` 查看。本轮 50 例串行验收与官方 runner 代表 smoke 记录保存在 [`results/budget_search/full50/`](results/budget_search/full50/)；完整批次由 `scripts/compare_budget_search.py` 驱动并调用官方 grader，官方 `run_all.py` 只记录了代表用例。

## 快速开始

直接用 g++ 编译单文件：

```sh
g++ -std=c++17 -O2 -pipe src/solver.cpp -o solver
./solver data/official/Problem/cases/x01_lr_block_p2.txt > answer.txt
python3 data/official/Problem/grader.py data/official/Problem/cases/x01_lr_block_p2.txt answer.txt
```

也可使用项目构建脚本生成 `build/solver`：

```sh
./scripts/build.sh
```

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

架构图展示单个 `src/solver.cpp` 内的搜索控制、调度内核和输入输出职责；工作流图展示默认搜索阶段、规模条件与累计时间预算。两张图均包含小规模局部搜索前缀之后的全规模预算扩展，以及显存上界快路径，并以已提交源码为证据。

- [当前搜索架构图](.archify/architecture-moe-budget-20261030-211601/moe-budget-architecture.html)
- [当前算法工作流图](.archify/workflow-moe-budget-20261030-211601/moe-budget-workflow.html)

此前的单文件重构验收记录保存在 `results/refactor_v8/`，其中 50 例通过且 `Time` 与当时冻结的 v8 逐例相同；它不代表当前预算扩展后的成绩。对应文件身份见 [`results/refactor_v8/SHA256SUMS`](results/refactor_v8/SHA256SUMS)。旧验收校验清单 [`results/scale_v8_default/SHA256SUMS`](results/scale_v8_default/SHA256SUMS) 继续指向 `backup/pre-refactor-v8/` 中的原始源码和二进制，作为历史证据保留。

## 当前源码与归档

- `src/` 只保留当前唯一提交件 `solver.cpp`；它不依赖项目本地头文件，可直接用 C++17 编译。
- [C++ 编码规范](docs/coding-style.md)和[格式配置](.clang-format)记录命名、格式与算法约束。
- `scripts/build.sh` 和 `scripts/run_acceptance.sh` 提供构建与官方验收入口。
- `results/scale_v8_default/` 保存重构前的 50 例基准；`results/refactor_v8/` 保存本轮重构验收结果。额外 P/V 搜索实验覆盖每例最多前 4 个可行 P、每个 P 前 3 个 V；最终官方 50 例中 0 例改善、50 例持平、0 例退步，全部通过 grader。扩宽阶段额外墙钟平均 0.580 秒、中位数 0.214 秒、最大 2.433 秒，因此实验未并入正式源码。细节见[扩宽 P/V 搜索实验报告](backup/wide_search_experiment/REPORT.md)。
- `data/` 与 `docs/problem/` 保留在原位置。
- 完整原 `algorithm_v5` 目录及历史报告在 `backup/algorithm_v5/`；旧工作区代码、脚本、工具和文档按原相对路径归入 `backup/legacy_workspace/`。重构前的 v8 源码和构建件保存在 `backup/pre-refactor-v8/`。
- `backup/MIGRATION_MANIFEST.json` 记录迁移前后的路径及正式源码、验收程序和结果文件的 SHA256。

当前默认运行启用 scale v8 搜索。局部资源顺序搜索在保留小例有限前缀后，还会按绝对时间预算扩展；`--budget-ms=9000..9500` 设置扩展预算，默认 9200 毫秒。`--scale=off` 可关闭扩展布局、波前和局部资源顺序搜索；默认 `--scale=auto` 在 `--borrow=ac`、`--diff=auto` 时启用这些阶段。更多细节、指标和限制见[当前求解器完整报告](docs/reports/current-solver-report.md)。

GitHub 保留源码、报告、架构图和验收汇总；构建二进制及逐例原始输出按 `.gitignore` 留在本地，可通过构建和验收脚本生成。当前源码与本轮 50 例验收身份可用 `sha256sum -c results/budget_search/full50/SOURCE_SHA256SUMS` 核对。`results/refactor_v8/` 的校验清单保留对应验收身份，已变化的文件指向 `backup/before-runner-input-fix/` 中的快照；完整运行清单还包含本地二进制及逐例输出。

整理前保存的 10 个顶层与 2 个嵌套 worktree（含未提交内容）位于 [`backup/worktrees/`](backup/worktrees/)，其路径映射见 [worktree 归档说明](backup/worktrees/README.md) 与 [manifest](backup/worktrees/archive_manifest.json)。普通文件迁移清单及校验记录见 [backup/MIGRATION_MANIFEST.json](backup/MIGRATION_MANIFEST.json)；归档目录导航见 [backup/README.md](backup/README.md)。
