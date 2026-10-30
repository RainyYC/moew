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


def best_placement(
    case: Case, P: int, budget_box: list[float] | None = None
) -> tuple[list[tuple[int, ...]], list[int]]:
    """逐层选使 ``m_l`` 最小的放置，返回 ``(rows, m)``。

    ``budget_box`` 是**一次求解**里所有 ``P`` 共享的精确搜索余量（秒，单元素列表，
    原地扣减）。必须共享：`best_placement` 每个 `P` 调一次，`E=24` 的层单层 DFS 就要
    ~0.1 s，20 层 × 5 个 P 能吃掉十几秒，把 7.6 s 预算吃穿，求解器会返回一个 20×lb 的
    烂解（实测 x19 从 8.0M 爆到 60.7M）。余量用完后自动退回 LPT + 换位下降。
    """
    import time as _time
    budget_left = budget_box if budget_box is not None else [0.35]
    per_rank = case.E // P
    rows: list[tuple[int, ...]] = []
    ms: list[int] = []
    # 换位下降的规模门槛（E^2 量级；大用例直接跳过，LPT 已足够）
    allow_refine = case.E <= 48 and case.L * case.E <= 20000
    # 精确放置的门槛：E 小到 DFS 能跑完。同构层用签名缓存，避免 L 次重复计算。
    allow_exact = case.E <= 24 and P * per_rank == case.E
    exact_cache: dict[tuple[int, ...], tuple[int, ...] | None] = {}
    for layer in range(case.L):
        slots = formula.layer_slots(case, layer)
        candidates = [lpt_row(slots, P, per_rank), sequential_row(case.E, P, per_rank)]
        if allow_refine:
            candidates.append(refine_row(slots, P, per_rank, candidates[0]))
        if allow_exact and budget_left[0] > 0:
            # 缓存键必须是**有序**的 slots：同一组负载只要排列不同，最优行就不同
            # （踩过：用 sorted 做键，把层 0 的行套到排列不同的层 1 上，m 反而变差）
            signature = tuple(slots)
            if signature not in exact_cache:
                started = _time.monotonic()
                nodes = 200_000 if case.E <= 16 else 40_000
                exact_cache[signature] = exact_row(slots, P, per_rank, node_budget=nodes)
                budget_left[0] -= _time.monotonic() - started
            exact = exact_cache[signature]
            if exact is not None:
                candidates.append(exact)
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


def best_placement_split(
    case: Case, P: int, budget_box: list[float] | None = None
) -> tuple[list[tuple[int, ...]], list[int], list[int]]:
    """返回 ``(rows, m, m_rank)``。

    ``rows``/``m`` 是**深下降之后**的放置（用于真正建 plan，时长更短）；
    ``m_rank`` 是原来的 LPT/精确搜索结果（**只用于候选排序**）。

    这样做的原因：``m`` 同时决定"所有计算时长"和"候选的 lb"。如果直接把深下降的 m
    交给排序，配置的相对顺序会变、搜索轨迹全变——实测 50 例里 5 改善 4 变差
    （r24_p4_block +2.96%），净效果为负。把两者解耦后：排序保持原轨迹，而每个候选
    建 plan 时都能拿到更短的时长，是**纯单调改进**。
    """
    rows, m_rank = best_placement(case, P, budget_box)
    per_rank = case.E // P
    if case.E > 64 or per_rank < 2 or per_rank > 8:
        return rows, list(m_rank), list(m_rank)
    refined_rows: list[tuple[int, ...]] = []
    refined_m: list[int] = []
    for layer in range(case.L):
        slots = formula.layer_slots(case, layer)
        row = deep_refine_row(slots, P, per_rank, rows[layer])
        refined_rows.append(row)
        refined_m.append(row_max_load(case, layer, P, row))
    return refined_rows, refined_m, list(m_rank)


