"""每卡内存三块（题面 §4.6 / CONTRACT §6）。

一个卡组的每张卡持有相同的层，核算单位因此是**卡组**：

* ``Mexp = Σ_{ℓ∈卡组} ((E/P)·Z + Zs)`` —— 静态专家参数；
* ``Movl = U × 通信并发峰值``，**闭区间**：恰好在下次开始时结束算两块
  （题面 §4.6「一次传输恰好在下次开始时结束，要算作两块」；CONTRACT §6 同）。
  反过来说，「留出空隙的调度是用一单位时间换一块内存」也只有在闭区间语义下才成立；
* ``Mact = Uact × [comb 结束, s_bwd 开始] 内的激活峰值``，**闭区间**
  （题面 §4.6「前向恰好在反向开始时结束，该时刻仍持有这份激活」）。

三者之和必须 ≤ M，否则该映射非法（题面 §4.7）。

零长度通信
----------
``P = 1`` 时 ``x_l = 0``，通信操作以 ``[t, t]`` 出现。闭区间口径下它在那一瞬间算一份
缓冲；官方口径未确认，团队裁定**保守地计入**（CONTRACT §11「零长度通信计入 Movl」：
闭区间合法 ⇒ 半开口径也合法，宁可少选一个配置，也不交一个可能被判非法的解）。
实现用一个模块级开关 :data:`ZERO_LEN_COMM_COUNTS` 表达，置 ``False`` 即跳过
``end == start`` 的通信区间（``ex5`` 的 ``movl`` 变 0、``mini`` 变 1，``Time`` 与合法性
不变），官方口径一旦确认可一行切换。

注意：该开关**只影响通信缓冲 ``Movl``**。激活区间 ``[comb 结束, s_bwd 开始]`` 的闭区间
是题面 §4.6 明确要求的（"前向恰好在反向开始时结束，该时刻仍持有这份激活"），
因此 :func:`closed_peak` 默认仍然计入零长度激活，由调用方显式控制。
"""

from __future__ import annotations

from heapq import heappop, heappush
from typing import Iterable, Optional, Sequence

from .parse import Case

__all__ = [
    "ZERO_LEN_COMM_COUNTS",
    "Interval",
    "closed_peak",
    "streamed_peaks",
    "group_memory",
]

#: ``(start, end, tag)``；``tag`` 只用来在报错时定位（可以是层号编码、字符串等）。
Interval = tuple[int, int, object]

#: 零长度通信（``end == start``，典型是 ``P = 1`` 时 ``x_l = 0``）是否计入 ``Movl``。
#:
#: ``True``（默认）：闭区间口径——``[t, t]`` 的传输在它那一瞬间算一份缓冲。
#: 这是 **官方口径未确认时的保守选择**（CONTRACT §11）：闭区间合法 ⇒ 半开口径也合法，
#: 宁可放弃一个配置，也不交一个可能被判非法的解。
#:
#: ``False``：:func:`streamed_peaks` / :func:`closed_peak` 跳过 ``end == start`` 的通信
#: 区间。一行可切，7 个验收值的 ``Time`` 与合法性不受影响（``ex5`` 的 ``movl`` 0、
#: ``mini`` 的 ``movl`` 1），但 ``groups.movl`` 会变，故默认保持 ``True``。
#:
#: 只作用于通信缓冲；零长度**激活**仍按题面 §4.6 计入 ``Mact``。
ZERO_LEN_COMM_COUNTS = True


