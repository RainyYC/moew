# r64_v4_c4b 完整排程与数据流

打开 `index.html` 即可离线查看；4480 个操作的数据已嵌入 HTML，不依赖旁侧 JSON 请求。`trace.json` 是便于机器读取和独立复核的副本。

## 用例选择

选择 `r64_v4_c4b`：7 层、64 个 microbatch、4480 个操作，映射使用 7 个 card group、每组 8 张卡。它明显小于 76800 操作的大型用例，同时计算与通信最忙组利用率接近，适合展示双引擎流水。

`Time=5,508,618` 是题目定义的离散时间单位，不是秒。单个 group/engine 利用率为该引擎正时长操作累计值除以 Time。最忙组计算引擎组为 3–6，通信引擎最忙组也为 3–6；每组 C/N 利用率分别为 89.23%/88.61%。七组等权平均分别为 C 82.85% / N 82.30%。组 0–2 各为 74.36% / 73.88%。因此最忙组利用率高于全组平均。

## 图示与操作

左侧时间线默认载入全部 4480 个操作和 14 条引擎泳道。microbatch/层选择器可聚焦视图；缩放滑块或滚轮放大时间，拖动平移。右侧 DAG 显示选中 microbatch 的全部 70 个节点和官方定义的 94 条依赖边，包括层内操作依赖和跨层 activation/gradient 依赖。SVG 区域可横向滚动查看全部十个操作列。四类操作颜色在时间线、DAG 节点和依赖边一致：前向计算蓝、前向通信青、反向计算橙、反向通信紫；C/N 同时写在泳道和节点副标签上。实线为层内边，虚线为跨层边。点选 DAG 节点或时间线操作会同步选中 microbatch、显示精确起止与时长、直接模型前驱/后继，以及同 group/engine 的资源顺序前后邻居。

全 trace 有 6016 条模型依赖边和 4466 条正时长资源顺序相邻边，二者分开保存、分开呈现。当前实例的 4480 个操作时长均为正；图仍支持将零时长任务作为占位显示。

## 复现和数据来源

运行 `python3 build_case_flow.py` 可重新生成嵌入完整 trace 的 `index.html` 和 `trace.json`。脚本直接调用官方 grader 的 `parse_instance`、`parse_mapping`、`simulate`、`op_preds` 和 `ENGINE`，使用精确整数 duration，不运行 solver，不生成估算时长。`simulate` 对输出执行官方排程合法性检查并返回 Time。脚本检查排程操作与完整操作集合均为 4480 个条目，并校验同资源相邻任务不重叠。

输入文件 SHA-256 由构建脚本从源文件自动读取并更新此处：

<!-- INPUT_HASHES_BEGIN -->
- `data/official/Problem/cases/r64_v4_c4b.txt`: `79e154fca4f96d54e09b7be3a546522778421b9212fc0a73947ac4045328323d`
- `results/retiming_speed/full50/r64_v4_c4b.out`: `513cc454baa2279a56c07cd6bfe8f048ea1518bdcebcb021e1e21de2091e05db`
- `data/official/Problem/grader.py`: `c42d5f0675e33cbfc1d40bdcafbb8aa40b6d0a4e26377e69405cdbb2b167cfbc`
<!-- INPUT_HASHES_END -->

图来自 `results/retiming_speed/full50/r64_v4_c4b.out` 这一冻结验收排程。没有进行历史算法比较。

## 浏览器 QA

2026-10-30 使用本地浏览器直接打开单文件 `index.html`（`file://`），在 1440×1250 窗口实际检查并查看截图：默认状态有 14/14 条泳道且能看到 group 6 的 C/N；全 trace 4480 操作，DAG 为 70 节点/94 条边，SVG 有四类颜色标记，页面背景为浅色。console 检查无报错输出。

交互检查通过：点击 DAG 切至 mb 5 的 `5:0:s`，显示 successor `5:0:comb` 和资源后邻居；点击时间线的 mb 12、层 3、group 3、N 引擎 `12:3:disp` 后，右侧同步为 mb 12，并显示模型前驱 `12:2:comb`、后继 `12:3:gemm` 以及资源前后邻居 `11:3:comb` / `13:3:disp`。筛选 mb 12 + 层 3 得到 10 个可见操作；重置后恢复全微批次、全层、未选中状态、缩放 1 和起点 0。

截图保存在本目录： [默认总览](</home/rainy/hackathon/docs/visualizations/case-flow-r64-v4-c4b/qa-default.png>) 与 [选中任务及依赖详情](</home/rainy/hackathon/docs/visualizations/case-flow-r64-v4-c4b/qa-selected-task.png>)。两张截图均已实际查看。
