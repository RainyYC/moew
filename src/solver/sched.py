"""事件驱动的贪心列表调度器（报告 §2.4）+ 内存核算（报告 §2.5）。

调度器给每个 ``(mb, ℓ, op)`` 选一个开始时刻，构造方式保证题面 §4.2 的四条规则：

1. **层内依赖**：``s→disp→gemm→comb``；反向 ``s_bwd→comb_bwd→gemm_dx→disp_bwd``，
   ``gemm_dw`` / ``s_dw`` 只跟 ``comb_bwd``；
2. **管线依赖（层序）**：``s(ℓ)`` 等 ``comb(ℓ−1)``；``s_bwd(ℓ)`` 等 ``disp_bwd(ℓ+1)``
   （并且 ``s_bwd`` 本身在 ``DEPS`` 里等本层 ``comb``）；
3. **卡组引擎互斥**：每个卡组各有计算/通信一套引擎；非零时长操作占用引擎，**零时长
   操作不占用**（题面 §7.2/§7.5 的语义），相等时刻释放；
4. **因果性**：操作只在全部前置**已调度**后入堆，开始时取 ``max(前置完成, 引擎空闲)``。

此外有一个求解器侧的**窗口 W**（1F1B 启发式，评测器并不强制）：microbatch ``mb`` 在某
卡组的首层前向，要等 ``mb−W`` 在该卡组的反向全部完成，用于把「同时活跃的
(mb, 层)」压到内存能承受的范围（报告 §2.5 的 ``w_max``）。``W ≥ nmb`` 表示不设窗口。

**优先级变体**：堆键叠加 ``(fwd_bias, mb_desc, l_desc, l_major)`` 三组方向开关，同一配置
能生成多种拓扑，取 Time 最小的（报告 §2.4 末段）。
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from heapq import heappop, heappush
from typing import Optional, Sequence

from .casein import Case
from .formula import (
    COMM,
    COMM_OPS,
    COMP,
    COMP_OPS,
    DEPS,
    ENGINE,
    OP_COMB,
    OP_COMB_BWD,
    OP_DISP,
    OP_DISP_BWD,
    OP_NAMES,
    OP_S,
    OP_S_BWD,
    Plan,
)

__all__ = [
    "Schedule",
    "VARIANT_NAMES",
    "schedule",
    "window_candidates",
    "peak_closed",
    "memory_usage",
    "render_output",
    "check_schedule",
]

#: 反向操作（``s_bwd, comb_bwd, gemm_dx, gemm_dw, disp_bwd, s_dw``）。
BWD_OPS = (4, 5, 6, 7, 8, 9)

#: 调度变体 ``(fwd_first, mb_desc, l_desc, l_major)``。
VARIANTS: tuple[tuple[bool, bool, bool, bool], ...] = (
    (True, False, False, False),
    (True, False, True, False),
    (True, True, False, False),
    (True, True, True, False),
    (False, False, False, False),
    (False, True, True, False),
    (True, False, False, True),
    (False, True, False, True),
)
VARIANT_NAMES = tuple(
    f"fwd={int(a)}/mb={'desc' if b else 'asc'}/l={'desc' if c else 'asc'}/{'l-major' if d else 'mb-major'}"
    for (a, b, c, d) in VARIANTS
)

#: 大用例（运算量大）时的变体子集：只留三种拓扑差异最大的。
_SMALL_VARIANTS = (
    (True, False, False, False),
    (False, True, True, False),
    (True, True, True, False),
    # 反向优先 + mb/层升序 + mb 为主序：b11 这类"层少、mb 多"的用例上它最好（1.00×lb）
    (False, False, False, False),
)


@dataclass
class Schedule:
    """一份调度结果：``start`` / ``end`` 按 ``mb·L·10 + ℓ·10 + op`` 线性索引。"""

    time: int
    start: list[int]
    end: list[int]
    window: int
    variant: tuple[bool, bool, bool, bool]


# --------------------------------------------------------------------------- #
# 依赖表（按 L 缓存；偏移量相对 ``mb·L·10`` 内的下标）
# --------------------------------------------------------------------------- #

_TABLES: dict[int, tuple[list[tuple[int, ...]], list[tuple[int, ...]]]] = {}


def _dep_tables(L: int) -> tuple[list[tuple[int, ...]], list[tuple[int, ...]]]:
    cached = _TABLES.get(L)
    if cached is not None:
        return cached
    size = L * 10
    pred: list[tuple[int, ...]] = [()] * size
    for layer in range(L):
        for oi in range(10):
            # 偏移 = Δlayer·10 + (前置 op 下标 − 本 op 下标)：同 mb 内的线性下标差
            offsets = [d - oi for d in DEPS[oi]]
            if oi in (OP_S, OP_DISP) and layer > 0:
                offsets.append(-10 + OP_COMB - oi)  # 前向入口等上一层的 comb
            if oi in (OP_S_BWD, OP_COMB_BWD) and layer < L - 1:
                offsets.append(10 + OP_DISP_BWD - oi)  # 反向入口等下一层的 disp_bwd
            pred[layer * 10 + oi] = tuple(offsets)
    succ: list[list[int]] = [[] for _ in range(size)]
    for layer in range(L):
        for oi in range(10):
            base = layer * 10 + oi
            for offset in pred[base]:
                succ[base + offset].append(-offset)
    table = (pred, tuple(tuple(row) for row in succ))
    _TABLES[L] = table
    return table


# --------------------------------------------------------------------------- #
# 调度
# --------------------------------------------------------------------------- #


def schedule(
    case: Case,
    plan: Plan,
    window: int,
    variant: tuple[bool, bool, bool, bool],
    mode: str = "prio",
    priority: Optional[Sequence[int]] = None,
    comm_gap: int = 0,
    fill_gaps: bool = False,
) -> Optional[Schedule]:
    """生成一份调度；``mode`` = ``"prio"``（按优先级出堆，报告 §2.4）或 ``"early"``
    （按最早可开始时刻出堆，堆键做惰性修正）。构造上合法，返回 ``None`` 仅表示死锁
    （正常不会发生）。

    ``priority`` 给出时用它作为堆键（逐节点，长度 = ``nmb·L·10``），用于随机化/局部搜索；
    为 ``None`` 时用 ``variant`` 推出的 ``(方向, mb, ℓ, op)`` 键。

    ``comm_gap`` 给通信引擎插入的最小空隙：一次通信结束后至少再空 ``comm_gap`` 时间才有
    下一次通信。题面 §4.6 的 ``Movl`` 是**闭区间**峰值（首尾相接算两块），因此
    ``comm_gap=1`` 能把「零时长通信挤在同一时刻」的峰值降回 1，代价是每条通信 +1 时间；
    内存顶死的用例用它换内存（由调用方按内存核算决定是否采用）。
    """
    L = case.L
    nmb = case.nmb
    V = plan.V
    stride = L * 10
    total = nmb * stride
    if window is None or window > nmb:
        window = nmb
    if window < 1:
        window = 1
    W = window

    pred, succ = _dep_tables(L)
    group_of = plan.group_of_layer
    durations = plan.durations
    l0 = plan.first_layer_of_group
    layers_of_group = plan.layers_of_group

    base_rem = [len(pred[b]) for b in range(stride)]
    rem = base_rem * nmb
    end = [-1] * total
    start = [-1] * total
    pushed = bytearray(total)
    comp_free = [0] * V
    comm_free = [0] * V
    # 空隙按终点排序；列表调度可将后访问的独立操作插入已留出的空闲段。
    gaps = [[[], []] for _ in range(V)] if fill_gaps else None
    # bw_left[g][mb]：还有多少个反向操作没排；rel[g][mb]：已排反向操作的最大完成时刻
    # 窗口释放条件按**激活存活**计（题面 §4.6：激活从 comb 结束到 s_bwd 开始为存活），
    # 因此每个 (mb, 层) 只要 `s_bwd` 排上了就算释放；不能等 6 个反向操作全排完
    # （`gemm_dw`/`s_dw` 是旁支、优先级低，等它们会把窗口卡到很晚，实测会让
    # nmb 大 + 内存紧的用例退化 30 倍以上）。
    bw_left = [[len(layers) for _ in range(nmb)] for layers in layers_of_group]
    rel = [[-1] * nmb for _ in range(V)]

    fwd_first, mb_desc, l_desc, l_major = variant

    def key_of(mb: int, layer: int, oi: int) -> tuple[int, int, int, int]:
        if oi <= 3:
            head = 0 if fwd_first else 1
        else:
            head = 1 if fwd_first else 0
        mbk = -mb if mb_desc else mb
        lk = -layer if l_desc else layer
        if l_major:
            return (head, lk, mbk, oi)
        return (head, mbk, lk, oi)

    def earliest(idx: int) -> int:
        mb = idx // stride
        base = idx - mb * stride
        layer = base // 10
        oi = base - layer * 10
        group = group_of[layer]
        ready = 0
        for offset in pred[base]:
            dep_end = end[idx + offset]
            if dep_end > ready:
                ready = dep_end
        free = comp_free[group] if ENGINE[oi] == COMP else comm_free[group]
        if free > ready:
            ready = free
        if layer == 0 and base_rem[oi] == 0 and mb >= W:
            waiting = rel[group][mb - W]
            if waiting > ready:
                ready = waiting
        return ready

    heap: list[tuple] = []

    def try_push(idx: int) -> None:
        if pushed[idx]:
            return
        mb = idx // stride
        base = idx - mb * stride
        layer = base // 10
        oi = base - layer * 10
        # 入口操作（层 0 上无前驱的那些，2026-10-29 之后是 s 与 disp）统一受窗口约束
        if layer == 0 and base_rem[oi] == 0 and mb >= W:
            group = group_of[layer]
            if bw_left[group][mb - W] > 0:
                return  # 窗口未释放
        pushed[idx] = 1
        if priority is not None:
            rank = priority[idx]
        else:
            rank = key_of(mb, layer, oi)
        if mode == "prio":
            heappush(heap, (rank, idx))
        else:
            heappush(heap, (earliest(idx), rank, idx))

    # 2026-10-29 修订后，层 0 上"零前驱"的操作不止 `s`（`disp` 也不再等 `s`），
    # 这些入口操作都要受窗口约束、也都要在释放时一起放开，否则要么空转死锁、
    # 要么绕过窗口让所有 microbatch 同时冲进来（内存直接爆）。
    entry_bases = [base for base in range(10) if base_rem[base] == 0]
    for mb in range(nmb):
        for base in entry_bases:
            try_push(mb * stride + base)

    count = 0
    time_max = 0
    while count < total:
        if not heap:
            if __import__("os").environ.get("SCHED_DEBUG"):
                done = [i for i in range(total) if start[i] >= 0]
                missing = [i for i in range(total) if start[i] < 0]
                print(f"[debug] count={count}/{total} missing={[(i//stride, (i%stride)//10, (i%stride)%10) for i in missing[:8]]}")
            return None
        entry = heappop(heap)
        idx = entry[1] if mode == "prio" else entry[2]
        mb = idx // stride
        base = idx - mb * stride
        layer = base // 10
        oi = base - layer * 10
        group = group_of[layer]

        ready = 0
        for offset in pred[base]:
            dep_end = end[idx + offset]
            if dep_end > ready:
                ready = dep_end
        if layer == 0 and base_rem[oi] == 0 and mb >= W:
            waiting = rel[group][mb - W]
            if waiting > ready:
                ready = waiting
        dur = durations[layer][oi]
        engine = ENGINE[oi]
        free = comp_free[group] if engine == COMP else comm_free[group]
        slot = -1
        if gaps is not None and dur and not comm_gap:
            available = gaps[group][engine]
            for j in range(bisect_right(available, (ready, float("inf"))), len(available)):
                stop, begin = available[j]
                if max(ready, begin) + dur <= stop:
                    ready = max(ready, begin)
                    slot = j
                    break
        if slot < 0 and free > ready:
            ready = free
        if mode == "early" and heap and ready > heap[0][0]:
            # 惰性修正：引擎/依赖只让起点后移，重排一次即可（摊还 O(1)）
            heappush(heap, (ready, entry[1], idx))
            continue

        start[idx] = ready
        dur = durations[layer][oi]
        finish = ready + dur
        end[idx] = finish
        if finish > time_max:
            time_max = finish
        if dur:
            if gaps is not None and not comm_gap:
                available = gaps[group][engine]
                if slot >= 0:
                    stop, begin = available.pop(slot)
                    if begin < ready:
                        available.insert(slot, (ready, begin))
                        slot += 1
                    if finish < stop:
                        available.insert(slot, (stop, finish))
                elif free < ready:
                    available.append((ready, free))
            if ENGINE[oi] == COMP:
                comp_free[group] = max(comp_free[group], finish)
            else:
                comm_free[group] = max(comm_free[group], finish + comm_gap)
        elif ENGINE[oi] == COMM and comm_gap:
            # 零时长通信也拉开距离（闭区间峰值下同一个 t 会算成多块缓冲）
            if finish + comm_gap > comm_free[group]:
                comm_free[group] = finish + comm_gap
        count += 1

        for offset in succ[base]:
            successor = idx + offset
            left = rem[successor] - 1
            rem[successor] = left
            if left == 0:
                try_push(successor)

        if oi == OP_S_BWD:
            left = bw_left[group][mb] - 1
            bw_left[group][mb] = left
            if finish > rel[group][mb]:
                rel[group][mb] = finish
            if left == 0:
                next_mb = mb + W
                if next_mb < nmb:
                    for base in entry_bases:
                        candidate = next_mb * stride + base
                        if rem[candidate] == 0:
                            try_push(candidate)

    return Schedule(time=time_max, start=start, end=end, window=W, variant=variant)


def window_candidates(case: Case, plan: Plan, big: bool = False) -> list[int]:
    """窗口 W 候选（从大到小；``W ≥ nmb`` 等价于不设窗口）。

    小用例把小窗口逐个试一遍；大用例只取对数刻度 + 报告 §2.6 的候选集，避免搜索超预算。
    """
    nmb = case.nmb
    values: set[int] = set()
    if not big:
        # `nmb` 小的时候逐个试（官方样例 nmb=2，候选就两三个）；`nmb` 大时逐个枚举会
        # 变成上千个候选，预算全耗在 W≈nmb 上，够不到 W≈nmb/8 这类真正好的窗口
        # （实测 b11：W=125/early 是 1.00×lb，而 W=1000 只有 1.26×lb）。
        if nmb <= 64:
            return list(range(nmb, 0, -1))
    # `k_w·nmb` 与 `k_w·nmb/2`：按比例锚定的窗口（≈ nmb/5 这类"中等窗口"实测最优，
    # 见 probe_window_anchors.py）—— 等比数列只给 1/2/4/8，探窗又是"离目标最近的候选"，
    # 于是 nmb/3..nmb/8 这一整段永远够不到（b13：W=20 是 1.186×lb，W=102 是 1.294×lb）。
    for num, den in ((2, 1), (1, 1), (2, 3), (1, 2), (1, 3), (1, 4), (1, 5),
                     (1, 6), (1, 8), (1, 12), (1, 16), (1, 24), (1, 32)):
        w = nmb * num // den
        if 1 <= w <= nmb:
            values.add(w)
    for w in (32, 24, 16, 12, 8, 6, 4, 3, 2, 1):
        if w <= nmb:
            values.add(w)
    # 内存推出来的窗口上限提示（报告 §2.5）
    per_layer = (case.E // plan.P) * case.Z + case.Zs
    for layers in plan.layers_of_group:
        mexp = len(layers) * per_layer
        if case.Uact > 0:
            allowed = (case.M - mexp - case.U) // case.Uact
            if allowed > 0 and len(layers) > 0:
                values.add(max(1, min(nmb, allowed // len(layers))))
    return sorted(values, reverse=True)


# --------------------------------------------------------------------------- #
# 内存（题面 §4.6）
# --------------------------------------------------------------------------- #


def peak_closed(intervals: Sequence[tuple[int, int]]) -> int:
    """闭区间并发峰值 ``max_t #{start ≤ t ≤ end}``（``t`` 只可能取某个 start）。"""
    if not intervals:
        return 0
    ordered = sorted(intervals)
    heap: list[int] = []
    best = 0
    index = 0
    total = len(ordered)
    while index < total:
        point = ordered[index][0]
        while heap and heap[0] < point:
            heappop(heap)
        cursor = index
        while cursor < total and ordered[cursor][0] == point:
            cursor += 1
        alive = len(heap) + (cursor - index)
        if alive > best:
            best = alive
        for k in range(index, cursor):
            heappush(heap, ordered[k][1])
        index = cursor
    return best


