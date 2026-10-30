# 归档索引

- [`algorithm_v5/`](algorithm_v5/)：整理前完整算法目录，包含正式 v8 源码、原验收结果与历史报告。
- [`legacy_workspace/`](legacy_workspace/)：旧工作区代码、脚本、工具、样例、运行产物与原文档，按原相对路径归档；部分历史脚本需按新归档路径调整。
- [`worktrees/`](worktrees/)：整理前保留的 10 个顶层与 2 个嵌套 Git worktree，包含其未提交内容。映射和状态说明见 [`worktrees/README.md`](worktrees/README.md) 与 [`worktrees/archive_manifest.json`](worktrees/archive_manifest.json)。
- [`MIGRATION_MANIFEST.json`](MIGRATION_MANIFEST.json)：普通工作区整理前后的路径映射及源码、binary、已验收结果和 grader 校验哈希。
- [`before-retiming-speed/`](before-retiming-speed/)：精确重定时加速前的正式源码与报告快照，对应 `results/budget_search/full50/`。
- [`before-module-split/`](before-module-split/)：模块拆分前的单文件、构建配置及报告快照，对应 `results/retiming_speed/full50/`；用于本次等价性和性能对照。
- [`before-multi-tu/`](before-multi-tu/)：改为多翻译单元之前的完整模块源码、单文件导出、构建配置和文档快照，对应 `results/module_refactor/`。
- [`before-design-patterns/`](before-design-patterns/ARCHIVE.md)：加入静态调度策略、适配层、求解门面和五选项命令行之前的源码与文档快照，对应 `results/multi_tu/`。
- [`retiming_speed_experiment/`](retiming_speed_experiment/)：已通过 50 例验收并纳入正式源码的评估器加速候选、数值边界测试与说明。
- `multicritical_experiment/`、`joint_resource_experiment/`、`escape_search_experiment/`：未并入正式求解器的搜索实验，四例试跑对照见[实验记录](../results/search_neighborhood/pilot_summary.md)。

归档内容作为历史记录保存。当前求解器入口、成绩与验收说明以仓库根目录 [`README.md`](../README.md) 和[当前求解器报告](../docs/reports/current-solver-report.md)为准。