def closed_peak(
    intervals: Sequence[Interval],
    presorted: bool = False,
    count_zero_length: bool = True,
) -> tuple[int, Optional[int], object]:
    """闭区间并发峰值：``max_t #{start ≤ t ≤ end}``。

    返回 ``(峰值, 达到峰值的时刻, 该时刻某个刚开始的 interval 的 tag)``。

    * 峰值只可能出现在某个 ``start`` 上（``t`` 不是任何 ``start`` 时并发数只会减少），
      所以用一个「结束时刻小顶堆」沿线推进即可，不需要展开 2n 个事件；
    * 同一时刻多个 interval 同时开始时按组计入（闭区间），堆中「恰好此时结束」的
      那些尚未弹出，因此首尾相接会算成两块；
    * ``count_zero_length=False`` 时跳过 ``end == start`` 的区间（零长度通信口径，见
      :data:`ZERO_LEN_COMM_COUNTS`）。激活峰值必须保持默认 ``True``。
    """
    if not intervals:
        return 0, None, None
    if not count_zero_length:
        intervals = [item for item in intervals if item[1] != item[0]]
        if not intervals:
            return 0, None, None
    ordered: Sequence[Interval] = intervals if presorted else sorted(intervals, key=lambda item: item[0])
    heap: list[int] = []
    best = 0
    best_time: Optional[int] = None
    best_tag: object = None
    index = 0
    total = len(ordered)
    while index < total:
        start = ordered[index][0]
        while heap and heap[0] < start:
            heappop(heap)  # 在 start 之前就已结束，不算并发
        end_of_group = index
        while end_of_group < total and ordered[end_of_group][0] == start:
            end_of_group += 1
        alive = len(heap) + (end_of_group - index)
        if alive > best:
            best = alive
            best_time = start
            best_tag = ordered[index][2]
        for cursor in range(index, end_of_group):
            heappush(heap, ordered[cursor][1])
        index = end_of_group
    return best, best_time, best_tag


def streamed_peaks(
    stream: Iterable[tuple[int, int, int, object]], groups: int
) -> list[tuple[int, Optional[int], object]]:
    """流式计算逐卡组的闭区间峰值。

    ``stream`` 按 ``start`` **非降**给出 ``(group, start, end, tag)``（调度本身就是按
    时刻书写的，所以可以直接流式喂进来，不必把 64 万条通信区间存下来）。
    ``ZERO_LEN_COMM_COUNTS`` 为 ``False`` 时跳过 ``end == start`` 的零长度传输。
    """
    skip_zero_length = not ZERO_LEN_COMM_COUNTS
    heaps: list[list[int]] = [[] for _ in range(groups)]
    best = [0] * groups
    best_time: list[Optional[int]] = [None] * groups
    best_tag: list[object] = [None] * groups
    for group, start, end, tag in stream:
        if skip_zero_length and end == start:
            continue
        heap = heaps[group]
        while heap and heap[0] < start:
            heappop(heap)
        alive = len(heap) + 1
        if alive > best[group]:
            best[group] = alive
            best_time[group] = start
            best_tag[group] = tag
        heappush(heap, end)
    return [(best[group], best_time[group], best_tag[group]) for group in range(groups)]


def group_memory(
    case: Case,
    layers_of_group: Sequence[Sequence[int]],
    comm_peaks: Sequence[tuple[int, Optional[int], object]],
    act_intervals: Sequence[Sequence[Interval]],
    P: int,
) -> tuple[list[dict], list[dict]]:
    """逐卡组算 ``(Mexp, Movl, Mact)``。

    返回 ``(groups, details)``：

    * ``groups`` 即 CONTRACT §1 的 ``groups`` 字段
      ``[{"v", "mexp", "movl", "mact", "limit"}]``；
    * ``details`` 是内部量（峰值、峰值时刻与 witness），供 ``sim`` 生成可定位的
      ``memory`` 错误。
    """
    per_layer_expert_bytes = (case.E // P) * case.Z + case.Zs
    groups: list[dict] = []
    details: list[dict] = []
    for group, layers in enumerate(layers_of_group):
        mexp = len(layers) * per_layer_expert_bytes
        peak_comm, time_comm, tag_comm = comm_peaks[group]
        # 激活区间必须按闭区间计入（题面 §4.6），与通信零长度开关无关
        peak_act, time_act, tag_act = closed_peak(act_intervals[group], count_zero_length=True)
        groups.append(
            {
                "v": group,
                "mexp": mexp,
                "movl": case.U * peak_comm,
                "mact": case.Uact * peak_act,
                "limit": case.M,
            }
        )
        details.append(
            {
                "layers": len(layers),
                "peak_comm": peak_comm,
                "time_comm": time_comm,
                "tag_comm": tag_comm,
                "peak_act": peak_act,
                "time_act": time_act,
                "tag_act": tag_act,
            }
        )
    return groups, details
