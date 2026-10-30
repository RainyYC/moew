"""事件驱动就绪前沿调度原型（frontier，t2 交付，**默认关闭**）。

设计目标
--------
现有 `solver.sched.schedule` 是「按优先级出堆」或「按最早可开始时刻出堆」的列表调度：
每次出堆都重新计算 ``max(前置完成, 引擎空闲)``，引擎空闲时刻一旦后移，同一引擎的一批旧键
会被逐个弹出再重入堆（最坏二次重入）；而且 ``earliest`` 对零时长操作也取 ``max(引擎空闲)``，
即使题面/官方 grader 明确「零时长不占引擎」。

本模块把调度写成**事件驱动的就绪前沿**：

* 每个卡组每套引擎只维护**就绪队列**（按依赖完成时刻排序）与**可派发桶**（依赖已满足、
  等引擎空闲）。操作从「就绪堆」晋升到「可派发桶」**最多一次**，之后只被弹出一次，
  因此入堆/出堆总数是 ``O(n)`` 而不是二次；
* 全局维护一个**引擎前沿堆**，堆键是「该引擎下一次可开工时刻」；只在引擎状态、依赖、
  内存门控变化时刷新对应引擎的堆项（惰性校验），不做全量扫描；
* 完成事件推动时间：只有依赖**真实完成**（``end`` 已知）后才把后继放进就绪队列；
* **零时长操作不占引擎**：依赖满足即可在任意时刻执行（``zero_free=True``），并形成
  同刻闭包；需要复现旧行为时用 ``zero_free=False``，此时零时长操作也排到引擎空闲之后
  （消融用，见 :func:`schedule` 参数）；
* **生命周期内存门控**（``gating=True``）：`peak_comm` 用「通信槽」闭区间着色（同刻
  先开后关 ⇒ 需要不同槽），`peak_act` 用「激活槽」计数（comb 入槽、s_bwd 出槽）。
  两个峰值**分别**受 ``cap_comm`` / ``cap_act`` 约束，且静态满足
  ``Mexp + U·cap_comm + Uact·cap_act ≤ M``；最终仍由 `sched.memory_usage` 复核。
  该门控允许**暂时等待**：门控满时该队列不出候选，等 s_bwd 释放后再继续，而不是
  预先固定 ``mb−W`` 窗口。

对外接口
--------
:func:`schedule`
    协议 §11.2 的稳定签名，返回 `sched.Schedule` 或 ``None``（死锁/预算内无完整解），
    绝不返回半份调度。``None`` 时调用方应回退到完整合法 incumbent。

:func:`memory_caps`
    由 ``M``/``Mexp``/``U``/``Uact`` 推出每个卡组的 ``(cap_comm, cap_act)`` 预留。

:class:`Stats`
    只用于**独立剖析**的计数器（堆入/出、晋升、前沿刷新、死锁原因），不参与正式墙钟。

正确性口径与 `judge/core` 一致的部分：实际合法性仍只认 ``python3 -m judge eval``；
本模块构造后必须依次过 `sched.check_schedule` / `sched.memory_usage` / `sched.render_output`。
"""

from __future__ import annotations

import heapq
import time as _time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Sequence

from . import sched
from .casein import Case
from .formula import (
    COMM,
    COMM_OPS,
    COMP,
    COMP_OPS,
    ENGINE,
    OP_COMB,
    OP_COMB_BWD,
    OP_DISP,
    OP_DISP_BWD,
    OP_GEMM_DX,
    OP_GEMM_DW,
    OP_S,
    OP_S_BWD,
    OP_S_DW,
    Plan,
)

__all__ = [
    "Caps",
    "Stats",
    "schedule",
    "memory_caps",
    "default_priority",
    "variant_priority",
    "parse_schedule_config",
]

INF = 1 << 60

#: 层 0 上「无同层前驱」的入口操作（2026-10-29 修订后是 ``s`` 与 ``disp``）。
_ENTRY_BASES: tuple[int, ...] = (OP_S, OP_DISP)


# --------------------------------------------------------------------------- #
# 统计与内存预留
# --------------------------------------------------------------------------- #


@dataclass
class Stats:
    """剖析计数器（``schedule(..., stats=...)`` 时填充；**不混入正式墙钟**）。"""

    pushes: int = 0
    pops: int = 0
    promotions: int = 0
    front_refreshes: int = 0
    repushes: int = 0
    dispatches: int = 0
    zero_dispatches: int = 0
    delayed_zero_dispatches: int = 0
    slot_assigns: int = 0
    slot_violations: int = 0
    window_releases: int = 0
    activation_acquires: int = 0
    activation_releases: int = 0
    lookahead_branches: int = 0
    lookahead_rollouts: int = 0
    degraded: bool = False
    abort: str = ""
    elapsed: float = 0.0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "pushes": self.pushes,
            "pops": self.pops,
            "promotions": self.promotions,
            "front_refreshes": self.front_refreshes,
            "repushes": self.repushes,
            "dispatches": self.dispatches,
            "zero_dispatches": self.zero_dispatches,
            "delayed_zero_dispatches": self.delayed_zero_dispatches,
            "slot_assigns": self.slot_assigns,
            "slot_violations": self.slot_violations,
            "window_releases": self.window_releases,
            "activation_acquires": self.activation_acquires,
            "activation_releases": self.activation_releases,
            "lookahead_branches": self.lookahead_branches,
            "lookahead_rollouts": self.lookahead_rollouts,
            "degraded": self.degraded,
            "abort": self.abort,
            "elapsed": round(self.elapsed, 6),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class Caps:
    """一个卡组的内存预留：``Mexp + U·cap_comm + Uact·cap_act ≤ M``。"""

    group: int
    mexp: int
    avail: int
    cap_comm: int
    cap_act: int
    need_act: int
    has_zero_comm: bool
    policy: str

    def as_dict(self) -> dict:
        return {
            "group": self.group,
            "mexp": self.mexp,
            "avail": self.avail,
            "cap_comm": self.cap_comm,
            "cap_act": self.cap_act,
            "need_act": self.need_act,
            "has_zero_comm": self.has_zero_comm,
            "policy": self.policy,
            "reserved": self.mexp + self._u_comm * self.cap_comm
            + self._u_act * self.cap_act,
        }

    # 计算 reserved 时需要的 U/Uact 由 :func:`memory_caps` 回填（dataclass 保持轻量）。
    _u_comm: int = 0
    _u_act: int = 0


