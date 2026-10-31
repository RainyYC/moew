# 当前求解器：资源下界与优先级搜索

从[图集入口](index.html)浏览全部七张浅色交互图：整体架构、算法流水线，以及逻辑、开发、进程、物理部署和场景五个 4+1 视图。每张图都保留对应的 `candidate.json` 和源码引用。

## 源码基线

所有候选图固定引用 `7ce6bc426515cf275adbf2ca9962e79939752196`，源码仓库为 `git@github.com:RainyYC/moew.git`（Archify `local-only`）。图中算法与调用关系以该提交的文件行范围为证据；本图集自身的 candidate、HTML 和验证收据不属于该源码提交。

## small-full 搜索路径

额外的布局与优先级搜索只在 `mode=full`、非 serial、`mb≤16`、`mb×L×10≤8000` 且 `L>G` 时启用。small-full 路径从 `solver::run` 计时起点检查 list 3.4 秒、wave 4.2 秒；其他 full 实例仍使用 list 8 秒、wave 9 秒截止。layout 最多占 2.0 秒，截止累计封顶 6.1 秒；priority 最多占 1.6 秒，截止累计封顶 7.8 秒；最终 full polish 默认目标为累计 9.2 秒。普通规模或非 full 路径跳过 layout / priority。

布局阶段通过资源下界导出的 contiguous/folded threshold DP 生成候选，并尝试 mirror cut 邻域及与已有种子插值；priority 阶段接收当前 incumbent 与多个布局种子。同一 `ListScheduleStrategy` 保留 mode 0/1/2，增加具名 mode 3（DAG-ready rank 上的可复现随机键）和 mode 5（单调非均匀 microbatch offsets）。新增候选使用共同 validator 检查完整 DAG、引擎互斥和官方闭区间内存峰值；只有严格更短且可行的候选才能更新全局最佳解；较差但合法的布局仍可作为搜索种子。

## 颜色约定

入口页和逻辑视图明确区分题目中的四类 operation：前向计算蓝色、前向通信青色、反向计算橙色、反向通信紫色。软件模块本身使用各图自己的职责类型和图例；模块颜色不表示 operation 方向。

## 图集验证

七张图均通过 Archify 3.2 `finalize` 的 source-evidence、schema/layout、artifact strict-check 与 browser-check。每个视图根目录留有当前 candidate、HTML、delivery 和最新的 finalize / summary / browser-check 收据；重新渲染过的图，其根收据副本保留了实际 `review-2/` 或 `review-3/` 证据位置：

- `architecture/review-2/`
- `pipeline/review-3/`
- `logical/`、`development/review-2/`、`process/`、`deployment/`、`scenarios/review-2/`

主图的 capture 收据及两种尺寸、两种主题的四张截图保存在 [architecture visual-check](architecture/visual-check-2/architecture.visual-check.html) 和 [pipeline visual-check](pipeline/visual-check-3/pipeline.visual-check.html)。1440×900 的浅色和深色截图已人工检查：节点、标签和连线清楚，没有遮挡或裁切。两张主图的自动浏览器检查还覆盖 1600×1000、1920×1080、2048×1320 视口。

本轮代码集成使用原始官方 `data/official/Problem/run_all.py` 验收全部 50 个用例，全部通过；图集不修改 runner、grader 或求解源码。
