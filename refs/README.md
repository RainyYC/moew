# refs/ —— 题面 §9 引用的四篇论文

题面《满足内存约束的 MoE 分块与重叠吞吐优化》§9 列出四篇参考文献。本文档记录它们是什么、为什么被引用、以及本地文件与校验和。

> 题面原话：**"它们只提供背景与思路；具体公式一律以第 4 节为准"**——这四篇里没有一个直接给出本题的十种操作、时长公式或内存核算方式，那些是题目自己的模型。

## 清单

| # | 论文 | 作者 | arXiv | 页数 | 本地文件 |
|---|---|---|---|---|---|
| 1 | *DeepSeek-V3 Technical Report* | DeepSeek-AI | [2412.19437](https://arxiv.org/abs/2412.19437) | 53 | `01-deepseek-v3-2412.19437.pdf` (1.8 MB) |
| 2 | *Zero Bubble Pipeline Parallelism* | P. Qi, X. Wan, G. Huang, M. Lin | [2401.10241](https://arxiv.org/abs/2401.10241) | 19 | `02-zero-bubble-2401.10241.pdf` (634 KB) |
| 3 | *PipeDream: Fast and Efficient Pipeline Parallel DNN Training* | A. Harlap, D. Narayanan, A. Phanishayee, V. Seshadri, N. Devanur, G. Ganger, P. Gibbons | [1806.03377](https://arxiv.org/abs/1806.03377) | 14 | `03-pipedream-1806.03377.pdf` (615 KB) |
| 4 | *UniEP: Unified Expert-Parallel MoE MegaKernel for LLM Training* | S. Zheng, X. Zheng, L. Chang, J. Zhai | [2604.19241](https://arxiv.org/abs/2604.19241) | 26 | `04-uniep-2604.19241.pdf` (1001 KB) |

下载时间：2026-10-26。来源：`https://arxiv.org/pdf/<id>`（HTTP 200，均为有效 PDF）。

## 各自对应题面的哪一块

| 论文 | 题面附注 | 在题面里的影子 |
| --- | --- | --- |
| DeepSeek-V3 | 层内分段的划分（attention / dispatch / MLP / combine）、DualPipe 的排法与参数共卡、跨节点通信的两级带宽 | 十种操作切成前向 4 步 + 反向 6 步；`PSI` 的 stage 切分；`B_in/B_out` 两级带宽 |
| Zero Bubble | 把反向拆成输入梯度与权重梯度两部分，用权重梯度填补空泡，用整数线性规划搜索调度 | `gemm_dw`/`s_dw` 只依赖 `comb_bwd`，因此可以推迟到计算引擎空闲时刻——这正是本题 ex1 能到 576（优于样例 592）的结构性来源 |
| PipeDream | 1F1B 排法 | 解题时常见的"窗口 W"启发式；题面不强制 1F1B，评测器只做前向模拟 |
| UniEP | 把 AllToAll 与 GroupGEMM 融合进同一 kernel | 题面把 `disp`/`gemm`/`comb` 建模为**分立**的通信与计算引擎，属于对 UniEP 的简化（融合内核被刻意不建模） |

## 校验和（sha256 前 16 位）

```
812a3fd645c80725  01-deepseek-v3-2412.19437.pdf
0de7cd6efd52eaa3  02-zero-bubble-2401.10241.pdf
8705b51efbb8b8a5  03-pipedream-1806.03377.pdf
d8ba80ea07a87d60  04-uniep-2604.19241.pdf
```

## 重新获取

```bash
cd refs
for id in 2412.19437 2401.10241 1806.03377 2604.19241; do
  curl -sSL -o "$id.pdf" "https://arxiv.org/pdf/$id"
done
```

> 这些 PDF 是二进制大文件，不进 git（`.gitignore` 已排除 `refs/*.pdf`）；本 README 入库。
