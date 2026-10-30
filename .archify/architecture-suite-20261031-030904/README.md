# 当前算法与 4+1 图集

打开 [index.html](index.html) 浏览全部七张图。每个子目录的 `index.html` 是白色入口，通过 Archify 支持的 `?theme=light` 参数加载原生图；不修改生成 HTML 及其验证收据。

源码固定为 `e18822f8a3e1f91ea4227d0ffd4138d444c7c829`，对应本次图更新前已推送的代码。图中的来源按该提交验证；本次仅增加图文，不改算法、官方 runner 或成绩。

| 图 | 入口 | 内容 |
|---|---|---|
| 整体架构 | [architecture/index.html](architecture/index.html) | 从 run 与 Solver 门面，到搜索、静态策略和两类调度内核。 |
| 算法流水线 | [pipeline/index.html](pipeline/index.html) | P/V 候选、探测精评、事件改进、列表、波前、前缀与扩展；显示四种模式出口。 |
| 逻辑视图 | [logical/index.html](logical/index.html) | 输入、候选、操作时长、DAG、资源约束与可行调度。 |
| 开发视图 | [development/index.html](development/index.html) | 模块职责、多文件构建、共同源清单、可选单文件导出与验证。 |
| 进程视图 | [process/index.html](process/index.html) | 同一求解进程中的同步调用，以及官方 runner 与 grader 的进程边界。 |
| 物理视图 | [deployment/index.html](deployment/index.html) | 本机 CPU 进程、题目文件、临时答案文件和验收输出。 |
| 场景视图（+1） | [scenarios/index.html](scenarios/index.html) | 默认求解、可控诊断、帮助、参数错误、无解与官方判定。 |

原生图由 Archify 3.2 创建；`candidate.json` 是可复现输入，HTML、delivery、finalize 与 browser-check 收据按子目录保留。最新检查目录：整体架构与逻辑视图使用各自 `review-2/`，流水线、场景及物理视图使用各自 `review-3/`，开发与进程视图使用子目录根部。`visual-check/` 保存可选截屏证据，截屏文件本身不等于视觉审阅结论；实际审阅记录另见本目录的 `verification.json`。

程序级节点颜色按软件职责图例解释；operation 的前向计算、前向通信、反向计算、反向通信分别使用蓝、青、橙、紫，并同时保留文字标签。