def deep_refine_row(
    slots: Sequence[int], P: int, per_rank: int, row: Sequence[int]
) -> tuple[int, ...]:
    """1/2/3 路交换下降：把最重 rank 的 a 个专家与另一个 rank 的 a 个专家对换。

    只做 1-1 / 2-2 会卡在"各 rank 分布同构"的局部最优：r16 的 916（下限 800）、
    x19 的 614/706（下限 536/616）都是这样。放开到 3 路之后两者都能打到下限。
    邻域很小（每 rank 只有 ``E/P`` 个专家），代价可忽略。
    """
    import itertools
    assign = list(row)
    ranks = [0] * P
    for expert, rank in enumerate(assign):
        ranks[rank] += slots[expert]
    current = max(ranks)
    improved = True
    while improved:
        improved = False
        heavy = max(range(P), key=lambda r: ranks[r])
        chosen = [e for e in range(len(assign)) if assign[e] == heavy]
        for size in (1, 2, 3):
            if size >= per_rank:
                break
            for group in itertools.combinations(chosen, size):
                group_load = sum(slots[e] for e in group)
                for other in range(P):
                    if other == heavy:
                        continue
                    targets = [e for e in range(len(assign)) if assign[e] == other]
                    for swap in itertools.combinations(targets, size):
                        swap_load = sum(slots[e] for e in swap)
                        new_heavy = ranks[heavy] - group_load + swap_load
                        new_other = ranks[other] - swap_load + group_load
                        if max(new_heavy, new_other) < current:
                            for e in group:
                                assign[e] = other
                            for e in swap:
                                assign[e] = heavy
                            ranks[heavy] = new_heavy
                            ranks[other] = new_other
                            current = max(ranks)
                            improved = True
                            break
                    if improved:
                        break
                if improved:
                    break
            if improved:
                break
    return tuple(assign)


def exact_row(
    slots: Sequence[int], P: int, per_rank: int, node_budget: int = 200_000
) -> tuple[int, ...] | None:
    """小 ``E`` 时求**最优**放置（最小化最大 rank 负载），失败则返回 ``None``。

    LPT + 1-1/2-2 交换会卡在"每 rank 分布同构"的局部最优上。r16 的层
    ``[374×4, 258×6, 26×6]`` 就是典型：LPT（含各种两两交换）都停在 916，
    而真正的最优是 800（= ⌈3200/4⌉，恰好可达）。

    做法是 DFS：专家按负载降序，依次尝试放进每个 rank；为了让搜索空间坍缩，
    **只允许把专家放进"负载不超过某个未满 rank"的位置，并保持各 rank 负载非增**
    （同构解只搜一次）。超过 ``node_budget`` 个结点就放弃，调用方退回启发式。
    """
    E = len(slots)
    if E > 24 or P < 1 or per_rank < 1 or E != P * per_rank:
        return None
    order = sorted(range(E), key=lambda e: -slots[e])
    total = sum(slots)
    lower = max((total + P - 1) // P, max(slots))
    ranks = [0] * P
    counts = [0] * P
    assign = [0] * E
    best = [None, lower - 1]  # [row, best_peak]
    nodes = [0]

    def dfs(i: int) -> None:
        nodes[0] += 1
        if nodes[0] > node_budget:
            return
        if i == E:
            peak = max(ranks)
            if best[0] is None or peak < best[1]:
                best[0] = list(assign)
                best[1] = peak
            return
        expert = order[i]
        load = slots[expert]
        seen_load = set()
        for r in range(P):
            if counts[r] >= per_rank:
                continue
            if ranks[r] in seen_load:  # 同负载的 rank 只试一次（对称性剪枝）
                continue
            if ranks[r] + load >= best[1] and best[0] is not None:
                continue
            seen_load.add(ranks[r])
            ranks[r] += load
            counts[r] += 1
            assign[expert] = r
            dfs(i + 1)
            ranks[r] -= load
            counts[r] -= 1
            if nodes[0] > node_budget:
                return

    dfs(0)
    if best[0] is None:
        return None
    return tuple(best[0])