@dataclass
class GroupMemory:
    v: int
    mexp: int
    movl: int
    mact: int
    peak_comm: int
    peak_act: int

    @property
    def used(self) -> int:
        return self.mexp + self.movl + self.mact


def memory_usage(
    case: Case, plan: Plan, start: Sequence[int], end: Sequence[int]
) -> tuple[bool, list[GroupMemory]]:
    """逐卡组算 ``Mexp + Movl + Mact``，并与 ``M`` 比较（题面 §4.6/§4.7）。"""
    L = case.L
    nmb = case.nmb
    stride = L * 10
    per_layer_bytes = (case.E // plan.P) * case.Z + case.Zs
    groups: list[GroupMemory] = []
    ok = True
    for group, layers in enumerate(plan.layers_of_group):
        mexp = len(layers) * per_layer_bytes
        comm_intervals: list[tuple[int, int]] = []
        act_intervals: list[tuple[int, int]] = []
        for layer in layers:
            for mb in range(nmb):
                base = mb * stride + layer * 10
                for oi in COMM_OPS:
                    comm_intervals.append((start[base + oi], end[base + oi]))
                act_intervals.append((end[base + OP_COMB], start[base + OP_S_BWD]))
        peak_comm = peak_closed(comm_intervals)
        peak_act = peak_closed(act_intervals)
        info = GroupMemory(
            v=group,
            mexp=mexp,
            movl=case.U * peak_comm,
            mact=case.Uact * peak_act,
            peak_comm=peak_comm,
            peak_act=peak_act,
        )
        groups.append(info)
        if info.used > case.M:
            ok = False
    return ok, groups


def check_schedule(case: Case, plan: Plan, result: Schedule) -> list[str]:
    """求解器侧自检：依赖、引擎互斥、Time 一致性（与 judge 语义对齐，供 unit test 用）。"""
    L = case.L
    stride = L * 10
    pred, _ = _dep_tables(L)
    problems: list[str] = []
    for mb in range(case.nmb):
        for layer in range(L):
            base = mb * stride + layer * 10
            for oi in range(10):
                idx = base + oi
                t = result.start[idx]
                if t < 0:
                    problems.append(f"{mb}:{layer}:{OP_NAMES[oi]} 未调度")
                    continue
                for offset in pred[layer * 10 + oi]:
                    dep_end = result.end[idx + offset]
                    if t < dep_end:
                        problems.append(
                            f"{mb}:{layer}:{OP_NAMES[oi]} 在 {t} 早于前置完成 {dep_end}"
                        )
    # 引擎互斥
    for group, layers in enumerate(plan.layers_of_group):
        for engine, ops in ((COMP, COMP_OPS), (COMM, COMM_OPS)):
            intervals = []
            for layer in layers:
                for mb in range(case.nmb):
                    base = mb * stride + layer * 10
                    for oi in ops:
                        if plan.durations[layer][oi] > 0:
                            intervals.append(
                                (result.start[base + oi], result.end[base + oi], f"{mb}:{layer}:{OP_NAMES[oi]}")
                            )
            intervals.sort()
            for previous, current in zip(intervals, intervals[1:]):
                if current[0] < previous[1]:
                    problems.append(
                        f"卡组 {group} 的{'计算' if engine == COMP else '通信'}引擎冲突："
                        f"{previous[2]} 占用到 {previous[1]}，但 {current[2]} 在 {current[0]} 开始"
                    )
    expected = max(result.end)
    if expected != result.time:
        problems.append(f"Time 不一致：max(end)={expected} ≠ {result.time}")
    return problems


# --------------------------------------------------------------------------- #
# 输出渲染（题面 §3）
# --------------------------------------------------------------------------- #


def render_output(
    case: Case, plan: Plan, result: Schedule, map_rows: Sequence[Sequence[int]]
) -> str:
    """把调度渲染成题面 §3 的输出文本。

    * ``K=1``（``V=1``）时 PSI 行只写块数、不带切点（**空切点**）；
    * 同一时刻的多个操作合并到一行，按 ``(mb, ℓ, op)`` 升序；
    * 零时长操作照常写出（时长由判题核心按题面 §4.1 计算）。
    """
    L = case.L
    stride = L * 10
    start = result.start
    order = sorted(range(len(start)), key=start.__getitem__)
    lines: list[str] = []
    lines.append(f"{plan.V} {plan.P}")  # 2026-10 版题面：网格只有 (V,P)，D 已取消
    lines.append("PSI")
    if plan.K <= 1:
        lines.append("1")
    else:
        lines.append(str(plan.K) + " " + " ".join(str(point) for point in plan.psi))
    lines.append("MAP")
    for row in map_rows:
        lines.append(" ".join(str(value) for value in row))
    lines.append("SCHEDULE")
    total = len(order)
    index = 0
    while index < total:
        idx = order[index]
        point = start[idx]
        cursor = index
        tokens: list[str] = []
        while cursor < total and start[order[cursor]] == point:
            node = order[cursor]
            mb = node // stride
            base = node - mb * stride
            layer = base // 10
            oi = base - layer * 10
            tokens.append(f"{mb}:{layer}:{OP_NAMES[oi]}")
            cursor += 1
        lines.append(f"{point} " + " ".join(tokens))
        index = cursor
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# 左移压实（在贪心结果上做局部改进）
# --------------------------------------------------------------------------- #


def _topological_order(case: Case) -> list[int]:
    """按依赖（不含引擎互斥）给出一个拓扑序；同一 mb 内节点编号线性。"""
    L = case.L
    stride = L * 10
    total = case.nmb * stride
    pred, succ = _dep_tables(L)
    base_rem = [len(pred[b]) for b in range(stride)]
    indeg = base_rem * case.nmb
    order: list[int] = []
    from collections import deque

    queue = deque()
    for mb in range(case.nmb):
        node = mb * stride
        if indeg[node] == 0:
            queue.append(node)
    while queue:
        idx = queue.popleft()
        order.append(idx)
        mb = idx // stride
        base = idx - mb * stride
        for offset in succ[base]:
            successor = idx + offset
            indeg[successor] -= 1
            if indeg[successor] == 0:
                queue.append(successor)
    if len(order) != total:  # pragma: no cover - 依赖图必定无环
        raise RuntimeError("依赖图存在环，无法给出拓扑序")
    return order


def _earliest_fit(starts: list[int], ends: list[int], ready: int, duration: int) -> int:
    """在已占用的（互不相交、按 start 升序的）区间里，找 ≥ ready 的第一个 length=duration 的空隙。"""
    from bisect import bisect_right

    index = bisect_right(ends, ready)
    point = ready
    count = len(starts)
    while index < count:
        if starts[index] >= point + duration:
            break
        if ends[index] > point:
            point = ends[index]
        index += 1
    return point


def compact(
    case: Case, plan: Plan, result: Schedule, passes: int = 6, max_ops: int = 20000
) -> Schedule:
    """把贪心结果按拓扑序**逐个左移**到最早可行时刻（保持依赖与引擎互斥）。

    这是纯改进：每个操作只可能更早（``Time = max(end)`` 单调不增），且搬动后仍然满足题面
    §4.2 的四条规则（依赖看前驱完成、引擎避开已放置的区间）。窗口 W 不进模拟器（评测器
    不强制 1F1B），因此压实可以自由打乱窗口；内存由调用方复核。

    复杂度 ``O(n·k)``（每卡组每引擎的占用表用有序数组 + 二分插入）；``n`` 超过 ``max_ops``
    时直接跳过（大用例留时间给多配置搜索）。
    """
    L = case.L
    stride = L * 10
    total = case.nmb * stride
    if total > max_ops:
        return result
    pred, _ = _dep_tables(L)
    durations = plan.durations
    group_of = plan.group_of_layer
    order = _topological_order(case)
    starts = result.start
    ends = result.end
    current = result.time
    from bisect import bisect_right, insort

    for _ in range(passes):
        engine_starts: list[list[int]] = [[[], []] for _ in range(plan.V)]
        engine_ends: list[list[int]] = [[[], []] for _ in range(plan.V)]
        new_start = [0] * total
        new_end = [0] * total
        best = 0
        for idx in order:
            mb = idx // stride
            base = idx - mb * stride
            layer = base // 10
            oi = base - layer * 10
            ready = 0
            for offset in pred[base]:
                finish = new_end[idx + offset]
                if finish > ready:
                    ready = finish
            duration = durations[layer][oi]
            if duration <= 0:
                start_at = ready
            else:
                group = group_of[layer]
                engine = ENGINE[oi]
                start_at = _earliest_fit(
                    engine_starts[group][engine], engine_ends[group][engine], ready, duration
                )
                insort(engine_starts[group][engine], start_at)
                insort(engine_ends[group][engine], start_at + duration)
            new_start[idx] = start_at
            finish = start_at + duration
            new_end[idx] = finish
            if finish > best:
                best = finish
        starts, ends = new_start, new_end
        if best >= current:
            break
        current = best
    return Schedule(time=current, start=starts, end=ends, window=result.window, variant=result.variant)


# --------------------------------------------------------------------------- #
# 引擎序列局部搜索（把调度看成「每个卡组每套引擎上一个操作序列」）
# --------------------------------------------------------------------------- #
#
# 一个贪心调度只是在每个引擎上排了一个序列；真正决定 makespan 的是这些序列的交错。
# 于是把调度表示为 ``2V`` 条序列（零时长操作不占引擎，不进序列），用「交换序列里的两个
# 操作 → 按依赖 + 序列顺序求最长路」的模拟退火做局部改进（经典 job-shop 邻域）。
# 每次求值是 O(n + 边数)，小用例每秒可试十万次；这是把 ex2/ex6 从 4928/1752 压到
# 4880/1744 的关键一步（见 solver/NOTES.md）。


def engine_sequences(case: Case, plan: Plan, result: Schedule) -> list[list[list[int]]]:
    """从一份调度抽出 ``[卡组][引擎] → 操作序列``（按开始时刻升序）。"""
    L = case.L
    stride = L * 10
    total = case.nmb * stride
    durations = plan.durations
    group_of = plan.group_of_layer
    seqs: list[list[list[int]]] = [[[], []] for _ in range(plan.V)]
    for idx in range(total):
        base = idx % stride
        layer = base // 10
        oi = base - layer * 10
        if durations[layer][oi] <= 0:
            continue
        seqs[group_of[layer]][ENGINE[oi]].append((result.start[idx], idx))
    for group in range(plan.V):
        for engine in range(2):
            ordered = seqs[group][engine]
            ordered.sort()
            seqs[group][engine] = [idx for (_point, idx) in ordered]
    return seqs


def evaluate_sequences(
    case: Case, plan: Plan, seqs: list[list[list[int]]]
) -> Optional[tuple[int, list[int], list[int]]]:
    """按「依赖 + 引擎序列顺序」求最长路，返回 ``(Time, start, end)``；成环则 ``None``。"""
    L = case.L
    stride = L * 10
    total = case.nmb * stride
    pred, succ = _dep_tables(L)
    durations = plan.durations
    pred_len = [len(pred[b]) for b in range(stride)] * case.nmb

    seq_prev = [-1] * total
    seq_next = [-1] * total
    indeg = pred_len
    for group_seqs in seqs:
        for seq in group_seqs:
            length = len(seq)
            for position in range(length):
                idx = seq[position]
                if position > 0:
                    seq_prev[idx] = seq[position - 1]
                    indeg[idx] += 1
                if position + 1 < length:
                    seq_next[idx] = seq[position + 1]
    start = [0] * total
    end = [0] * total
    stack = [idx for idx in range(total) if indeg[idx] == 0]
    processed = 0
    makespan = 0
    while stack:
        idx = stack.pop()
        processed += 1
        base = idx % stride
        layer = base // 10
        oi = base - layer * 10
        ready = 0
        for offset in pred[base]:
            finish = end[idx + offset]
            if finish > ready:
                ready = finish
        previous = seq_prev[idx]
        if previous >= 0 and end[previous] > ready:
            ready = end[previous]
        finish = ready + durations[layer][oi]
        start[idx] = ready
        end[idx] = finish
        if finish > makespan:
            makespan = finish
        for offset in succ[base]:
            successor = idx + offset
            indeg[successor] -= 1
            if indeg[successor] == 0:
                stack.append(successor)
        following = seq_next[idx]
        if following >= 0:
            indeg[following] -= 1
            if indeg[following] == 0:
                stack.append(following)
    if processed != total:
        return None  # 交换引入了环
    return makespan, start, end


def improve_sequences(
    case: Case,
    plan: Plan,
    result: Schedule,
    trials: int,
    seed: int = 20261020,
    deadline: Optional[float] = None,
) -> Schedule:
    """模拟退火：随机交换某条引擎序列上的两个操作，保留「合法且更好」的调度。

    内存超限的候选只作为搜索中间态、不会成为返回结果（最终合法性仍由 judge 判定）。
    """
    import random
    import time as _time

    seqs = engine_sequences(case, plan, result)
    state = evaluate_sequences(case, plan, seqs)
    if state is None:  # pragma: no cover - 由合法调度抽出的序列必然无环
        return result
    current_time, current_start, current_end = state
    best = result
    best_time = result.time
    if current_time < best_time:
        ok, _groups = memory_usage(case, plan, current_start, current_end)
        if ok:
            best = Schedule(current_time, current_start, current_end, result.window, result.variant)
            best_time = current_time
    rng = random.Random(seed)
    temperature = max(1, current_time // 40)
    groups = plan.V
    for trial in range(trials):
        if deadline is not None and (trial & 0x3F) == 0 and _time.monotonic() > deadline:
            break
        seq = seqs[rng.randrange(groups)][rng.randrange(2)]
        length = len(seq)
        if length < 2:
            continue
        i = rng.randrange(length)
        j = rng.randrange(length)
        if i == j:
            continue
        seq[i], seq[j] = seq[j], seq[i]
        state = evaluate_sequences(case, plan, seqs)
        if state is None or state[0] > current_time + temperature * rng.random():
            seq[i], seq[j] = seq[j], seq[i]
            continue
        current_time, current_start, current_end = state
        if current_time < best_time:
            ok, _groups = memory_usage(case, plan, current_start, current_end)
            if ok:
                best = Schedule(
                    current_time, current_start, current_end, result.window, result.variant
                )
                best_time = current_time
        if trial % 500 == 499:
            temperature = temperature * 9 // 10
            if temperature < 1:
                temperature = 1
    return best
