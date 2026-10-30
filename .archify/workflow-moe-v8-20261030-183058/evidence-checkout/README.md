# MoE 调度求解器（Scale v8）

当前默认版本为已验收的 v8。官方 50 个用例全部通过：相对冻结 v7 有 31 例改善、19 例持平、无退步；平均 Time 从 20,589,369.80 降至 20,407,224.34，几何平均加速 1.01340×。最长记录墙钟为 8.811 秒，官方单例限时为 10 秒。完整逐例结果见 [`results/scale_v8_default/`](results/scale_v8_default/)，分析见[中文验收报告](docs/reports/scale-v8.md)。

## 快速开始

```sh
make                 # 编译到 build/solver
make smoke            # 官方 grader 验收 x01 与 x18
make official-serial  # 串行验收全部 50 例，结果写入 results/run_latest/
```

单例求解从标准输入读取题目，向标准输出写答案：

```sh
./scripts/build.sh
./build/solver < data/official/Problem/cases/x01_lr_block_p2.txt > answer.txt
python3 data/official/Problem/grader.py data/official/Problem/cases/x01_lr_block_p2.txt answer.txt
```

验收 runner 的五个可选参数顺序为：`mode borrow diff case_filter scale`。默认等价于 `run_latest ac auto "" auto`；每例通过 `timeout 10` 运行，再由 `data/official/Problem/grader.py` 判分。`mode` 指定 `results/<mode>/`。若需复现旧 v7 搜索，可将第五个参数设为 `off`，例如：

```sh
./scripts/run_acceptance.sh v7_replay ac auto '' off
```

## 当前源码与归档

- `src/` 仅含当前五个 C++ 源文件与头文件；构建输出为 `build/solver`。
- `scripts/build.sh` 和 `scripts/run_acceptance.sh` 提供构建与官方验收入口。
- `results/scale_v8_default/` 保存已验收的 50 例结果；`SHA256SUMS.pre-reorganization` 是整理前原样校验清单，`SHA256SUMS` 是新路径校验清单。
- `data/` 与 `docs/problem/` 保留在原位置。
- 完整原 `algorithm_v5` 目录及历史报告在 `backup/algorithm_v5/`；旧工作区代码、脚本、工具和文档按原相对路径归入 `backup/legacy_workspace/`。历史资料按原样保留，个别脚本可能需要根据归档后的路径调整。
- `backup/MIGRATION_MANIFEST.json` 记录迁移前后的路径及正式源码、验收程序和结果文件的 SHA256。

当前默认运行启用 scale v8 搜索。`--scale=off` 可回放 v7；默认 `--scale=auto` 在 `--borrow=ac`、`--diff=auto` 时启用 v8 阶段。更多细节、指标和限制见[验收报告](docs/reports/scale-v8.md)。

整理前保存的 10 个顶层与 2 个嵌套 worktree（含未提交内容）位于 [`backup/worktrees/`](backup/worktrees/)，其路径映射见 [worktree 归档说明](backup/worktrees/README.md) 与 [manifest](backup/worktrees/archive_manifest.json)。普通文件迁移清单及校验记录见 [backup/MIGRATION_MANIFEST.json](backup/MIGRATION_MANIFEST.json)；归档目录导航见 [backup/README.md](backup/README.md)。
