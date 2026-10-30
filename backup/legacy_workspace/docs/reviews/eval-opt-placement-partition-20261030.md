# 评估：`opt-placement-partition` 分支是否合入 master

> 2026-10-30。维护者评估，结论：**暂不合入**（实测为中性偏负）。

## 被评估的内容

分支 `opt-placement-partition`（`33d4dc7`），交付「placement / 切层末端优化」：
`E≤48 refine` + `placement_tail` + `partition_tail`，附带约 8000 行探针与基准工具。

## 合并可行性

`git merge-tree master opt-placement-partition` 无冲突；实际在独立 worktree 里 merge 后：

- `make check`：7/7 通过
- `make six`：`560 / 4880 / 6072 / 3200 / 416 / 1696`（不变）

所以**技术上可以合**，问题在收益。

## 同条件背靠背 A/B

两次全量 50 例串行、背靠背跑（避免机器负载差异互比）：

| 版本 | 均值 TIME | 几何平均比值 |
|---|---|---|
| `master`（三项优化） | **21,736,156** | **0.7187** |
| `master` + `opt-placement-partition` | 21,750,041 | 0.7189 |

合并后均值 **+0.064%**、几何比值 0.7187 → 0.7189，**中性偏负**。

## 为什么抵消

两边压的是同一个目标——每层方阵放置的峰值负载 `m_l`：

- master：`place.exact_row`（E≤16 精确 DFS）+ `place.deep_refine_row`（1/2/3 路交换下降）
- 该分支：`refine_row` 家族 + `placement_tail` / `partition_tail`

`m_l` 一旦被压到每层下界 `⌈T_l/P⌉`，任何进一步的放置改动都没有空间了；两边都能到
下界时，后合入的一方只剩噪声。第 50 例的 ±0.06% 差异属于时间预算抖动。

## 什么情况下值得重新评估

1. master 的放置**没有**打到下界的用例出现。当前 `exact_row` 只在 `E ≤ 16`、`deep_refine_row` 在 `E ≤ 64 且 per_rank ≤ 8` 生效；超出的形状（大 `E`、大 `per_rank`）仍落在 LPT 上，那里可能还有空间。
2. 该分支里的 `partition_tail`（切层末端）如果包含了**与放置无关**的调度改进，可以单独摘出来评估——本次是整体 A/B，未做拆分归因。

## 结论

不合入。分支保留在仓库里，`opt-placement-partition` 的探针工具与实验报告仍可查阅。
