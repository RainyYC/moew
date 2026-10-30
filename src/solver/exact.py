"""精确搜索：`nmb=2` 且**每个 stage 只含 1 层**时的双 microbatch 交错穷举。

为什么要单开一条路
------------------
报告 §4 第 17 条那条路径：这类形状的调度拓扑空间很小，可以把「同一 stage 内两个
microbatch 的操作交错」**枚举穷尽**，而不是靠退火碰运气。本模块只负责这一步；网格、切层、
MAP 仍由 `solver/solve.py` 的主搜索给出（因此这里拿到的是一份确定好的 :class:`Plan`）。

表示与枚举
----------
一份调度可以写成「每个卡组两套引擎上各一条操作序列」（非零时长的操作才占引擎）。对
``nmb=2``、每 stage 单层的形状：

* **通信引擎**：每个 (mb, 层) 的通信操作依赖顺序固定为
  ``disp → comb → comb_bwd → disp_bwd``（中间隔着 comp 上的 ``gemm`` / ``gemm_dx``），
  因此每个 stage 的两条 mb 链只有**交错顺序**是自由的，共 ``C(k0+k1, k0)`` 种；
* **计算引擎**：先用「最早可开始 + 固定优先级」贪心放置（4 个优先级变体）；再对第一阶段最好
  的几个通信交错枚举计算操作的**线性扩展**（`_comp_extensions`，规模受 `COMP_EXTENSION_CAP`
  等上限约束）；
* 两个 stage 的通信交错做笛卡尔积，逐对模拟——跨 stage 的两条 feed
  （``s(mb,ℓ+1) ≥ comb(mb,ℓ)``、``s_bwd(mb,ℓ) ≥ disp_bwd(mb,ℓ+1)``）在模拟里自然满足。

模拟得到的每个候选都满足题面 §4.2 的四条规则（依赖已满足、引擎串行、非零时长才占引擎、
因果性由 ``max(依赖完成, 引擎空闲)`` 保证），因此一定是**合法映射**。覆盖范围要如实说：
通信交错是**穷举**的（每个 stage 的两条 mb 链全部交错），计算顺序只对第一阶段最好的若干
通信交错做**部分**枚举（完整联合枚举是 4900 × 6400 ≈ 3.1×10^7，10 s 预算内跑不完）。所以
结论只能是「枚举了 N 个候选、没找到更优」，**不是「不可达」**。

边界
----
* 只对 ``nmb=2`` 且每个卡组恰好 1 层、且交错总数 ≤ ``MAX_SPACE`` 的形状生效（ex2/ex6/ex5
  与 L=1 的 ex1/ex3/ex4 都命中；L≥3 的多 stage 形状交错数爆炸，直接不适用）；
* 调用方给时间预算（`deadline`），到点即停并返回已找到的最好解（可能是 `None`）。
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass
from math import comb
from typing import Optional, Sequence

from . import sched
from .casein import Case
from .formula import (
    COMM,
    COMP,
    ENGINE,
    OP_COMB,
    OP_COMB_BWD,
    OP_DISP,
    OP_DISP_BWD,
    Plan,
)

__all__ = [
    "COMM_CHAIN",
    "MAX_SPACE",
    "ExactResult",
    "applicable",
    "space_size",
    "search",
]

#: 同一 (mb, 层) 上占用通信引擎的四个操作，依赖顺序固定（题面 §4.2 第 1 条）。
COMM_CHAIN: tuple[int, ...] = (OP_DISP, OP_COMB, OP_COMB_BWD, OP_DISP_BWD)

#: 交错总数上限（两个 stage 的笛卡尔积）。超过就判定「不适用」，交回主搜索。
MAX_SPACE = 200_000

#: 第二阶段：最多对多少个「第一阶段最好的通信交错」再做计算顺序枚举。
PHASE_B_SEEDS = 4
#: 单个 stage 的计算线性扩展上限（超过则跳过第二阶段，统计里如实写）。
COMP_EXTENSION_CAP = 40_000
#: 两个 stage 计算扩展的笛卡尔积上限（超过则改为逐 stage 枚举）。
COMP_PAIR_CAP = 40_000
#: 第二阶段总共允许的模拟次数（保证耗时有界、且与机器快慢无关）。
PHASE_B_BUDGET = 60_000

#: 计算引擎上同刻候选的 tie-break：越靠前越关键（前向链 / 输入梯度链优先于权重梯度）。
COMP_PRIORITIES: tuple[tuple[int, ...], ...] = (
    (2, 6, 0, 4, 7, 9),  # gemm → gemm_dx → s → s_bwd → gemm_dw → s_dw
    (2, 6, 7, 9, 0, 4),  # 权重梯度提前，覆盖「把 gemm_dw/s_dw 挪进空档」的拓扑
)
#: mb 的先后顺序也各试一遍（两条 chain 谁先起跑会改变 feed 关系）。
MB_FIRST: tuple[bool, ...] = (True, False)


@dataclass
class ExactResult:
    """一次精确搜索的产出与统计（统计要写进 NOTES，证明「搜过、没找到」）。"""

    time: int
    start: list[int]
    end: list[int]
    groups: list[sched.GroupMemory]
    # -- 统计 ---------------------------------------------------------------
    space: int = 0            # 通信交错对数（每 stage 一对 mb 链的全部交错之积）
    feasible: int = 0         # 其中能排出合法调度（无死锁）的通信交错对数
    variants: int = 0         # 第一阶段用的计算优先级变体数
    enumerated: int = 0       # 实际模拟次数（第一阶段 + 第二阶段）
    comp_extensions: int = 0  # 第二阶段枚举的计算线性扩展数（0 = 未进入第二阶段）
    elapsed: float = 0.0

    @property
    def elapsed_text(self) -> str:
        return f"{self.elapsed:.2f}s"


def _rank_table(order: Sequence[int]) -> tuple[int, ...]:
    """把「操作优先级顺序」翻成「op 下标 → 名次」的查表（未列出的取末尾）。"""
    table = [len(order)] * 10
    for rank, oi in enumerate(order):
        table[oi] = rank
    return tuple(table)


def _comm_chains(case: Case, plan: Plan) -> list[list[list[tuple[int, int, int]]]]:
    """每个卡组、每个 mb 的通信链（只留非零时长的操作，按依赖顺序）。"""
    chains: list[list[list[tuple[int, int, int]]]] = []
    for layers in plan.layers_of_group:
        per_mb: list[list[tuple[int, int, int]]] = []
        for mb in range(case.nmb):
            chain: list[tuple[int, int, int]] = []
            for layer in layers:
                for oi in COMM_CHAIN:
                    if plan.durations[layer][oi] > 0:
                        chain.append((mb, layer, oi))
            per_mb.append(chain)
        chains.append(per_mb)
    return chains


def _interleavings(a: Sequence[int], b: Sequence[int]) -> list[tuple[int, ...]]:
    """两条序列的所有交错（保持各自相对顺序）。元素是同一索引空间里的 op 下标。"""
    na, nb = len(a), len(b)
    total = na + nb
    if na == 0 or nb == 0:
        return [tuple(a) + tuple(b)]
    out: list[tuple[int, ...]] = []
    for places in itertools.combinations(range(total), na):
        slot: list[int] = [0] * total
        for position, value in zip(places, a):
            slot[position] = value
        it = iter(b)
        for position in range(total):
            if position not in places:
                slot[position] = next(it)
        out.append(tuple(slot))
    return out


def space_size(case: Case, plan: Plan) -> Optional[int]:
    """交错总数；形状不适用时返回 ``None``。"""
    if case.nmb != 2:
        return None
    if len(plan.layers_of_group) != case.L:
        return None  # 不是「每 stage 恰好 1 层」
    if any(len(group) != 1 for group in plan.layers_of_group):
        return None
    chains = _comm_chains(case, plan)
    total = 1
    for per_mb in chains:
        k0, k1 = len(per_mb[0]), len(per_mb[1])
        total *= comb(k0 + k1, k0)
        if total > MAX_SPACE:
            return None
    return total


def applicable(case: Case, plan: Plan) -> bool:
    """是否走精确搜索（``nmb=2`` + 每 stage 单层 + 交错数可枚举）。"""
    return space_size(case, plan) is not None


def _simulate(
    case: Case,
    plan: Plan,
    seqs: Sequence[Sequence[Sequence[int]]],
    prio_rank: Sequence[int],
    mb_first: bool,
    pred: Sequence[Sequence[int]],
    succ: Sequence[Sequence[int]],
) -> Optional[tuple[int, list[int], list[int]]]:
    """在给定通信引擎顺序下，按最早可开始 + 固定优先级贪心排完整调度。

    返回 ``(Time, start, end)``；生成的调度一定满足题面 §4.2（依赖 / 引擎互斥 / 因果性）。
    """
    L = case.L
    stride = L * 10
    total = case.nmb * stride
    durations = plan.durations
    group_of = plan.group_of_layer
    groups = len(seqs)

    # seq_pos[idx] = (group, engine, position)；不属于任何序列的操作自由放置
    seq_pos: list[tuple[int, int, int]] = [(-1, -1, -1)] * total
    for group, per_engine in enumerate(seqs):
        for engine, seq in enumerate(per_engine):
            for position, idx in enumerate(seq):
                seq_pos[idx] = (group, engine, position)
    seq_ptr = [[0, 0] for _ in range(groups)]

    base_rem = [len(pred[b]) for b in range(stride)]
    rem = base_rem * case.nmb
    start = [-1] * total
    end = [-1] * total
    free = [[0, 0] for _ in range(groups)]
    count = 0
    makespan = 0

    while count < total:
        best_start = -1
        best_key: tuple[int, int, int, int] = (0, 0, 0, 0)
        best_idx = -1
        for idx in range(total):
            if start[idx] >= 0 or rem[idx] != 0:
                continue
            base = idx % stride
            group = group_of[base // 10]
            g_pos, g_engine, position = seq_pos[idx]
            if g_pos >= 0 and position != seq_ptr[g_pos][g_engine]:
                continue  # 该引擎的序列还没轮到它
            oi = base % 10
            engine = ENGINE[oi]
            ready = free[group][engine]
            for offset in pred[base]:
                dep_end = end[idx + offset]
                if dep_end > ready:
                    ready = dep_end
            if engine == COMM and g_pos >= 0:
                key = (0, oi, 0, idx)
            elif engine == COMM:
                key = (1, oi, 0, idx)
            else:
                mb = idx // stride
                key = (2, prio_rank[oi], mb if mb_first else -mb, idx)
            if best_idx < 0 or (ready, key) < (best_start, best_key):
                best_start = ready
                best_key = key
                best_idx = idx
        if best_idx < 0:  # pragma: no cover - 依赖图无环，不会发生
            return None
        idx = best_idx
        base = idx % stride
        group = group_of[base // 10]
        oi = base % 10
        duration = durations[base // 10][oi]
        start[idx] = best_start
        finish = best_start + duration
        end[idx] = finish
        if finish > makespan:
            makespan = finish
        count += 1
        if duration > 0:
            free[group][ENGINE[oi]] = finish
        node_group, node_engine, _node_pos = seq_pos[idx]
        if node_group >= 0:
            seq_ptr[node_group][node_engine] += 1
        for offset in succ[base]:
            successor = idx + offset
            rem[successor] -= 1
    return makespan, start, end


def _comp_extensions(case: Case, plan: Plan, group: int, cap: int) -> Optional[list[tuple[int, ...]]]:
    """该 stage 计算引擎上两条 mb 链的全部线性扩展（交错）；超过 ``cap`` 返回 ``None``。

    偏序取「同 mb 内 comp 操作之间的**传递**依赖」（例如 ``gemm < gemm_dx``、``gemm < gemm_dw``
    是经 comm 上的 ``comb → s_bwd → comb_bwd`` 传递出来的），保证枚举出的顺序不会死锁。
    """
    layers = plan.layers_of_group[group]
    if len(layers) != 1:
        return None
    layer = layers[0]
    comp_ops = [oi for oi in range(10) if ENGINE[oi] == COMP and plan.durations[layer][oi] > 0]
    if not comp_ops:
        return [()]
    pred, _succ = sched._dep_tables(case.L)
    stride = case.L * 10
    per_mb: list[list[tuple[int, ...]]] = []
    for mb in range(case.nmb):
        ops = [(mb, layer, oi) for oi in comp_ops]
        index = {key: position for position, key in enumerate(ops)}
        size = len(ops)
        before = [0] * size
        for position, (m, l, o) in enumerate(ops):
            stack = [(l, o)]
            seen: set[tuple[int, int, int]] = set()
            while stack:
                cur_layer, cur_op = stack.pop()
                base = cur_layer * 10 + cur_op
                for offset in pred[base]:
                    pred_base = base + offset
                    key = (m, pred_base // 10, pred_base % 10)
                    if key in seen:
                        continue
                    seen.add(key)
                    if key in index:
                        before[position] |= 1 << index[key]
                    stack.append((key[1], key[2]))
        orders: list[tuple[int, ...]] = []

        def walk(mask: int, current: list[int]) -> bool:
            if len(current) == size:
                orders.append(tuple(current))
                return len(orders) <= cap
            for position in range(size):
                if mask >> position & 1:
                    continue
                if before[position] & ~mask:
                    continue
                current.append(position)
                if not walk(mask | (1 << position), current):
                    current.pop()
                    return False
                current.pop()
            return True

        walk(0, [])
        if len(orders) > cap:
            return None
        per_mb.append([tuple(ops[position] for position in order) for order in orders])
    out: list[tuple[int, ...]] = []
    for first in per_mb[0]:
        for second in per_mb[1]:
            seq_a = [mb * stride + layer * 10 + oi for (mb, layer, oi) in first]
            seq_b = [mb * stride + layer * 10 + oi for (mb, layer, oi) in second]
            for merged in _interleavings(seq_a, seq_b):
                out.append(merged)
                if len(out) > cap:
                    return None
    return out


def search(
    case: Case,
    plan: Plan,
    deadline: float,
    base_time: int,
    log=None,
    stats: Optional[dict] = None,
) -> Optional[ExactResult]:
    """枚举通信交错 × 计算优先级（+ 计算顺序），返回**严格优于** ``base_time`` 的最优合法解。

    两阶段：
    1. 通信引擎交错穷举 × 计算优先级变体（贪心最早放置）；
    2. 对第一阶段最好的若干通信交错，枚举计算引擎的**线性扩展**（ex2 是 80×80，ex6 是
       每 stage 33264 个，按规模先枚举单个 stage 再枚举另一个）。

    统计（``space`` / ``feasible`` / ``variants`` / ``enumerated`` / ``comp_extensions`` /
    ``elapsed``）写进 NOTES，用于证明「搜过多少、多久」；没找到更优解时只陈述事实，不说
    「不可达」。
    """
    space = space_size(case, plan)
    if space is None:
        return None
    pred, succ = sched._dep_tables(case.L)
    chains = _comm_chains(case, plan)
    stride = case.L * 10
    per_group_orders: list[list[tuple[int, ...]]] = []
    for per_mb in chains:
        chain0 = [mb * stride + layer * 10 + oi for (mb, layer, oi) in per_mb[0]]
        chain1 = [mb * stride + layer * 10 + oi for (mb, layer, oi) in per_mb[1]]
        per_group_orders.append(_interleavings(chain0, chain1))
    variants = [
        (_rank_table(order), mb_first)
        for order in COMP_PRIORITIES
        for mb_first in MB_FIRST
    ]
    started = time.monotonic()
    best: Optional[ExactResult] = None
    enumerated = 0
    feasible = 0
    scored: list[tuple[int, tuple[tuple[int, ...], ...]]] = []
    stop = False

    def consider(outcome, combo, comp_extensions_used: int) -> None:
        nonlocal best
        if outcome is None:
            return
        makespan, start, end = outcome
        if makespan >= base_time:
            return
        if best is not None and makespan >= best.time:
            return
        ok, groups = sched.memory_usage(case, plan, start, end)
        if not ok:
            return
        best = ExactResult(
            time=makespan,
            start=start,
            end=end,
            groups=groups,
            space=space,
            feasible=feasible,
            variants=len(variants),
            enumerated=enumerated,
            comp_extensions=comp_extensions_used,
            elapsed=time.monotonic() - started,
        )
        if log:
            log(f"    [精确] 第 {enumerated} 个候选找到 Time={makespan}（下界 {plan.lb}）")

    # ---------------- 第一阶段：通信交错 × 计算优先级 ----------------
    groups = len(per_group_orders)
    for combo in itertools.product(*per_group_orders):
        if stop:
            break
        wrapped = tuple(((), seq) for seq in combo)
        local: Optional[tuple[int, list[int], list[int]]] = None
        for prio, mb_first in variants:
            enumerated += 1
            if (enumerated & 0x3F) == 0 and time.monotonic() > deadline:
                stop = True
                break
            outcome = _simulate(case, plan, wrapped, prio, mb_first, pred, succ)
            if outcome is None:
                continue
            if local is None or outcome[0] < local[0]:
                local = outcome
        if local is not None:
            feasible += 1
            scored.append((local[0], combo))
            consider(local, combo, 0)
    scored.sort(key=lambda item: (item[0], item[1]))

    # ---------------- 第二阶段：计算引擎的线性扩展 ----------------
    comp_extensions_used = 0
    phase_b_left = PHASE_B_BUDGET
    if not stop and scored:
        seeds = scored[: PHASE_B_SEEDS]
        for _seed_time, combo in seeds:
            if stop or phase_b_left <= 0 or time.monotonic() > deadline:
                break
            extensions: list[Optional[list[tuple[int, ...]]]] = [
                _comp_extensions(case, plan, group, COMP_EXTENSION_CAP) for group in range(groups)
            ]
            if any(item is None for item in extensions):
                continue  # 规模超上限：这一阶段跳过（统计里如实反映）
            if groups == 1:
                for extension in extensions[0]:
                    if stop or phase_b_left <= 0 or time.monotonic() > deadline:
                        break
                    enumerated += 1
                    comp_extensions_used += 1
                    phase_b_left -= 1
                    outcome = _simulate(
                        case,
                        plan,
                        ((extension, combo[0]),),
                        variants[0][0],
                        variants[0][1],
                        pred,
                        succ,
                    )
                    consider(outcome, combo, comp_extensions_used)
            elif groups == 2:
                first, second = extensions
                product_size = len(first) * len(second)
                if product_size <= COMP_PAIR_CAP:
                    for c0 in first:
                        if stop or phase_b_left <= 0 or time.monotonic() > deadline:
                            break
                        for c1 in second:
                            if phase_b_left <= 0:
                                break
                            enumerated += 1
                            comp_extensions_used += 1
                            phase_b_left -= 1
                            if (enumerated & 0x3F) == 0 and time.monotonic() > deadline:
                                stop = True
                                break
                            outcome = _simulate(
                                case,
                                plan,
                                ((c0, combo[0]), (c1, combo[1])),
                                variants[0][0],
                                variants[0][1],
                                pred,
                                succ,
                            )
                            consider(outcome, combo, comp_extensions_used)
                        if stop:
                            break
                else:
                    # 规模太大：先只枚举 stage 0 的顺序（stage 1 交回贪心），再只枚举 stage 1
                    for phase in (0, 1):
                        if stop or phase_b_left <= 0:
                            break
                        for extension in extensions[phase]:
                            if phase_b_left <= 0:
                                break
                            enumerated += 1
                            comp_extensions_used += 1
                            phase_b_left -= 1
                            if (enumerated & 0x3F) == 0 and time.monotonic() > deadline:
                                stop = True
                                break
                            if phase == 0:
                                wrapped = ((extension, combo[0]), ((), combo[1]))
                            else:
                                wrapped = (((), combo[0]), (extension, combo[1]))
                            outcome = _simulate(
                                case,
                                plan,
                                wrapped,
                                variants[0][0],
                                variants[0][1],
                                pred,
                                succ,
                            )
                            consider(outcome, combo, comp_extensions_used)
                        if stop:
                            break
            if stop:
                break

    elapsed = time.monotonic() - started
    if best is not None:
        best.elapsed = elapsed
        best.feasible = feasible
        best.enumerated = enumerated
        best.comp_extensions = comp_extensions_used
    summary = {
        "space": space,
        "stage_orders": [len(orders) for orders in per_group_orders],
        "variants": len(variants),
        "feasible": feasible,
        "enumerated": enumerated,
        "comp_extensions": comp_extensions_used,
        "elapsed": elapsed,
        "improved": best.time if best is not None else None,
        "base_time": base_time,
    }
    if stats is not None:
        stats.update(summary)
    if log:
        dimensions = "×".join(str(len(orders)) for orders in per_group_orders)
        gain = f"找到 Time={best.time}" if best is not None else f"未找到优于 {base_time} 的解"
        log(
            f"    [精确] 空间 {space}（{dimensions}）× {len(variants)} 变体；"
            f"可行交错对 {feasible}/{space}；实际模拟 {enumerated} 次"
            f"（其中计算线性扩展 {comp_extensions_used} 个）；{gain}，{elapsed:.2f}s"
        )
    return best
