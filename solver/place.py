"""专家放置（MAP）：把每层 E 个专家分给 P 个 rank，每 rank 恰好 E/P 个（题面 §3.1）。

目标只有一个：压低 ``m_l = max_r（该 rank 承载的 slot 数）``，因为计算类操作的时长取
组内最慢 rank（题面 §4.3）。这是典型的「最小化最大负载」装箱问题：

* **LPT**（Largest Processing Time first）：按专家负载降序，逐个放到当前负载最小、
  且还没装满 ``E/P`` 个的 rank。均匀负载时退化为顺序放置；
* **顺序放置**（报告 §2.2 的「负载均衡层」分支）作为另一个候选；
* 小规模时对 LPT 结果做**换位下降**（exchange local search）：交换两个不同 rank 上的
  专家，若能让最大负载下降就接受。

逐层独立选 ``m`` 最小的那个候选，再取该层的结果。
"""

from __future__ import annotations

from typing import Sequence

from . import formula
from .casein import Case

__all__ = ["lpt_row", "sequential_row", "refine_row", "best_placement", "row_max_load"]


def row_max_load(case: Case, layer: int, P: int, row: Sequence[int]) -> int:
    """该放置下这一层的 ``m_l``。"""
    return formula.layer_m(case, layer, P, row)


def lpt_row(slots: Sequence[int], P: int, per_rank: int) -> tuple[int, ...]:
    """LPT：负载降序，放进「当前最轻且未满」的 rank。"""
    E = len(slots)
    order = sorted(range(E), key=lambda e: (-slots[e], e))
    loads = [0] * P
    counts = [0] * P
    row = [0] * E
    for expert in order:
        best = -1
        best_load = None
        for rank in range(P):
            if counts[rank] >= per_rank:
                continue
            load = loads[rank]
            if best_load is None or load < best_load:
                best_load = load
                best = rank
        # per_rank ≥ 1 保证总有可放的位置
        row[expert] = best
        loads[best] += slots[expert]
        counts[best] += 1
    return tuple(row)


def sequential_row(E: int, P: int, per_rank: int) -> tuple[int, ...]:
    """顺序放置：专家 e 放在 rank ``e // per_rank``（每 rank 恰好 E/P 个）。"""
    return tuple(min(P - 1, e // per_rank) for e in range(E))


def refine_row(slots: Sequence[int], P: int, per_rank: int, row: tuple[int, ...]) -> tuple[int, ...]:
    """换位下降：交换两个不同 rank 上的专家，若最大负载下降则接受。

    只在 ``E`` 不大时调用（`best_placement` 里有门槛）。保持每个 rank 恰好 ``E/P`` 个。
    """
    E = len(slots)
    ranks = list(row)
    loads = [0] * P
    for expert, rank in enumerate(ranks):
        loads[rank] += slots[expert]
    current = max(loads)
    improved = True
    while improved and current > 0:
        improved = False
        for a in range(E):
            ra = ranks[a]
            for b in range(a + 1, E):
                rb = ranks[b]
                if ra == rb:
                    continue
                # 交换后的两个 rank 负载
                na = loads[ra] - slots[a] + slots[b]
                nb = loads[rb] - slots[b] + slots[a]
                new_peak = current
                if na > new_peak:
                    new_peak = na
                if nb > new_peak:
                    new_peak = nb
                if new_peak < current:
                    ranks[a], ranks[b] = rb, ra
                    loads[ra] = na
                    loads[rb] = nb
                    current = new_peak
                    improved = True
                    break
            if improved:
                break
    return tuple(ranks)


def best_placement(case: Case, P: int) -> tuple[list[tuple[int, ...]], list[int]]:
    """逐层选使 ``m_l`` 最小的放置，返回 ``(rows, m)``。"""
    per_rank = case.E // P
    rows: list[tuple[int, ...]] = []
    ms: list[int] = []
    # 换位下降的规模门槛（E^2 量级；大用例直接跳过，LPT 已足够）
    allow_refine = case.E <= 48 and case.L * case.E <= 20000
    for layer in range(case.L):
        slots = formula.layer_slots(case, layer)
        candidates = [lpt_row(slots, P, per_rank), sequential_row(case.E, P, per_rank)]
        if allow_refine:
            candidates.append(refine_row(slots, P, per_rank, candidates[0]))
        best_row = candidates[0]
        best_m = row_max_load(case, layer, P, best_row)
        for row in candidates[1:]:
            m = row_max_load(case, layer, P, row)
            if m < best_m:
                best_m = m
                best_row = row
        rows.append(best_row)
        ms.append(best_m)
    return rows, ms
