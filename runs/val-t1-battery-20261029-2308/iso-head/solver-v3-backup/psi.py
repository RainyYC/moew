"""层切分 ψ（题面 §3.1：“把 L 层连续切成 K 块”，本求解器只产 ``K=V``）。

报告 §2.3 的 ``dp_split2``：对每层定义两个权重

* 计算权重 ``C_l``  = 该层十个操作里**计算引擎**的时长之和；
* 通信权重 ``Wc_l`` = 该层十个操作里**通信引擎**的时长之和。

对 V 段做 DP，最小化「最慢 stage」的上下界 ``max_v max(ΣC_v, ΣWc_v)``；回溯出切点。
这同时压低计算与通信两条链（只按 ΣC 切会忽略通信主导的用例，如 ex3/ex4）。

``psi_candidates`` 在此之外**无条件追加**按层数均分的 ``balanced_split`` 与它的 ±1 微移：
内存受限时把层堆进同一个 stage 会让 ``Mexp`` 超限，而均分切分保证「每 stage 层数最平均」
的可行选项永远在候选集里（报告 §4 第 13/14 条）。
"""

from __future__ import annotations

from typing import Sequence

__all__ = ["dp_split", "dp_split2", "balanced_split", "shifted_splits", "psi_candidates"]


def _prefix(values: Sequence[int]) -> list[int]:
    out = [0]
    total = 0
    for value in values:
        total += value
        out.append(total)
    return out


def dp_split(L: int, V: int, comp: Sequence[int], comm: Sequence[int]) -> tuple[int, ...] | None:
    """最小化 ``max_v max(ΣC_v, ΣWc_v)`` 的 V 段切分，返回 V−1 个切点。"""
    if V <= 1:
        return ()
    if V > L:
        return None
    pref_c = _prefix(comp)
    pref_w = _prefix(comm)
    # dp[v][i]：把前 i 层切成 v 段时的最优值；choice[v][i]：第 v 段的起点
    dp: list[list[int | None]] = [[None] * (L + 1) for _ in range(V + 1)]
    choice: list[list[int]] = [[0] * (L + 1) for _ in range(V + 1)]
    dp[0][0] = 0
    for v in range(1, V + 1):
        row = dp[v]
        prev = dp[v - 1]
        for i in range(v, L + 1):
            best: int | None = None
            best_j = -1
            for j in range(v - 1, i):
                baseline = prev[j]
                if baseline is None:
                    continue
                seg = pref_c[i] - pref_c[j]
                other = pref_w[i] - pref_w[j]
                if other > seg:
                    seg = other
                cand = baseline if baseline > seg else seg
                if best is None or cand < best:
                    best = cand
                    best_j = j
            row[i] = best
            choice[v][i] = best_j
    if dp[V][L] is None:
        return None
    cuts: list[int] = []
    i = L
    for v in range(V, 0, -1):
        j = choice[v][i]
        if v > 1:
            cuts.append(j)
        i = j
    cuts.reverse()
    return tuple(cuts)


def dp_split2(L: int, V: int, comp: Sequence[int], comm: Sequence[int]) -> tuple[int, ...] | None:
    """报告 §2.3 的 ``dp_split2``：同时对计算与通信两条链做 min-max 切分。"""
    return dp_split(L, V, comp, comm)


def balanced_split(L: int, V: int) -> tuple[int, ...]:
    """按层数尽量均分（前 ``L % V`` 段各多一层）。"""
    if V <= 1:
        return ()
    base, remainder = divmod(L, V)
    cuts: list[int] = []
    position = 0
    for segment in range(V - 1):
        position += base + (1 if segment < remainder else 0)
        cuts.append(position)
    return tuple(cuts)


def shifted_splits(L: int, V: int, cuts: Sequence[int], radius: int = 1) -> list[tuple[int, ...]]:
    """把每个切点单独平移 ±1、±2（保持严格递增且段非空），用于局部扰动。"""
    out: list[tuple[int, ...]] = []
    if not cuts:
        return out
    for index, cut in enumerate(cuts):
        for delta in (-radius, radius):
            moved = cut + delta
            low = cuts[index - 1] if index > 0 else 0
            high = cuts[index + 1] if index + 1 < len(cuts) else L
            if low < moved < high:
                candidate = list(cuts)
                candidate[index] = moved
                out.append(tuple(candidate))
    return out


def psi_candidates(L: int, V: int, comp: Sequence[int], comm: Sequence[int]) -> list[tuple[int, ...]]:
    """候选切点集（去重、保序）：dp_split2 / 只按计算 / 只按通信 / 均分 / 均分±1。"""
    if V <= 1:
        return [()]
    candidates: list[tuple[int, ...]] = []
    seen: set[tuple[int, ...]] = set()

    def add(cuts: tuple[int, ...] | None) -> None:
        if cuts is None or cuts in seen:
            return
        if len(cuts) != V - 1:
            return
        seen.add(cuts)
        candidates.append(cuts)

    add(dp_split(L, V, comp, comm))  # dp_split2：两条链一起
    add(dp_split(L, V, comp, [0] * L))  # 只按计算切
    add(dp_split(L, V, [0] * L, comm))  # 只按通信切
    balanced = balanced_split(L, V)
    add(balanced)
    for moved in shifted_splits(L, V, balanced, 1):
        add(moved)
    return candidates