def _group_mexp(case: Case, plan: Plan, group: int) -> int:
    per_layer = (case.E // plan.P) * case.Z + case.Zs
    return len(plan.layers_of_group[group]) * per_layer


def _group_need_act(case: Case, plan: Plan, group: int) -> int:
    """该卡组至少需要几个激活槽才能推进（保守下界）。

    若卡组内存在**相邻层** ``(ℓ, ℓ+1)``：``disp(ℓ+1)`` 等 ``comb(ℓ)``，而释放 ``ℓ`` 的激活
    又要 ``comb(ℓ+1)``，两者必须同时在世 ⇒ 至少 2 个槽；否则 1 个即可。
    """
    layers = set(plan.layers_of_group[group])
    for layer in layers:
        if layer + 1 < case.L and (layer + 1) in layers:
            return 2
    return 1


def memory_caps(
    case: Case,
    plan: Plan,
    *,
    policy: str = "auto",
    comm_cap: Optional[int] = None,
    act_cap: Optional[int] = None,
) -> Optional[list[Caps]]:
    """推出每个卡组的 ``(cap_comm, cap_act)``；不可行返回 ``None``。

    * ``policy="auto"``：默认给通信 2 个槽（非零通信在闭区间下最坏 2 块）；若该卡组存在
      零时长通信，则把「留够激活槽之后」的剩余内存尽量给通信槽，减少零时长通信被 +1
      拉开的时间代价；
    * ``policy="comm1"/"comm2"/"comm4"``：固定通信槽数（消融 B 用）；
    * ``policy="actmax"``：通信只留 1 槽，其余全给激活；
    * ``comm_cap`` / ``act_cap`` 显式覆盖。

    ``U == 0`` 时通信不占内存，给大槽数；``Uact == 0`` 时激活不占内存。
    ``need_act`` 见 :func:`_group_need_act`；连 ``need_act`` 都放不下时返回 ``None``
    （本地保守口径下该配置不可行，调用方应回退）。
    """
    caps: list[Caps] = []
    for group in range(plan.V):
        mexp = _group_mexp(case, plan, group)
        avail = case.M - mexp
        if avail < 0:
            return None
        need_act = _group_need_act(case, plan, group)
        layers = plan.layers_of_group[group]
        has_zero_comm = any(
            plan.durations[layer][oi] == 0 for layer in layers for oi in COMM_OPS
        )
        max_comm = INF if case.U <= 0 else avail // case.U
        max_act = INF if case.Uact <= 0 else avail // case.Uact
        if comm_cap is not None:
            cap_comm = comm_cap
        elif case.U <= 0:
            cap_comm = INF
        elif policy == "comm1":
            cap_comm = 1
        elif policy == "comm2":
            cap_comm = 2
        elif policy == "comm4":
            cap_comm = 4
        elif policy == "actmax":
            cap_comm = 1
        elif policy == "auto":
            if has_zero_comm:
                if case.Uact <= 0:
                    cap_comm = max_comm
                else:
                    # 至少留 need_act 个激活槽；剩余内存的一半给通信、一半继续留给激活
                    # （纯占满通信会把流水线压到 need_act=1~2 个激活，Time 反而变差）。
                    reserve_act = min(max_act, max(need_act, max_act // 2))
                    spare = avail - case.Uact * reserve_act
                    cap_comm = max(2, spare // case.U) if spare > 0 else 2
            else:
                cap_comm = 2
        else:
            raise ValueError(f"未知 memory policy：{policy!r}")
        cap_comm = min(cap_comm, max_comm)
        if cap_comm < 1:
            return None
        if act_cap is not None:
            cap_act = act_cap
        elif case.Uact <= 0:
            cap_act = INF
        else:
            cap_act = (avail - case.U * cap_comm) // case.Uact
        # 放不下最小激活槽时，逐步让出通信槽（先 1，再失败）。
        while cap_act < need_act and cap_comm > 1:
            cap_comm -= 1
            cap_act = (avail - case.U * cap_comm) // case.Uact if case.Uact > 0 else INF
        if cap_act < need_act:
            return None
        caps.append(
            Caps(
                group=group,
                mexp=mexp,
                avail=avail,
                cap_comm=cap_comm,
                cap_act=cap_act,
                need_act=need_act,
                has_zero_comm=has_zero_comm,
                policy=policy,
                _u_comm=case.U,
                _u_act=case.Uact,
            )
        )
    return caps


# --------------------------------------------------------------------------- #
# 优先级（默认：真实依赖剩余路径；变体：复刻 sched.schedule 的键）
# --------------------------------------------------------------------------- #


def _static_tail(case: Case, plan: Plan) -> list[int]:
    """每个 ``(layer, op)`` 到汇点的最长剩余路径（含本操作时长）。

    依赖图与 `sched._dep_tables` 完全一致（同层 DEPS + 层间前向/反向入口边），只是把
    ``mb`` 维折叠掉——同一 ``base`` 在每个 microbatch 上相同。图无环，Kahn 拓扑序反向
    递推即可。
    """
    L = case.L
    stride = L * 10
    pred, _succ = sched._dep_tables(L)
    succ_static: list[list[int]] = [[] for _ in range(stride)]
    indeg = [0] * stride
    for base in range(stride):
        for offset in pred[base]:
            source = base + offset
            succ_static[source].append(-offset)
            indeg[base] += 1
    order: list[int] = []
    queue = deque(base for base in range(stride) if indeg[base] == 0)
    while queue:
        base = queue.popleft()
        order.append(base)
        for offset in succ_static[base]:
            nxt = base + offset
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    tail = [0] * stride
    for base in reversed(order):
        layer, oi = divmod(base, 10)
        best = 0
        for offset in succ_static[base]:
            value = tail[base + offset]
            if value > best:
                best = value
        tail[base] = plan.durations[layer][oi] + best
    if len(order) != stride:  # pragma: no cover - 依赖图无环
        raise RuntimeError("frontier: 依赖图存在环，无法计算剩余路径")
    return tail


def default_priority(case: Case, plan: Plan) -> list[int]:
    """默认优先级：真实依赖剩余路径（越接近关键路径越优先），再按 ``mb`` / 层 / op。

    优先级只在**同一开始时刻**的候选之间起作用（事件内核先按时间推进）；剩余路径用
    `sched._dep_tables` 的同一张依赖图算出，不额外假设窗口或拓扑。
    """
    L = case.L
    stride = L * 10
    nmb = case.nmb
    tail = _static_tail(case, plan)
    order = sorted(range(stride), key=lambda base: (-tail[base], base // 10, base % 10))
    tail_rank = [0] * stride
    for position, base in enumerate(order):
        tail_rank[base] = position
    rank = [0] * (nmb * stride)
    for mb in range(nmb):
        offset = mb * stride
        for base in range(stride):
            rank[offset + base] = (tail_rank[base] * nmb + mb) * stride + base
    return rank


def variant_priority(
    case: Case, plan: Plan, variant: Sequence[bool]
) -> list[int]:
    """复刻 `sched.schedule` 的 ``(fwd_first, mb_desc, l_desc, l_major)`` 键为整数秩。"""
    L = case.L
    nmb = case.nmb
    stride = L * 10
    fwd_first, mb_desc, l_desc, l_major = variant
    rank = [0] * (nmb * stride)
    for mb in range(nmb):
        mbk = nmb - 1 - mb if mb_desc else mb
        for layer in range(L):
            lk = L - 1 - layer if l_desc else layer
            for oi in range(10):
                head = (0 if fwd_first else 1) if oi <= 3 else (1 if fwd_first else 0)
                if l_major:
                    value = ((head * L + lk) * nmb + mbk) * 10 + oi
                else:
                    value = ((head * nmb + mbk) * L + lk) * 10 + oi
                rank[mb * stride + layer * 10 + oi] = value
    return rank


# --------------------------------------------------------------------------- #
# 内核
# --------------------------------------------------------------------------- #


@dataclass
class _Queue:
    """一个可派发前沿（对应某卡组某套引擎，或 comb 独立队列）。

    ``nz_wait``：依赖已满足但可能还要等引擎的（非零）操作，键 ``(dep_ready, rank, idx)``；
    ``nz_bucket``：``dep_ready ≤ 引擎空闲`` 的操作，键 ``(rank, idx)``；
    ``zero_wait``：零时长操作（不占引擎），键 ``(dep_ready, rank, idx)``。
    """

    qid: int
    group: int
    engine: int
    kind: str  # "comp" | "comm" | "comb"
    nz_wait: list = field(default_factory=list)
    nz_bucket: list = field(default_factory=list)
    zero_wait: list = field(default_factory=list)


class _Kernel:
    """一次事件驱动构造的完整状态；不跨用例复用。"""

    def __init__(
        self,
        case: Case,
        plan: Plan,
        *,
        window: Optional[int],
        variant: Optional[Sequence[bool]],
        priority: Optional[Sequence[int]],
        gating: bool,
        zero_free: bool,
        caps: Optional[list[Caps]],
        delays: Optional[dict[int, int]],
        trace: Optional[list],
        trace_limit: int,
        order: str,
        deadline: Optional[float],
        stats: Stats,
    ) -> None:
        self.case = case
        self.plan = plan
        self.L = case.L
        self.nmb = case.nmb
        self.stride = self.L * 10
        self.total = self.nmb * self.stride
        self.window = window
        self.variant = tuple(variant) if variant is not None else None
        self.gating = gating
        self.zero_free = zero_free
        self.order = order
        if order in ("priority", "lazy_early") and gating:
            raise ValueError(
                f"frontier: order={order!r} 的时间非单调，不能与生命周期门控同用"
            )
        self.delays = delays or {}
        self.trace = trace
        self.trace_limit = trace_limit
        self.deadline = deadline
        self.stats = stats

        self.pred, self.succ = sched._dep_tables(self.L)
        self.base_rem = [len(self.pred[base]) for base in range(self.stride)]
        self.rem = self.base_rem * self.nmb
        self.start = [-1] * self.total
        self.end = [-1] * self.total

        self.durations = plan.durations
        self.group_of = plan.group_of_layer
        self.V = plan.V

        # 每个 base 的静态分类（每 mb 相同）。
        self.eng_of = [ENGINE[base % 10] for base in range(self.stride)]
        self.grp_of = [self.group_of[base // 10] for base in range(self.stride)]
        self.dur_of = [
            self.durations[base // 10][base % 10] for base in range(self.stride)
        ]

        if priority is not None:
            self.ranks = list(priority)
        elif variant is not None:
            self.ranks = variant_priority(case, plan, variant)
        elif gating and min(cap.cap_act for cap in caps) <= 4:
            # 内存极紧时默认「剩余路径」优先级可能把多个 mb 的 layer-0 comb 排在前，
            # 占满激活槽后无法再放下一层 comb（死锁）。此时退回基线最稳的
            # fwd-first / mb-major 顺序；宽松内存仍用剩余路径优先级。
            self.ranks = variant_priority(case, plan, (True, False, False, False))
            self.stats.notes.append("tight-activation: 默认优先级退化为 fwd-first/mb-major")
        else:
            self.ranks = default_priority(case, plan)

        if gating:
            if caps is None:
                raise ValueError("frontier: gating=True 需要 caps")
            self.caps = caps
        else:
            self.caps = [
                Caps(group, _group_mexp(case, plan, group), case.M - _group_mexp(case, plan, group),
                     INF, INF, 1, False, "off", case.U, case.Uact)
                for group in range(self.V)
            ]

        self.free = [[0, 0] for _ in range(self.V)]
        self.work_left = [
            [
                sum(
                    self.durations[layer][oi]
                    for layer in plan.layers_of_group[group]
                    for oi in (COMP_OPS if engine == COMP else COMM_OPS)
                )
                * self.nmb
                for engine in (COMP, COMM)
            ]
            for group in range(self.V)
        ]
        self.live_act = [0] * self.V
        # 激活区间按题面 §4.6 是**双闭** [comb.end, s_bwd.start]：s_bwd 排在 u 时，
        # 该激活在 u 时刻仍占内存，必须等时间严格推进到 u 之后才能释放。
        self.release_heap: list[list[int]] = [[] for _ in range(self.V)]
        self.slot_ends: list[list[int]] = [[] for _ in range(self.V)]

        # 窗口（1F1B 启发式，仅 A 组用于复刻基线口径）。
        self.bw_left = [
            [len(layers) for _ in range(self.nmb)] for layers in plan.layers_of_group
        ]
        self.rel = [[-1] * self.nmb for _ in range(self.V)]
        self.deferred: dict[tuple[int, int], list[int]] = {}

        # 可派发前沿：每卡组 comp / comm(非 comb) / comb 三条队列。
        self.queues: list[_Queue] = []
        self.q_comp: list[_Queue] = []
        self.q_comm: list[_Queue] = []
        self.q_comb: list[_Queue] = []
        for group in range(self.V):
            for kind, engine, target in (
                ("comp", COMP, self.q_comp),
                ("comm", COMM, self.q_comm),
                ("comb", COMM, self.q_comb),
            ):
                queue = _Queue(qid=len(self.queues), group=group, engine=engine, kind=kind)
                self.queues.append(queue)
                target.append(queue)

        self.token = [0] * len(self.queues)
        self.heap: list[tuple] = []
        self.rank_heap: list[tuple] = []
        self.lazy_heap: list[tuple] = []
        self.dep_ready = [0] * self.total
        self.time = 0
        self.time_max = 0
        self.count = 0
        self.abort = ""

        # 初始入口操作（层 0 上无同层前驱的 s / disp）入队；窗口未释放的先进 deferred。
        for mb in range(self.nmb):
            for base in _ENTRY_BASES:
                self._make_ready(mb * self.stride + base)

    # -- 队列 --------------------------------------------------------------- #

    def _queue_of(self, idx: int) -> _Queue:
        base = idx % self.stride
        group = self.grp_of[base]
        if self.eng_of[base] == COMP:
            return self.q_comp[group]
        if base % 10 == OP_COMB:
            return self.q_comb[group]
        return self.q_comm[group]

    def _window_threshold(self, base: int, mb: int) -> Optional[int]:
        """窗口门控：返回该入口操作必须等的 ``mb−W``（不需要等则 ``None``）。"""
        if self.window is None or base not in _ENTRY_BASES:
            return None
        if mb < self.window:
            return None
        return mb - self.window

    def _make_ready(self, idx: int) -> None:
        base = idx % self.stride
        layer, oi = divmod(base, 10)
        mb = idx // self.stride
        group = self.grp_of[base]
        ready = 0
        for offset in self.pred[base]:
            value = self.end[idx + offset]
            if value > ready:
                ready = value
        if self.delays:
            extra = self.delays.get(idx)
            if extra:
                ready += extra
        threshold = self._window_threshold(base, mb)
        if threshold is not None:
            if self.bw_left[group][threshold] > 0:
                self.deferred.setdefault((group, threshold), []).append(idx)
                return
            value = self.rel[group][threshold]
            if value > ready:
                ready = value
        rank = self.ranks[idx]
        if self.order in ("priority", "lazy_early"):
            self.dep_ready[idx] = ready
            if self.order == "priority":
                heapq.heappush(self.rank_heap, (rank, idx))
            else:
                duration = self.dur_of[base]
                free = self.free[self.grp_of[base]][self.eng_of[base]]
                stored = ready
                if duration > 0 or not self.zero_free:
                    if free > stored:
                        stored = free
                heapq.heappush(self.lazy_heap, (stored, rank, idx))
            self.stats.pushes += 1
            return
        duration = self.dur_of[base]
        queue = self._queue_of(idx)
        if duration > 0 or not self.zero_free:
            heapq.heappush(queue.nz_wait, (ready, rank, idx))
        else:
            heapq.heappush(queue.zero_wait, (ready, rank, idx))
        self._touch(queue)

    def _promote(self, queue: _Queue) -> None:
        free = self.free[queue.group][queue.engine]
        wait = queue.nz_wait
        bucket = queue.nz_bucket
        while wait and wait[0][0] <= free:
            _ready, rank, idx = heapq.heappop(wait)
            heapq.heappush(bucket, (rank, idx))
            self.stats.promotions += 1

    def _slot_earliest(self, group: int, point: int) -> int:
        """通信槽（闭区间）在 ``point`` 之后的最早可用时刻。"""
        cap = self.caps[group].cap_comm
        ends = self.slot_ends[group]
        if len(ends) < cap:
            return point
        smallest = ends[0]
        return point if smallest < point else smallest + 1

    def _advance_activation(self, group: int, point: int) -> None:
        """释放 ``s_bwd.start < point`` 的激活（双闭区间：等号时刻仍占内存）。"""
        releases = self.release_heap[group]
        while releases and releases[0] < point:
            heapq.heappop(releases)
            if self.live_act[group] > 0:
                self.live_act[group] -= 1
                self.stats.activation_releases += 1

    def _front(self, queue: _Queue) -> Optional[tuple[int, int, int]]:
        """返回 ``(start, rank, idx)``；``None`` 表示当前无候选（含激活门控满）。"""
        group = queue.group
        if queue.kind == "comb" and self.gating:
            self._advance_activation(group, self.time)
            if self.live_act[group] >= self.caps[group].cap_act:
                return None
        self._promote(queue)
        free = self.free[group][queue.engine]
        best: Optional[tuple[int, int, int]] = None
        if queue.nz_bucket:
            rank, idx = queue.nz_bucket[0]
            best = (free, rank, idx)
        elif queue.nz_wait:
            ready, rank, idx = queue.nz_wait[0]
            best = (ready if ready > free else free, rank, idx)
        if self.zero_free and queue.zero_wait:
            ready, rank, idx = queue.zero_wait[0]
            if ready < self.time:
                ready = self.time
            if best is None or (ready, rank) < (best[0], best[1]):
                best = (ready, rank, idx)
        if best is not None and queue.engine == COMM:
            shifted = self._slot_earliest(group, best[0])
            if shifted != best[0]:
                best = (shifted, best[1], best[2])
        return best

    def _touch(self, queue: _Queue) -> None:
        """刷新一个队列的全局堆项（惰性：只推新令牌，旧项出堆时作废）。"""
        qid = queue.qid
        self.token[qid] += 1
        front = self._front(queue)
        self.stats.front_refreshes += 1
        if front is None:
            return
        start, rank, idx = front
        neg_work = -self.work_left[queue.group][queue.engine]
        heapq.heappush(
            self.heap, (start, neg_work, rank, qid, self.token[qid], idx)
        )
        self.stats.pushes += 1

    # -- 派发 --------------------------------------------------------------- #

    def _select(self) -> Optional[tuple[_Queue, int, int]]:
        """弹出一个全局最早可开工的候选；记录冲突点（供前瞻分支）。"""
        while self.heap:
            entry = heapq.heappop(self.heap)
            self.stats.pops += 1
            start, neg_work, rank, qid, token, idx = entry
            if token != self.token[qid]:
                continue
            queue = self.queues[qid]
            front = self._front(queue)
            if front is None:
                continue
            current = (front[0], -self.work_left[queue.group][queue.engine], front[1], front[2])
            if current != (start, neg_work, rank, idx):
                self._touch(queue)
                continue
            if self.trace is not None and len(self.trace) < self.trace_limit:
                self._record_trace(start, idx)
            self._take(queue, idx)
            return queue, idx, start
        return None

    def _take(self, queue: _Queue, idx: int) -> None:
        """把选中的操作从它所在队列的队首弹出（`_front` 只看队首）。"""
        bucket = queue.nz_bucket
        if bucket and bucket[0][1] == idx:
            heapq.heappop(bucket)
            return
        zero = queue.zero_wait
        if zero and zero[0][2] == idx:
            heapq.heappop(zero)
            return
        wait = queue.nz_wait
        if wait and wait[0][2] == idx:
            heapq.heappop(wait)
            return
        raise RuntimeError(f"frontier: 选中的操作 {idx} 不在队列 {queue.qid} 队首")

    def _record_trace(self, start: int, chosen: int) -> None:
        """记录同一时刻的其它候选（不含被选中的），最多 3 个。"""
        alternatives: list[int] = []
        for queue in self.queues:
            if len(alternatives) >= 3:
                break
            front = self._front(queue)
            if front is None or front[0] != start or front[2] == chosen:
                continue
            if front[2] not in alternatives:
                alternatives.append(front[2])
        if alternatives:
            self.trace.append((start, chosen, alternatives))

    def _dispatch(self, queue: Optional[_Queue], idx: int, start: int) -> None:
        base = idx % self.stride
        layer, oi = divmod(base, 10)
        mb = idx // self.stride
        group = self.grp_of[base]
        duration = self.dur_of[base]
        engine = self.eng_of[base]
        finish = start + duration
        self.start[idx] = start
        self.end[idx] = finish
        self.time = start
        if finish > self.time_max:
            self.time_max = finish
        self.count += 1
        self.stats.dispatches += 1

        if duration > 0:
            if engine == COMM:
                self._assign_slot(group, start, finish)
                if finish > self.free[group][engine]:
                    self.free[group][engine] = finish
            else:
                if finish > self.free[group][engine]:
                    self.free[group][engine] = finish
            self.work_left[group][engine] -= duration
        else:
            self.stats.zero_dispatches += 1
            if engine == COMM:
                self._assign_slot(group, start, start)

        if self.gating:
            if oi == OP_COMB:
                self.live_act[group] += 1
                self.stats.activation_acquires += 1
            elif oi == OP_S_BWD:
                heapq.heappush(self.release_heap[group], start)

        if self.window is not None and oi == OP_S_BWD:
            left = self.bw_left[group][mb] - 1
            self.bw_left[group][mb] = left
            if finish > self.rel[group][mb]:
                self.rel[group][mb] = finish
            if left == 0:
                self.stats.window_releases += 1
                next_mb = mb + self.window
                if next_mb < self.nmb:
                    for deferred in self.deferred.pop((group, next_mb), ()):
                        self._make_ready(deferred)

        for offset in self.succ[base]:
            successor = idx + offset
            remaining = self.rem[successor] - 1
            self.rem[successor] = remaining
            if remaining == 0:
                self._make_ready(successor)

        if self.order == "time":
            assert queue is not None
            self._touch(queue)
            if engine == COMM:
                sibling = self.q_comm[group] if queue.kind == "comb" else self.q_comb[group]
                self._touch(sibling)
            if self.gating and oi in (OP_COMB, OP_S_BWD):
                self._touch(self.q_comb[group])

    def _assign_slot(self, group: int, start: int, finish: int) -> None:
        cap = self.caps[group].cap_comm
        ends = self.slot_ends[group]
        self.stats.slot_assigns += 1
        if ends and ends[0] < start:
            heapq.heapreplace(ends, finish)
            return
        if len(ends) < cap:
            heapq.heappush(ends, finish)
            return
        # 理论上 `_front` 已保证可用；走到这里说明门控与派发不一致（记录后仍按最早槽放）。
        self.stats.slot_violations += 1
        heapq.heapreplace(ends, finish)

    # -- 主循环 ------------------------------------------------------------- #

    def run(self) -> Optional[sched.Schedule]:
        if self.order == "priority":
            return self._run_priority()
        if self.order == "lazy_early":
            return self._run_lazy_early()
        for queue in self.queues:
            self._touch(queue)
        while self.count < self.total:
            if self.deadline is not None and (self.count & 0x3FF) == 0:
                if _time.monotonic() > self.deadline:
                    self.abort = "deadline"
                    return None
            selected = self._select()
            if selected is None:
                advanced = False
                if self.gating:
                    waits = [heap[0] for heap in self.release_heap if heap]
                    if waits:
                        # 只剩「激活还差一个单位才释放」：时间推进到释放之后再看，
                        # 不派发任何操作（有意义的“等到下一有效事件”）。
                        point = min(waits) + 1
                        if point > self.time:
                            self.time = point
                            for group in range(self.V):
                                self._advance_activation(group, self.time)
                            for queue in self.queues:
                                self._touch(queue)
                            advanced = True
                if advanced:
                    continue
                self.abort = "deadlock"
                return None
            queue, idx, start = selected
            self._dispatch(queue, idx, start)
        return self._result()

    def _result(self) -> sched.Schedule:
        return sched.Schedule(
            time=self.time_max,
            start=self.start,
            end=self.end,
            window=self.window if self.window is not None else self.nmb,
            variant=self.variant if self.variant is not None else (True, False, False, False),
        )

    def _run_priority(self) -> Optional[sched.Schedule]:
        """按优先级出堆（等价于基线 ``prio`` 的**延迟**派发：允许引擎先空着等关键操作）。

        时间不再单调，因此只允许 ``gating=False``（内存由调用方 `sched.memory_usage` 复核）；
        零时长操作仍按 ``zero_free`` 决定是否等引擎。该路径用于 A 组对 ``prio`` 的等价对照，
        以及 C 组前瞻里的「延迟派发」分支。
        """
        heap = self.rank_heap
        while self.count < self.total:
            if self.deadline is not None and (self.count & 0x3FF) == 0:
                if _time.monotonic() > self.deadline:
                    self.abort = "deadline"
                    return None
            if not heap:
                self.abort = "deadlock"
                return None
            _rank, idx = heapq.heappop(heap)
            self.stats.pops += 1
            base = idx % self.stride
            group = self.grp_of[base]
            engine = self.eng_of[base]
            duration = self.dur_of[base]
            start = self.dep_ready[idx]
            if duration > 0 or not self.zero_free:
                free = self.free[group][engine]
                if free > start:
                    start = free
            self._dispatch(None, idx, start)
        return self._result()

    def _run_lazy_early(self) -> Optional[sched.Schedule]:
        """逐条复刻基线 ``mode="early"`` 的惰性修正语义（用于等价性/重入堆计数）。

        基线只在 ``实际开始 > 堆顶存储时刻`` 时把操作重排回堆；这里逐句照做，并统计
        ``repushes``。它**不是**本模块推荐的事件内核（仍可能二次重入），只作为 A 组
        等价性与剖析的“基线替身”。
        """
        heap = self.lazy_heap
        while self.count < self.total:
            if self.deadline is not None and (self.count & 0x3FF) == 0:
                if _time.monotonic() > self.deadline:
                    self.abort = "deadline"
                    return None
            if not heap:
                self.abort = "deadlock"
                return None
            _stored, rank, idx = heapq.heappop(heap)
            self.stats.pops += 1
            base = idx % self.stride
            group = self.grp_of[base]
            engine = self.eng_of[base]
            duration = self.dur_of[base]
            ready = self.dep_ready[idx]
            if duration > 0 or not self.zero_free:
                free = self.free[group][engine]
                if free > ready:
                    ready = free
            if heap and ready > heap[0][0]:
                heapq.heappush(heap, (ready, rank, idx))
                self.stats.repushes += 1
                continue
            self._dispatch(None, idx, ready)
        return self._result()


# --------------------------------------------------------------------------- #
# 对外入口
# --------------------------------------------------------------------------- #


def _greedy(
    case: Case,
    plan: Plan,
    *,
    window: Optional[int],
    variant: Optional[Sequence[bool]],
    priority: Optional[Sequence[int]],
    gating: bool,
    zero_free: bool,
    policy: str,
    comm_cap: Optional[int],
    act_cap: Optional[int],
    delays: Optional[dict[int, int]],
    trace: Optional[list],
    trace_limit: int,
    order: str,
    deadline: Optional[float],
    stats: Stats,
) -> Optional[sched.Schedule]:
    caps = None
    if gating:
        caps = memory_caps(case, plan, policy=policy, comm_cap=comm_cap, act_cap=act_cap)
        if caps is None:
            stats.abort = "memory-infeasible"
            return None
    kernel = _Kernel(
        case,
        plan,
        window=window,
        variant=variant,
        priority=priority,
        gating=gating,
        zero_free=zero_free,
        caps=caps,
        delays=delays,
        trace=trace,
        trace_limit=trace_limit,
        order=order,
        deadline=deadline,
        stats=stats,
    )
    try:
        result = kernel.run()
    except Exception:  # pragma: no cover - 内核 bug 时也不返回半份
        stats.abort = "exception"
        raise
    stats.abort = kernel.abort
    return result


def schedule(
    case: Case,
    plan: Plan,
    *,
    window: Optional[int] = None,
    deadline: Optional[float] = None,
    seed: int = 20261020,
    variant: Optional[Sequence[bool]] = None,
    mode: str = "event",
    lookahead: int = 0,
    zero_free: bool = True,
    gating: bool = True,
    policy: str = "auto",
    comm_cap: Optional[int] = None,
    act_cap: Optional[int] = None,
    priority: Optional[Sequence[int]] = None,
    trace_limit: int = 0,
    order: str = "time",
    stats: Optional[Stats] = None,
) -> Optional[sched.Schedule]:
    """事件驱动就绪前沿调度（稳定接口，见协议 §11.2）。

    参数
    ----
    window
        ``None`` = 不设 ``mb−W`` 窗口（B/C 默认）；整数 = 复刻基线 1F1B 窗口（A 组用）。
    variant
        基线的 ``(fwd_first, mb_desc, l_desc, l_major)`` 优先键；``None`` = 默认
        「真实依赖剩余路径」优先。
    mode
        ``"event"``（单次贪心事件内核）或 ``"lookahead"``（有界前瞻/束搜索）。
    lookahead
        前瞻模式的分支上限（0 表示沿用 ``mode`` 默认值）；见 :func:`_lookahead`。
    zero_free
        ``True``：零时长操作不占引擎、依赖满足即可执行（题面/官方语义）；``False``：
        复刻旧 `sched.schedule` 的 ``max(引擎空闲)`` 行为（消融用）。
    gating
        ``True``：生命周期内存门控（通信槽 + 激活槽）；``False``：不门控（A 组）。
    policy / comm_cap / act_cap
        内存预留拆分策略，见 :func:`memory_caps`。
    priority
        显式整数秩（逐节点）；``None`` 时按 ``variant`` 或默认剩余路径生成。
    trace_limit
        > 0 时收集冲突点（同一时刻的其它候选），供前瞻分支；不改变调度本身。
    stats
        :class:`Stats`，填充剖析计数器；不影响调度。

    返回
    ----
    `sched.Schedule` 或 ``None``。``None`` 只表示死锁/内存不可行/预算内无完整解，
    **绝不返回半份调度**；调用方必须回退到完整合法 incumbent。
    """
    started = _time.monotonic()
    stats = stats if stats is not None else Stats()
    trace: Optional[list] = ([] if trace_limit > 0 else None)

    base = _greedy(
        case,
        plan,
        window=window,
        variant=variant,
        priority=priority,
        gating=gating,
        zero_free=zero_free,
        policy=policy,
        comm_cap=comm_cap,
        act_cap=act_cap,
        delays=None,
        trace=trace,
        trace_limit=trace_limit,
        order=order,
        deadline=deadline,
        stats=stats,
    )
    if base is None and gating and variant is None and priority is None:
        # 死锁兜底：默认优先级在极紧内存上可能选错 comb 顺序；换一次 fwd-first/mb-major。
        retry_stats = Stats()
        base = _greedy(
            case, plan, window=window, variant=(True, False, False, False),
            priority=None, gating=gating, zero_free=zero_free, policy=policy,
            comm_cap=comm_cap, act_cap=act_cap, delays=None, trace=trace,
            trace_limit=trace_limit, order=order, deadline=deadline,
            stats=retry_stats,
        )
        if base is not None:
            stats.notes.append("deadlock fallback: fwd-first/mb-major 优先级")
            stats.abort = ""
    if base is None or mode == "event":
        stats.elapsed = _time.monotonic() - started
        return base
    if mode != "lookahead":
        raise ValueError(f"未知 mode：{mode!r}（只支持 event / lookahead）")

    best = _lookahead(
        case,
        plan,
        base,
        trace or [],
        window=window,
        variant=variant,
        priority=priority,
        gating=gating,
        zero_free=zero_free,
        policy=policy,
        comm_cap=comm_cap,
        act_cap=act_cap,
        order=order,
        deadline=deadline,
        seed=seed,
        width=lookahead,
        stats=stats,
    )
    stats.elapsed = _time.monotonic() - started
    return best


def _lookahead(
    case: Case,
    plan: Plan,
    base: sched.Schedule,
    trace: list,
    *,
    window: Optional[int],
    variant: Optional[Sequence[bool]],
    priority: Optional[Sequence[int]],
    gating: bool,
    zero_free: bool,
    policy: str,
    comm_cap: Optional[int],
    act_cap: Optional[int],
    order: str,
    deadline: Optional[float],
    seed: int,
    width: int,
    stats: Stats,
) -> sched.Schedule:
    """有界前瞻：对基线解里的冲突点做「换派发 / 暂时等待」的一步分支 + 贪心 rollout。

    只做**一步**偏离再让事件内核跑完（rollout），代价是一次 ``O(n log n)``；因此
    必须限制冲突点数/分支数，并在大用例上直接降级（``stats.degraded = True``）。
    这既包含「换一个同刻候选」，也包含「同刻全部暂时等待、让时间推进到下一有效事件」
    的有意义等待分支；不做全状态束搜索，避免复制成本失控。
    """
    width = max(1, width or 4)
    # 大规模自动降级：一次事件内核就要 0.2–1 s，不能做多分支 rollout。
    if case.n_ops > 120_000:
        stats.degraded = True
        stats.notes.append(
            f"lookahead degraded: n_ops={case.n_ops} > 120000 (width={width})"
        )
        return base
    best = base

    def _accept(candidate: Optional[sched.Schedule], label: str) -> None:
        nonlocal best
        if candidate is None or candidate.time >= best.time:
            return
        ok, _groups = sched.memory_usage(case, plan, candidate.start, candidate.end)
        if ok:
            best = candidate
            stats.notes.append(f"lookahead {label}: → {candidate.time}")

    # ---- 分支 1：延迟派发（优先级出堆；含「引擎先空着、等关键操作」的等待语义） ----
    # 这是与时间前沿解**不同**的派发规则；只在内存复核通过时接受。
    if case.n_ops <= 20_000:
        rules: list[tuple[str, Optional[Sequence[int]]]] = [("critical", None)]
        rules += [(f"variant{index}", variant_priority(case, plan, variant))
                  for index, variant in enumerate(sched.VARIANTS)]
        for label, rule in rules:
            if deadline is not None and _time.monotonic() > deadline:
                stats.notes.append("lookahead deadline 截断（延迟派发分支）")
                return best
            if stats.lookahead_rollouts >= 6 + width * 3:
                break
            roll_stats = Stats()
            candidate = _greedy(
                case,
                plan,
                window=None,
                variant=None,
                priority=rule,
                gating=False,
                zero_free=True,
                policy=policy,
                comm_cap=comm_cap,
                act_cap=act_cap,
                delays=None,
                trace=None,
                trace_limit=0,
                order="priority",
                deadline=deadline,
                stats=roll_stats,
            )
            stats.lookahead_rollouts += 1
            stats.lookahead_branches += 1
            _accept(candidate, f"priority/{label}")
    else:
        stats.degraded = True
        stats.notes.append(
            f"lookahead degraded: n_ops={case.n_ops} > 20000，只做关键路径延迟派发分支"
        )
        roll_stats = Stats()
        candidate = _greedy(
            case, plan, window=None, variant=None, priority=None, gating=False,
            zero_free=True, policy=policy, comm_cap=comm_cap, act_cap=act_cap,
            delays=None, trace=None, trace_limit=0, order="priority",
            deadline=deadline, stats=roll_stats,
        )
        stats.lookahead_rollouts += 1
        stats.lookahead_branches += 1
        _accept(candidate, "priority/critical")

    if not trace:
        stats.notes.append("lookahead: 无冲突点，跳过等待分支")
        return best

    points = 0
    branches = 0
    # 固定顺序 + 固定 seed：候选序列在固定迭代上限下确定；deadline 只会截断。
    _ = seed
    for start, chosen, alternatives in trace:
        if points >= 6 or branches >= width * 4:
            break
        points += 1
        candidates = [chosen] + alternatives[:2]
        plans: list[dict[int, int]] = []
        for alt in candidates:
            if alt == chosen:
                continue
            plans.append({idx: 1 for idx in candidates if idx != alt})
        if len(candidates) > 1:
            plans.append({idx: 1 for idx in candidates})  # 同刻全部等待
        for delays in plans:
            if branches >= width * 4:
                break
            if deadline is not None and _time.monotonic() > deadline:
                stats.notes.append("lookahead deadline 截断")
                return best
            branches += 1
            stats.lookahead_branches += 1
            roll_stats = Stats()
            candidate = _greedy(
                case,
                plan,
                window=window,
                variant=variant,
                priority=priority,
                gating=gating,
                zero_free=zero_free,
                policy=policy,
                comm_cap=comm_cap,
                act_cap=act_cap,
                delays=delays,
                trace=None,
                trace_limit=0,
                order=order,
                deadline=deadline,
                stats=roll_stats,
            )
            stats.lookahead_rollouts += 1
            if candidate is None:
                continue
            if candidate.time < best.time:
                ok, _groups = sched.memory_usage(case, plan, candidate.start, candidate.end)
                if ok:
                    best = candidate
    stats.notes.append(
        f"lookahead: points={points} branches={branches} base={base.time} best={best.time}"
    )
    return best


# --------------------------------------------------------------------------- #
# 固定配置下的候选扫描（工具/生产接入共用；返回**已验证内存**的最好解）
# --------------------------------------------------------------------------- #


def _default_windows(case: Case, plan: Plan, limit: int = 4) -> list[int]:
    """窗口候选（从大到小）：nmb, nmb/2, nmb/4, nmb/8, 1；大用例只留前 ``limit`` 个。"""
    nmb = case.nmb
    values: list[int] = []
    for numerator, denominator in ((1, 1), (1, 2), (1, 4), (1, 8)):
        value = max(1, nmb * numerator // denominator)
        if value not in values:
            values.append(value)
    if 1 not in values:
        values.append(1)
    return values[:limit]


def _merge_stats(target: Stats, source: Stats) -> None:
    """把被接受候选的剖析计数并入外层（``pushes/pops/...`` 逐项相加）。"""
    for name in (
        "pushes", "pops", "promotions", "front_refreshes", "repushes", "dispatches",
        "zero_dispatches", "slot_assigns", "slot_violations", "window_releases",
        "activation_acquires", "activation_releases", "lookahead_branches",
        "lookahead_rollouts",
    ):
        setattr(target, name, getattr(target, name) + getattr(source, name))
    target.degraded = target.degraded or source.degraded
    if source.abort:
        target.abort = source.abort
    for note in source.notes:
        if note not in target.notes:
            target.notes.append(note)


def _accept_candidate(
    case: Case,
    plan: Plan,
    candidate: Optional[sched.Schedule],
    best: Optional[sched.Schedule],
    stats: Stats,
    candidate_stats: Optional[Stats] = None,
) -> Optional[sched.Schedule]:
    """只在**严格更好**时做内存核算；非法/超内存直接丢弃。"""
    if candidate is None:
        if candidate_stats is not None:
            _merge_stats(stats, candidate_stats)
        return best
    if best is not None and candidate.time >= best.time:
        return best
    ok, _groups = sched.memory_usage(case, plan, candidate.start, candidate.end)
    if candidate_stats is not None:
        _merge_stats(stats, candidate_stats)
    if not ok:
        stats.notes.append(f"拒绝超内存候选 Time={candidate.time}")
        return best
    if best is None or candidate.time < best.time:
        stats.notes.append(f"接受候选 Time={candidate.time}")
        return candidate
    return best


def search(
    case: Case,
    plan: Plan,
    *,
    strategy: str = "B",
    windows: Optional[Sequence[int]] = None,
    deadline: Optional[float] = None,
    seed: int = 20261020,
    log=None,
    stats: Optional[Stats] = None,
    variant_set: Optional[Sequence[Sequence[bool]]] = None,
    policies: Optional[Sequence[str]] = None,
) -> Optional[sched.Schedule]:
    """在同一 ``(V,P,K,ψ,MAP)`` 下扫候选，返回**内存已复核**的最好调度或 ``None``。

    * ``strategy="A"``：只用事件内核（不门控）——时间前沿 + 优先级出堆两条路径、
      ``zero_free`` 两态、同窗口/同变体集；用于和基线列表调度做等价/加速对照。
    * ``strategy="B"``：去掉 ``mb−W`` 窗口，生命周期内存门控 + 多预留策略。
    * ``strategy="C"``：B 的最优解上再做有界前瞻（延迟派发 + 同刻等待分支）。
    * ``strategy="auto"``：B → C（有剩余预算时）。

    ``deadline`` 是 ``time.monotonic()`` 绝对时刻；到点后不再开新候选，已得到的合法解
    照常返回。返回 ``None`` 只表示没有任何合法候选。
    """
    stats = stats if stats is not None else Stats()
    variant_set = list(
        variant_set
        if variant_set is not None
        else (sched._SMALL_VARIANTS if case.n_ops > 20_000 else sched.VARIANTS)
    )
    if strategy in ("A", "A0", "A1"):
        windows = list(windows) if windows is not None else _default_windows(case, plan, 4)
        zero_states = (False, True) if strategy == "A" else ((strategy == "A1"),)
        best: Optional[sched.Schedule] = None
        for window in windows:
            for variant in variant_set:
                for zero_free in zero_states:
                    if deadline is not None and _time.monotonic() > deadline:
                        stats.notes.append("search A: deadline 截断")
                        return best
                    cand_stats = Stats()
                    candidate = schedule(
                        case, plan, window=window, variant=variant, gating=False,
                        zero_free=zero_free, order="time", deadline=deadline,
                        stats=cand_stats,
                    )
                    best = _accept_candidate(case, plan, candidate, best, stats, cand_stats)
                if deadline is not None and _time.monotonic() > deadline:
                    return best
                cand_stats = Stats()
                candidate = schedule(
                    case, plan, window=window, variant=variant, gating=False,
                    zero_free=False, order="priority", deadline=deadline, stats=cand_stats,
                )
                best = _accept_candidate(case, plan, candidate, best, stats, cand_stats)
        return best

    if strategy not in ("B", "C", "auto"):
        raise ValueError(f"未知 strategy：{strategy!r}")
    if policies is None:
        policies = ("auto", "comm1", "comm2") if case.n_ops <= 20_000 else ("auto", "comm1")
    best = None
    variants = [None] + variant_set
    for policy in policies:
        for variant in variants:
            if deadline is not None and _time.monotonic() > deadline:
                stats.notes.append("search B: deadline 截断")
                return best
            cand_stats = Stats()
            candidate = schedule(
                case, plan, window=None, variant=variant, gating=True, zero_free=True,
                policy=policy, order="time", deadline=deadline, stats=cand_stats,
            )
            best = _accept_candidate(case, plan, candidate, best, stats, cand_stats)
    if best is None:
        return None
    if strategy in ("C", "auto"):
        if deadline is not None and _time.monotonic() > deadline:
            stats.notes.append("search C: 无剩余预算")
            return best
        lookahead_stats = Stats()
        improved = schedule(
            case, plan, window=None, gating=True, zero_free=True, policy=policies[0],
            mode="lookahead", lookahead=4, deadline=deadline, seed=seed,
            stats=lookahead_stats,
        )
        stats.notes.extend(lookahead_stats.notes)
        stats.lookahead_branches += lookahead_stats.lookahead_branches
        stats.lookahead_rollouts += lookahead_stats.lookahead_rollouts
        stats.degraded = stats.degraded or lookahead_stats.degraded
        best = _accept_candidate(case, plan, improved, best, stats)
    return best


# --------------------------------------------------------------------------- #
# 输出解析（固定基线配置用；独立实现，不依赖 judge）
# --------------------------------------------------------------------------- #


def parse_schedule_config(text: str, case: Case) -> dict:
    """从一份**合法输出**里取出 ``V/P/K/psi/MAP``，供固定配置对照。

    只解析结构，不判合法性；字段缺失或数量不符直接抛 ``ValueError``。
    """
    lines = [line.rstrip("\n") for line in text.splitlines()]
    index = 0

    def take() -> str:
        nonlocal index
        if index >= len(lines):
            raise ValueError("输出缺少行")
        value = lines[index]
        index += 1
        return value

    grid = take().split()
    if len(grid) != 2:
        raise ValueError(f"第一行应为 V P，得到 {grid!r}")
    V, P = int(grid[0]), int(grid[1])
    if take().strip() != "PSI":
        raise ValueError("缺少 PSI 行")
    psi_tokens = take().split()
    K = int(psi_tokens[0])
    psi = tuple(int(value) for value in psi_tokens[1:])
    if len(psi) != K - 1:
        raise ValueError(f"K={K} 需要 {K - 1} 个切点，得到 {len(psi)}")
    if take().strip() != "MAP":
        raise ValueError("缺少 MAP 行")
    rows: list[tuple[int, ...]] = []
    for _layer in range(case.L):
        row = tuple(int(value) for value in take().split())
        if len(row) != case.E:
            raise ValueError(f"MAP 行需要 E={case.E} 个值，得到 {len(row)}")
        rows.append(row)
    if take().strip() != "SCHEDULE":
        raise ValueError("缺少 SCHEDULE 行")
    return {"V": V, "P": P, "K": K, "psi": psi, "map_rows": rows}
