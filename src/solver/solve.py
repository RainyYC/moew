"""搜索主流程（报告 §2.1/§2.6）：网格枚举 → 切层候选 → 窗口/变体扫描 → 局部搜索 → 取最优。

搜索空间
--------
* **P**（专家并行）：``P∣E``、``P∣R``、``P∣S`` 或 ``S∣P``；
* **V**（stage 数）：``V ∣ R/P`` 且 ``V ≤ L``；本求解器只产 ``K=V``（每卡组一块，题面
  §3.1 的默认配对），``D = R/(P·V)``；
* **ψ**（切层）：`solver.psi.psi_candidates`（``dp_split2`` + 只按计算 / 只按通信 +
  按层数均分及 ±1 微移）；
* **MAP**：`solver.place.best_placement`（逐层取 LPT / 顺序 / 换位下降里 ``m_l`` 最小者）；
* **W / 变体 / 出堆模式**：`solver.sched` 的窗口候选 × 优先级变体 × (prio|early)；
* **引擎序列局部搜索**：在贪心结果上用模拟退火改进「每个卡组每套引擎上的操作顺序」
  （报告 §2.4 的优先级变体只能换拓扑，这里再往下挖一层）。

剪枝与预算
----------
* ``Mexp > M`` 的 (P,V,ψ) 直接丢弃（静态参数就放不下）；
* 按 ``lb = max_v nmb·max(ΣC_v, ΣWc_v)`` 升序评估；一旦 ``lb ≥ best.time`` 就整体停止
  （后面只会更差）；``best.time == lb`` 时直接判定已达下界，不再做局部搜索；
* 每个候选先看 Time，**只在 Time 优于当前最优时才做内存核算**（报告 §4 第 23 条的
  fast_eval 思路），内存超限则换下一个窗口；
* 全程受 ``budget`` 墙钟约束；即使搜索被截断，也返回**当前最好的合法解**（回退逻辑）。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, Optional

from . import exact as exact_mod, formula, place, psi as psi_mod, sched
from .casein import Case
from .formula import COMM_OPS, COMP_OPS

__all__ = ["Solution", "Config", "solve_case", "p_candidates", "divisors"]

Log = Optional[Callable[[str], None]]

#: 中等规模大用例的**探窗**锚点 ``W = nmb // k``（去重保序，最多 :data:`_PROBE_SHOTS` 个）。
#: 前两个与旧版一致（``nmb``、``nmb/8``，保证 b11 这类"W=nmb/8 最好"的用例不退化、也不
#: 丢掉旧探窗会探到的点）；其后补 ``nmb/32, nmb/2, nmb/5, nmb/3, ...``：实测最优窗口常在
#: nmb/3–nmb/8 之间（b13：W=20 ≈ nmb/5 是 1.186×lb，而 nmb/8=12 是 1.443×lb）。只探
#: 第一个没被整体砍掉不影响"两个比例都探到"，探一次 ≈ 0.1 s。
_PROBE_DIVISORS = (1, 8, 32, 2, 5, 3, 4, 6)
_PROBE_SHOTS = 4
_PROBE_SHOTS_WIDE = 4
#: 一轮"窗口 × 模式"探窗的调度次数上限（按 :func:`_probe_eval_budget` 再截断）。
_PROBE_MAX_EVALS = 12
#: 前几个探窗窗口把 `prio`/`early` 都试一遍（其余窗口只用定位模式）。
_PROBE_PAIRS = 2
#: 普通预算下最多探几个"中等窗口"（宽形状再多一个：见 `_PROBE_SHOTS_WIDE`）。
_PROBE_MAX_MID = 2
#: 探窗之后，用完整变体集再扫的窗口数（探窗最优的那一个 + 更大的几个）。
_SCAN_EXTRA_WINDOWS = 3
#: 探窗定位在 `early` 时，第一段（只换窗口、不换变体）的时间上限。之后再回来扫 `prio`，
#: 两级都受 `deadline` 约束；这一项只决定"先花多少时间在 `early` 上"。
#: 64k op 的用例单次 `early` ≈ 0.2 s，1.8 s ≈ 9 次。
_EARLY_PHASE_SECONDS = 1.8
#: 中等规模（探窗启用）的 op 上限。与 :func:`solve_case` 里 ``big`` 的阈值保持一致：
#: 120k 以内单次调度 ~0.2–0.7 s，探几次窗口是划算的；再大就只能跑几条 ``prio``。
_PROBE_MAX_OPS = 120_000

#: 局部搜索的总工作量上限（≈ 试次数 × 操作数），按用例规模换算成试次数。
_SEARCH_WORK = 2_500_000
_MAX_TRIALS = 200_000
_MIN_TRIALS = 1_500


@dataclass
class Solution:
    """一份求解结果（含生成文本与静态信息，便于 solve_all 汇总）。"""

    text: str
    time: int
    lb: int
    V: int
    P: int
    D: int
    K: int
    psi: tuple[int, ...]
    window: int
    variant: tuple[bool, bool, bool, bool]
    mode: str
    elapsed: float
    groups: list[sched.GroupMemory]
    exact_stats: Optional[dict] = None
    frontier_stats: Optional[dict] = None

    @property
    def grid(self) -> tuple[int, int, int]:
        return (self.V, self.P, self.D)


@dataclass(frozen=True)
class Config:
    """一个 (P, V, D, ψ) 候选。"""

    P: int
    V: int
    D: int
    psi: tuple[int, ...]
    lb: int
    # 只用于排序的下界（用 LPT 的 m 算），见 place.best_placement_split 的说明
    lb_rank: int = 0


@dataclass
class _PMap:
    """与 P 相关、与 (V,D) 无关的逐层量。"""

    P: int
    pin: int
    pout: int
    rows: list[tuple[int, ...]]
    m: list[int]
    payload: list[int]
    x: list[int]
    durations: list[tuple[int, ...]]
    # 只用 LPT 的 m 算出来的时长，仅用于**候选排序**（见 place.best_placement_split）
    durations_rank: list[tuple[int, ...]] | None = None


@dataclass
class _Best:
    """搜索过程中的当前最优（保留 plan / 调度对象，供局部搜索继续改进）。"""

    time: int
    lb: int
    plan: formula.Plan
    rows: list[tuple[int, ...]]
    config: Config
    result: sched.Schedule
    groups: list[sched.GroupMemory]
    mode: str


def divisors(n: int) -> list[int]:
    """``n`` 的正因子（升序）。"""
    out: list[int] = []
    index = 1
    while index * index <= n:
        if n % index == 0:
            out.append(index)
            if index != n // index:
                out.append(n // index)
        index += 1
    out.sort()
    return out


def p_candidates(case: Case) -> list[int]:
    """合法的专家并行度 P（题面 §4.7.1）。"""
    out: list[int] = []
    for P in range(1, min(case.E, case.R) + 1):
        if case.E % P:
            continue
        if case.R % P:
            continue
        if not (case.S % P == 0 or P % case.S == 0):
            continue
        out.append(P)
    return out


def _pmap(case: Case, P: int, budget_box: list[float] | None = None) -> _PMap:
    rows, m, m_rank = place.best_placement_split(case, P, budget_box)
    pin, pout = formula.peer_counts(case, 1, P)
    payload = [formula.comm_payload(case, layer, P) for layer in range(case.L)]
    x = [formula.comm_time(case, payload[layer], pin, pout) for layer in range(case.L)]
    durations = [
        formula.layer_durations(case, layer, m[layer], x[layer]) for layer in range(case.L)
    ]
    durations_rank = [
        formula.layer_durations(case, layer, m_rank[layer], x[layer]) for layer in range(case.L)
    ]
    return _PMap(P=P, pin=pin, pout=pout, rows=rows, m=m, payload=payload, x=x,
                 durations=durations, durations_rank=durations_rank)


def v_candidates(case: Case, P: int) -> list[int]:
    """给定 P 时的 V 候选（降序，首个恒为 vmax = ``min(L, 64, R//P)``）。

    卡是"免费"的：加大 V 让每个卡组少背几层（``lb`` 下降），代价是流水线填充
    ``(nmb+V-1)/nmb``。对固定的 ``nmb``，流水线项 ``(nmb+V-1)/V`` 对 V 单调递减，
    所以 ``V=vmax`` 永远是**首选**（电池 13 例的 ``nmb`` 都 ≥102，实测缩 V 全是坏方向）。
    但题面 §6 不限制 ``nmb`` 与 ``L`` 的组合：``L=64, nmb=2`` 时 ``V=64`` 的填充是 32.5×，
    小 V 反而更好（``runs/score-strategy-20261030/probe_hidden_risk.json``）。
    因此只在 ``2·nmb < vmax``（填充惩罚 > 2×）时补加 ``vmax/2, vmax/4, vmax/8, 1``；
    其余情况候选集与旧版逐字节相同。
    """
    vmax = min(case.L, 64, case.R // P)
    out = [vmax]
    if 2 * case.nmb < vmax:
        for div in (2, 4, 8):
            v = max(1, vmax // div)
            if v not in out:
                out.append(v)
        if 1 not in out:
            out.append(1)
    return out


def k2v_candidates(
    case: Case, V: int, comp: Sequence[int], comm: Sequence[int]
) -> list[tuple[int, ...]]:
    """``K=2V``（DualPipe 镜像配对）的切点候选。

    块 ``k`` 与块 ``2V-1-k`` 同属卡组 ``k``：每个卡组各持一块靠前的、一块靠后的，
    于是一块可以跑前向、另一块同时跑另一个 microbatch 的反向。``group_layers`` /
    ``group_of_layer`` 本来就是按这条镜像规则写的，所以只差"把层切成 ``2V`` 段"。

    只做两种切法——负载均衡的 ``dp_split``（两条链一起）与按层数均分：配对本身已经把
    "早段 + 晚段"的负载拉平，切法再花哨收益有限。
    """
    if 2 * V > case.L:
        return []
    out: list[tuple[int, ...]] = []
    for cuts in (
        psi_mod.dp_split(case.L, 2 * V, comp, comm),
        psi_mod.balanced_split(case.L, 2 * V),
    ):
        if cuts is None or len(cuts) != 2 * V - 1:
            continue
        if cuts not in out:
            out.append(cuts)
    return out


def enumerate_configs(case: Case) -> tuple[list[Config], dict[int, _PMap]]:
    """枚举全部 (P,V,ψ) 候选，并返回按 P 缓存的逐层量。

    2026-10-29 修订：网格约束是 ``V·P ≤ R``（可以是严格小于，允许有空闲卡），
    所以 ``V`` 与 ``P`` 是两个独立的自由度：``V ∈ [1, min(L, 64, R//P)]``。
    ``D`` 已从题面移除，恒为 1。EP 组的 ``(pin, pout)`` 只由 P 与 S 决定（§4.4），
    因此「与 P 相关的逐层量」只需算一次。

    V 候选见 :func:`v_candidates`；另有一个**纯省时**的 P 门槛：与 (V,ψ) 无关的边角量
    ``quick = nmb·max(L·ΣT·F_s, ΣWc)`` 若已小于当前最紧候选 ``lb``，这个 P 上不存在
    可能更好的配置，直接跳过（不算 ψ、不生成配置）。最优解不受影响。
    """
    pmaps: dict[int, _PMap] = {}
    configs: list[Config] = []
    # 精确放置的总余量（所有 P 共享）：值得花，但不能把搜索预算吃穿
    exact_budget = [1.2]
    seen: set[tuple[int, int, tuple[int, ...]]] = set()
    t_fwd = sum(case.T)
    best_floor: Optional[int] = None
    for P in p_candidates(case):
        if case.R % P:
            continue
        info = _pmap(case, P, exact_budget)
        pmaps[P] = info
        per_layer_bytes = (case.E // P) * case.Z + case.Zs
        comp_w = [sum(row[i] for i in COMP_OPS) for row in info.durations]
        comm_w = [sum(row[i] for i in COMM_OPS) for row in info.durations]
        # 与 (V,ψ) 无关的边角量：计算链 ≥ Σ s = T_fwd·F_s、通信链 ≥ Σ Wc。
        # 「单来源最紧下界」：每层 m ≥ T/P ⇒ 每层 MoE 两条链都 ≥ ⌊T/P⌋·F_in。
        # 这里原先有一层 `P` 级剪枝：`quick = nmb·max(L·ΣT·F_s, ΣWc)`，`quick < best_floor`
        # 就跳过该 P。**方向反了**：`quick` ≈ 全部层的工作量，真实下界约是它的 1/V，即 `quick`
        # 是**高估**；"它比当前最好下界还小"恰恰说明这个 P 值得一算。官方 50 例上实测开关它
        # 结果逐位相同（被剪掉的 P 早已被上面的 Mexp 静态检查干掉），但对隐藏用例有风险，停用。
        _ = t_fwd
        for V in v_candidates(case, P):
            for cuts in psi_mod.psi_candidates(case.L, V, comp_w, comm_w):
                key = (P, V, cuts)
                if key in seen:
                    continue
                seen.add(key)
                psi_full = (0,) + cuts + (case.L,)
                layers = formula.group_layers(V, psi_full)
                if any(len(group) * per_layer_bytes > case.M for group in layers):
                    continue  # Mexp 静态就放不下（题面 §4.6）
                lb = formula.lower_bound(case, info.durations, layers)
                lb_rank = formula.lower_bound(
                    case, info.durations_rank or info.durations, layers
                )
                if best_floor is None or lb < best_floor:
                    best_floor = lb
                configs.append(Config(P=P, V=V, D=1, psi=cuts, lb=lb, lb_rank=lb_rank))
            # K=2V（DualPipe 镜像配对）：每个卡组两块。2026-10-30 实测：官方 50 例中
            # 20/50 例最终选它，均值 Time 22,883,348 → 21,967,523（−4.0%），单例最大 −18.3%。
            if 2 * V <= case.L:
                for cuts in k2v_candidates(case, V, comp_w, comm_w):
                    key = (P, V, cuts)
                    if key in seen:
                        continue
                    seen.add(key)
                    psi_full = (0,) + cuts + (case.L,)
                    layers = formula.group_layers(V, psi_full)
                    if any(len(group) * per_layer_bytes > case.M for group in layers):
                        continue  # 配对后一个卡组要背两块，Mexp 可能放不下
                    lb = formula.lower_bound(case, info.durations, layers)
                    lb_rank = formula.lower_bound(
                        case, info.durations_rank or info.durations, layers
                    )
                    configs.append(Config(P=P, V=V, D=1, psi=cuts, lb=lb, lb_rank=lb_rank))
    # 排序键用 `lb × 填充代价` 而不是裸 lb：2026-10 版 `V=R/P` 后，V 大的配置 lb 小但
    # 流水线深、填充代价大（`(nmb+V-1)/nmb`）。按裸 lb 排序会在"lb 打平"的计算主导实例上
    # 一律先试 V 最大的那个，实测会丢掉 3%（b13：先试 P=16 得 4.86e16，P=32 是 4.70e16）。
    # 排序用 `lb_rank`（LPT 的 m）：保持搜索轨迹与"放置只做 LPT 时"逐位相同，
    # 避免深下降改变候选顺序引入回归；而建 plan 用的是深下降后的时长（单调更短）。
    configs.sort(key=lambda item: (item.lb_rank * max(1, case.nmb + item.V - 1) // case.nmb,
                                   -item.V, item.P))
    return configs, pmaps


def _plan(case: Case, info: _PMap, config: Config) -> formula.Plan:
    return formula.build_plan_from_parts(
        case,
        config.V,
        config.P,
        config.D,
        config.psi,
        info.rows,
        info.m,
        info.x,
        info.payload,
        info.durations,
    )


def _accept(
    case: Case, best: Optional[_Best], plan: formula.Plan, config: Config, rows, result: sched.Schedule, mode: str
) -> Optional[_Best]:
    """``result`` 严格优于 ``best`` 时做内存核算并返回新的最优。"""
    if best is not None and result.time >= best.time:
        return best
    ok, groups = sched.memory_usage(case, plan, result.start, result.end)
    if not ok:
        return best
    return _Best(
        time=result.time,
        lb=plan.lb,
        plan=plan,
        rows=rows,
        config=config,
        result=result,
        groups=groups,
        mode=mode,
    )


def _seg_len(durations, group) -> int:
    """一个卡组的段长 ``seg_v = max(ΣC_v, ΣWc_v)``（``lb = nmb × max_v seg_v``）。"""
    compute = 0
    comm = 0
    for layer in group:
        row = durations[layer]
        compute += sum(row[i] for i in COMP_OPS)
        comm += sum(row[i] for i in COMM_OPS)
    return max(compute, comm)


def _cost_guard(cost: dict, mode: str) -> float:
    """下一次调度前的耗时保护：``mode`` 自己的实测最大耗时 × 1.3（没测过就用全局最大）。

    注意估算必须按模式分开：65k op 上 `early` 单次 0.35–0.62 s、`prio` 只有 0.13 s，
    混在一起会让 `prio` 也被判成"来不及"。
    """
    own = cost.get(("mode", mode))
    if own is None:
        own = cost.get(("mode-all",))
    base = own if own is not None else cost.get("est", 0.0)
    return base * 1.3


def _window_cap(case: Case, plan: formula.Plan) -> Optional[int]:
    """按内存推出的窗口上限（只算 ``Mact`` 一项，保守取 ``len(group)`` 倍）。

    大用例单次调度就要 1 s 量级，先把"必然超内存"的窗口剪掉，否则预算全花在
    ``W=nmb`` 这种形状上，等轮到可行的窗口时已经没时间了。
    """
    if case.Uact <= 0:
        return None
    widest = max((len(g) for g in plan.layers_of_group), default=1) or 1
    per_layer = (case.E // plan.P) * case.Z + case.Zs
    mexp_max = max((len(g) * per_layer for g in plan.layers_of_group), default=0)
    # 通信缓冲按 2 块算（闭区间下首尾相接即 2 块）
    spare = case.M - mexp_max - 2 * case.U
    if spare <= 0:
        return 1
    max_live = spare // case.Uact
    return max(1, int(max_live // widest))


#: ``early`` 的硬上限（op 数）。实测单次 `schedule(early)`：65k op 约 0.2 s，
#: 但 640k op 在 W=1000 时 **21.6 s**、W=500 时 14.2 s（probe_op_costs.json）。deadline
#: 只在调度**开始前**检查，一次撞穿就是该测试点 0 分（题面 §5.4），所以超过这个规模
#: 一律只用 ``prio``。
EARLY_MAX_OPS = 200_000


def _modes_for(case: Case, plan: formula.Plan, big: bool) -> tuple[str, ...]:
    """出堆模式的尝试顺序（见 `_try_config` 里的说明）。

    ``early``（按最早可开始时间出堆）在窗口被内存压小时更好；但它单次代价是 ``prio`` 的
    2–14 倍，超过 :data:`EARLY_MAX_OPS` 的用例上可能单次就超出 10 s ⇒ 直接不给它机会。
    """
    cap = _window_cap(case, plan)
    capped = cap is not None and cap < case.nmb
    if case.n_ops > EARLY_MAX_OPS:
        return ("prio",)
    return ("early", "prio") if (not big or capped) else ("prio", "early")


def _dominated_over(case: Case, config: Config, best: Optional[_Best]) -> bool:
    """这个配置上**最好的可能结果**是否已被 ``best`` 压死（只见于预测，不改变解）。

    每个卡组的两套引擎都要串行做完 ``nmb`` 份工作量，所以对任何切片都有
    ``Time ≥ nmb · max_v max(ΣC_v, ΣWc_v)``（= ``config.lb``）；再叠加流水线按块推进的
    填充 ``(nmb + V − 1)/nmb``，得到 ``lb · (nmb+V−1) / nmb``。真正的下界只会更大
    （层内链、跨组连边都还没算），所以 ``预测 ≥ best.time`` 时这个配置不可能改进。

    注意这是**预测**，不是证明：只在"落选配置"上用它把探窗目标集换成便宜的那一组，
    真正的接受/拒绝仍然只看实测 Time。
    """
    if best is None:
        return False
    predicted = config.lb * (case.nmb + config.V - 1) // case.nmb
    return predicted >= best.time


def _try_config(
    case: Case,
    config: Config,
    info: _PMap,
    best: Optional[_Best],
    deadline: float,
    big: bool,
    log: Log,
    cost: dict,
    debug: Log = None,
    cheap_probe: bool = False,
) -> Optional[_Best]:
    """在一个配置上扫 W / 变体 / 出堆模式，返回改进后的最优。

    ``cheap_probe``：只在"已经确定赢不了"的配置上用（见 :data:`_FALLBACK_TARGETS`）。

    ``cost["est"]`` 是实测出来的「单次调度耗时」，用于在开始下一次调度前确认预算够
    （每个用例 10 s 硬上限，不能让一次 640k 条的调度把预算撞穿）。
    """
    plan = _plan(case, info, config)
    windows = sched.window_candidates(case, plan, big=big)
    if debug is not None:
        debug(f"    [配置] P={plan.P} V={plan.V} psi={plan.psi[:4]} lb={plan.lb} "
              f"lb×fill={config.lb * max(1, case.nmb + config.V - 1) // case.nmb} "
              f"W 候选={windows[:8]}")
    # 将权重梯度旁支延后，优先打通往返流水；再把旁支插回计算引擎空隙。
    # 该候选对 P=1 和 P>1 都适用，且仍经过完整内存验收。
    if case.n_ops >= 5_000:
        if time.monotonic() + cost.get("est", 0.0) * 1.5 < deadline:
            began = time.monotonic()
            priority = [
                (int(op in (7, 9)), mb + (layer if op < 4 else 2 * case.L - layer), op)
                for mb in range(case.nmb)
                for layer in range(case.L)
                for op in range(10)
            ]
            result = sched.schedule(case, plan, case.nmb, sched.VARIANTS[0],
                                    "prio", priority=priority, fill_gaps=True)
            cost["est"] = max(cost.get("est", 0.0), time.monotonic() - began)
            if result is not None:
                before = best.time if best else None
                best = _accept(case, best, plan, config, info.rows, result, "gap-fill")
                if best is not None and best.time != before and log:
                    log(f"    [填隙] P={plan.P} V={plan.V} → Time={best.time} (lb={plan.lb})")
    if big:
        # 大用例（>120k op）的窗口候选直接按内存上限截断。中等规模不再截断：旧版把
        # b12（通信量最小 ⇒ 内存上限最松）的 W 候选砍成只剩 [102]，而它的最优窗口
        # 恰恰在 nmb/5 ≈ 20（实测 7.4e16 vs W=102 的 9.8e16）；截断只该在"单次调度
        # 就要 1–2 s、预算撑不起多试几次"的大用例上生效。
        cap = _window_cap(case, plan)
        if case.n_ops > _PROBE_MAX_OPS and cap is not None:
            windows = [w for w in windows if w <= cap] or [max(1, cap)]
    variants = sched._SMALL_VARIANTS if big else sched.VARIANTS
    # 只用 `prio` 时，一旦窗口被内存压小，所有前向会挤成一批、反向再挤成一批，实测把
    # 64 个卡组的并行度压到 2 个、慢 29 倍（b06：1.57e17 vs 5.4e15）。`early`（按最早
    # 可开始时间出堆）天然按时间推进，能保持交错 —— 但它在 64 万条 op 上单次要 5 s 以上，
    # 所以只在"窗口确实被压小"时才优先用它；否则 `prio` 已经够好（b05：1.04×lb）。
    modes = _modes_for(case, plan, big)
    if 5_000 <= case.n_ops <= _PROBE_MAX_OPS and len(windows) > 3:
        # 中等规模的大用例：先探窗再回来扫变体（W 对 Time 的影响比变体更大，实测 b11 在
        # W=nmb/8 时是 1.00×lb，而 W=nmb 只有 1.26×lb；b13 的 W≈nmb/5 是 1.186×lb，而
        # W=nmb 是 1.294×lb）。探窗按 nmb/k 的比例锚点取（旧版只有 nmb/8 与 nmb/32，
        # nmb/3..nmb/6 这一整段够不到），并且**每一对「窗口 × 出堆模式」都单独打分**：
        # b13 上 W=20 只有配 `early` 才好（1.186），配 `prio` 反而差；只探 modes[0] 会把
        # 好的窗口误判成坏窗口（实测 b13 因此停在 1.186×lb 而不是进 `prio` 的 1.155×lb）。
        probe: list[int] = []
        for target in _probe_targets(case, plan, cheap=cheap_probe):
            pick = min(windows, key=lambda w: (abs(w - target), -w))
            if pick not in probe:
                probe.append(pick)
        scored: list[tuple[int, int, int]] = []  # (time, window, 模式下标)
        mode_best_time: dict[str, int] = {}  # 探窗里每个模式各自最好的时间
        probe_evals = 0
        # 前 `_PROBE_PAIRS` 个窗口把两种模式都试（b13：W=20/`early` 是 1.186×lb，而同一窗口
        # 的 `prio` 是 10.9×lb；只看一个模式会误判窗口）；之后的窗口只用当前定位模式，
        # 省下预算给大窗口的变体扫描（W=102/`prio` 是 b13 的最优之一）。
        for probe_index, window in enumerate(sorted(probe)):  # 小窗口更便宜，先探
            pairs = probe_index < _PROBE_PAIRS
            for mode_index, mode in enumerate(modes):
                if not pairs and mode_index > 0:
                    break
                if time.monotonic() + _cost_guard(cost, mode) > deadline:
                    break
                if probe_evals >= _PROBE_MAX_EVALS:
                    break
                probe_evals += 1
                started = time.monotonic()
                result = sched.schedule(case, plan, window, variants[0], mode)
                spent = time.monotonic() - started
                if result is None:
                    continue
                if spent > cost.get(("mode", mode), 0.0):
                    cost[("mode", mode)] = spent
                if spent > cost.get("est", 0.0):
                    cost["est"] = spent
                before = best.time if best is not None else None
                if before is None or result.time < before:
                    # 只有"可能改进 best"的候选才做完整内存核算（0.025 s/次 × 12 次 ≈ 0.3 s，
                    # 而 65k op 的 `early` 一次只要 0.2 s —— 这笔钱本可以多跑 1–2 次调度）。
                    ok_mem, _groups = sched.memory_usage(case, plan, result.start, result.end)
                    if not ok_mem:
                        continue
                else:
                    ok_mem = True
                best = _accept(case, best, plan, config, info.rows, result, mode)
                improved = best is not None and best.time != before
                if improved:
                    # 已经比这个解更差的"探窗锚点"不再有参考价值（它们只是被同一预算
                    # 切掉的更差组合），留着只会把后面的变体扫描引到坏窗口上。
                    # 注意：留下的锚点按"本配置探窗里看到的"排序，**不能**用全局 best
                    # （别的配置的更优解会把本配置的锚点全删光）。
                    scored = [item for item in scored if item[0] < result.time]
                scored.append((result.time, window, mode_index))
                if result.time < mode_best_time.get(mode, result.time + 1):
                    mode_best_time[mode] = result.time
                if improved:
                    # 这个窗口/模式组合成为新的"定位模式"，后续窗口先用它探
                    modes = (mode,) + tuple(m for i, m in enumerate(modes) if i != mode_index)
                if improved and log:
                    log(f"    [探窗] W={window} {mode} → Time={best.time} (lb={plan.lb})")
        if scored:
            # 探窗之后怎么花剩下的预算（三条实测结论，b13/b12/b11）：
            # 1) 同一窗口换变体能差 1.23× → 1.155×lb（b13：W=51 的 v0/v3），比"换更大的
            #    窗口"更值，但它要 4 次调度；所以先给探窗里最好的 2 对「窗口 × 模式」各补
            #    一遍变体（每对 1 次，用当前配置的第二个变体也算一次 `early` ≈ 0.3 s）。
            # 2) 探窗定位在 `early` 时，更高的 `prio` 变体（≥16×lb）绝不能排到前面：
            #    它们单次不比 `early` 便宜，结果却差一个数量级。
            # 3) 小窗口上的 `prio` 对"段长 ≫ nmb"的算力主导用例差 30 倍（b12），不要回扫。
            ranked = sorted(scored)
            if debug is not None:
                debug(f"    [探窗明细] lb={plan.lb} "
                      f"{[(round(t / plan.lb, 3), w, modes[i]) for t, w, i in ranked[:4]]}")
            best_window, best_mode_index = ranked[0][1], ranked[0][2]
            modes = (modes[best_mode_index],) + tuple(
                m for i, m in enumerate(modes) if i != best_mode_index
            )
            quick_windows: list[int] = []
            for _time_value, window, _mode_index in ranked[:_SCAN_EXTRA_WINDOWS]:
                if window not in quick_windows:
                    quick_windows.append(window)
            seen = max(probe)
            extras = [w for w in windows if w > seen and w != best_window]
            # 探窗里最好的是 `prio`：先在这个窗口换变体，再在小窗口上补扫（b12 那种
            # 算力主导的用例上 `prio` 只在大窗口好用，这里的"小窗口"也只在 `prio` 已经
            # 是定位模式时才回扫）。探窗里最好的是 `early`：先把探窗最好的 2 个窗口的
            # 其它变体补齐（b13：W=51 的 v0 是 1.23×lb、v3 是 1.156×lb），再去看更大的
            # 窗口；`prio` 排到最后只作为"其它变体都杀内存"时的兜底。
            if modes[0] == "early":
                # 顺序：先扫"更大窗口 + 定位模式"（W=102/early 0.6 s 也能跑得下），再回来扫
                # `early` 变体 —— b13 实测前者能把 1.186×lb 压到 1.155×lb 附近，后者在同一
                # 窗口换变体只有 ±1%（W=20：1.186/1.196/1.237…）。
                windows = [w for w in windows if w > max(probe)][::-1] + quick_windows
                best = _scan_windows(case, config, info, plan, best, deadline, variants[:1],
                                     ("early",), windows, log, cost, debug)
                modes = ("early",)
                windows = [best_window] + extras[: _SCAN_EXTRA_WINDOWS - 1][::-1]
            if debug is not None:
                debug(f"    [计划] 探窗={sorted(probe)} 最优={best_window}/{modes[0]} "
                      f"quick={quick_windows} 之后扫={windows}")
    return _scan_windows(case, config, info, plan, best, deadline, variants, modes, windows, log, cost, debug)


def _probe_targets(case: Case, plan: formula.Plan, cheap: bool = False) -> list[int]:
    """探窗的 ``W`` 目标（``nmb // k``，去重保序），次数见 :data:`_PROBE_SHOTS`。

    段长相对 ``nmb`` 很大（``seg·nmb > 16·lb``，即填充惩罚小、算力主导）时多探几个 ——
    这类用例的 ``Time/lb`` 曲线在中等窗口处更平，多看几个窗口更值。
    """
    if cheap:
        return [max(1, case.nmb // k) for k in _FALLBACK_TARGETS]
    seg = max(_seg_len(plan.durations, group) for group in plan.layers_of_group)
    shots = _PROBE_SHOTS_WIDE if seg * case.nmb > 16 * max(1, plan.lb) else _PROBE_SHOTS
    # 名额分配：``shots=4`` 时是 ``nmb, nmb/8, nmb/2, nmb/5``（前两个与旧版重叠，保证
    # b11 这类"W=nmb/8 最好"的用例不退化；后两个是新增的中等窗口 —— b13 的最优
    # W≈nmb/5 在旧候选集里完全没有）。``shots=5`` 时再多一个 nmb/32。
    old = (1, 8, 32)                      # 旧版探窗的三个锚点
    mid = (2, 5, 3, 4, 6)                 # 中等窗口：nmb/2 … nmb/6
    order = list(old[: shots - 2]) + list(mid[: _PROBE_MAX_MID]) + list(old[shots - 2 :])
    out: list[int] = []
    for k in order:
        target = max(1, case.nmb // k)
        if target not in out:
            out.append(target)
    return out


#: 探窗只有两个出处：**落选配置**（它的最优解已经不可能超越当前 best）与**末尾补位**
#: （持有 best 的配置在预算末尾用剩下的时间再探，全便宜、只可能改进）。这两次调用用不同的
#: 目标集：前者必须便宜（旧版锚点，保证不退化），后者才用完整的 :func:`_probe_targets`。
#: b13 实测：把完整目标集也用到落选配置上，会把 W=102 的变体扫描挤掉（4.633e16 → 4.757e16）。
_FALLBACK_TARGETS: tuple[int, ...] = (1, 8, 2)     # nmb, nmb/8, nmb/2


def _probe_eval_budget(case: Case) -> int:
    """一轮"窗口 × 模式"里允许的调度次数（按 op 数估算，单次 ≈ 1.3e-6·op 秒）。

    65k op ≈ 0.09 s/次、40k op ≈ 0.05 s/次；12 次探窗 ≈ 1.1 s，加上每个候选 4 个
    变体 ≈ 0.4 s，在 65k op 的用例上总耗时 ~5–6 s（预算见 solve_all.auto_budget）。
    """
    return 12 if case.n_ops <= 120_000 else 8


def _scan_windows(
    case: Case,
    config: Config,
    info: _PMap,
    plan: formula.Plan,
    best: Optional[_Best],
    deadline: float,
    variants,
    modes: tuple[str, ...],
    windows: list[int],
    log: Log,
    cost: dict,
    debug: Log = None,
) -> Optional[_Best]:
    """在一个配置上按 ``windows`` 顺序扫「窗口 × 出堆模式 × 变体」。"""
    for window in windows:
        if time.monotonic() > deadline:
            return best
        illegal_here = 0
        for mode in modes:
            for variant in variants:
                now = time.monotonic()
                if now > deadline or now + _cost_guard(cost, mode) > deadline:
                    return best
                started = time.monotonic()
                result = sched.schedule(case, plan, window, variant, mode)
                spent = time.monotonic() - started
                # 按模式分开记估算：`early` 单次 0.35–0.62 s、`prio` 只有 0.13 s（b13，65k op）。
                # 用统一的"最贵一次"会把 `prio` 也挡在门外；用统一的"最近一次"又会在
                # 下一步撞上 `early` 撞穿预算。
                if spent > cost.get(("mode", mode), 0.0):
                    cost[("mode", mode)] = spent
                if debug is not None:
                    debug(f"    [扫窗·候选] W={window} {mode} 变体={variant} → "
                          f"{result.time if result is not None else 'None'} ({spent:.3f}s)")
                if result is None:  # pragma: no cover - DAG 不会死锁
                    continue
                ok_mem, _groups = sched.memory_usage(case, plan, result.start, result.end)
                if not ok_mem:
                    # 给通信引擎插空隙 = 用时间换内存（题面 §4.6 明说这是合法手段）。
                    # 内存极紧时 gap=0 可能永远不合法，必须在这里就试，而不是留到回退——
                    # 回退往往只剩零点几秒（实测会出现"其实有解却返回无解"，直接 0 分）。
                    rescued = False
                    for gap in (1, 2, 4, 8):
                        if time.monotonic() + cost.get("est", 0.0) * 1.3 > deadline:
                            break
                        began = time.monotonic()
                        cand = sched.schedule(case, plan, window, variant, mode, comm_gap=gap)
                        spent2 = time.monotonic() - began
                        if spent2 > cost.get(("mode", mode), 0.0):
                            cost[("mode", mode)] = spent2
                        if cand is None:
                            continue
                        ok2, _g2 = sched.memory_usage(case, plan, cand.start, cand.end)
                        if not ok2:
                            continue
                        before2 = best.time if best is not None else None
                        best = _accept(case, best, plan, config, info.rows, cand, mode)
                        rescued = True
                        if best is not None and best.time != before2 and log:
                            log(
                                f"    [空隙] W={window} gap={gap} {mode} 变体={variant} "
                                f"→ Time={best.time} (lb={plan.lb})"
                            )
                        break
                    if rescued:
                        continue
                    # 同一窗口下换变体对峰值影响很小；连续非法就换更小的窗口，
                    # 避免把整个预算耗在必然超内存的 W 上（nmb 很大时单次调度就要 1 s+）。
                    illegal_here += 1
                    if illegal_here >= 2:
                        break
                    continue
                before = best.time if best is not None else None
                best = _accept(case, best, plan, config, info.rows, result, mode)
                if best is not None and best.time != before and log:
                    log(
                        f"    [贪心] P={plan.P} V={plan.V} D={plan.D} psi={plan.psi} "
                        f"W={result.window} {mode} 变体={variant} → Time={best.time} (lb={plan.lb})"
                    )
                if best is not None and best.time <= plan.lb:
                    return best  # 已达该配置的下界：再换拓扑也不会更好
    return best


def _fill_boost_pass(
    case: Case,
    best: "_Best",
    info: "_PMap",
    deadline: float,
    log: Log,
) -> "_Best":
    """填充气泡专项：在同一配置上扫 (stage 数 × mb 数 × boost 量级 × 是否斜坡)。

    出堆键从 ``rt`` 变成 ``rt − bv[v][mb]``（``sched.schedule`` 的 ``fill_boost`` 家族）：
    让"前几个 stage × 前几个 microbatch 的前向操作"显得更急，把前向波往前推。
    ``boost`` 的量级必须与用例时长同阶 —— 取 ``plan.lb / nmb`` 的若干倍（参考实现在它
    自己的时间尺度上用的是 2e9~1e10，正好也是"几个 per-mb 时间"）。
    """
    if os.environ.get("MOE_NO_FILL"):
        return best  # 对照实验开关：关掉填充专项，用于同机 A/B
    plan = best.plan
    if plan.V < 2 or case.nmb < 2:
        return best  # 单 stage 或单 microbatch：没有前向波可推
    # 只有"填充主导"的用例才值得花这个预算：microbatch 灌不满流水线（nmb ≤ V），
    # 或者当前解离下界还远（>1.25×lb）。否则前向波本来就铺得开，纯属浪费时间。
    if case.nmb > plan.V * 6 // 5 and best.time * 4 <= best.lb * 5:
        return best
    scale = plan.lb / max(1, case.nmb)
    if scale <= 0:
        return best
    best_local = best
    # 网格刻意放得比"看起来省"的要宽：实测收紧到 3 档 × 4 变体 × 0.9 s 反而更差
    # （21,897,645 vs 21,846,362），因为缩小 boost 量级的覆盖会错过最优点。
    stages = sorted({1, 2, max(1, case.nmb // 4), max(1, case.nmb // 2), plan.V})
    mbs = sorted({case.nmb, max(1, case.nmb // 2), max(1, case.nmb // 4)})
    windows = [best.result.window] if best.result is not None else [case.nmb]
    for window in windows:
        for fs in stages:
            if time.monotonic() > deadline:
                return best_local
            for fm in mbs:
                for ratio in (0.5, 1.0, 2.0, 5.0, 10.0):
                    if time.monotonic() > deadline:
                        return best_local
                    for ramp in (True, False):
                        for variant in sched.VARIANTS:
                            result = sched.schedule(
                                case, plan, window, variant, "early",
                                fill_boost=scale * ratio, fill_stages=fs,
                                fill_mbs=fm, fill_ramp=ramp,
                            )
                            if result is None:
                                continue
                            candidate = _accept(
                                case, best_local, plan, best_local.config,
                                info.rows, result, "fill",
                            )
                            if candidate is not None and candidate.time < best_local.time:
                                best_local = candidate
                                if log:
                                    log(f"    [填充] P={plan.P} V={plan.V} fs={fs} fm={fm} "
                                        f"×{ratio} ramp={int(ramp)} → Time={best_local.time}")
                                if best_local.time <= best_local.lb:
                                    return best_local
    return best_local


def _improve_best(case: Case, best: _Best, deadline: float, log: Log) -> _Best:
    """在最优配置上做引擎序列局部搜索（多种子 + 模拟退火）。"""
    if best.time <= best.lb:
        return best  # 已达下界，不可能更好
    if case.n_ops > 20000:
        return best  # 大用例留时间给多配置搜索：序列搜索的单次求值 O(n)
    plan = best.plan
    # 种子：当前最优 + 同配置下两个不同拓扑的贪心解（都很便宜）
    seeds: list[sched.Schedule] = [best.result]
    for variant in (sched.VARIANTS[1], sched.VARIANTS[4]):
        candidate = sched.schedule(case, plan, best.result.window, variant, "prio")
        if candidate is not None and candidate.time <= best.time * 2 + 1:
            seeds.append(candidate)
    trials = _SEARCH_WORK // max(1, case.n_ops)
    trials = max(_MIN_TRIALS, min(_MAX_TRIALS, trials))
    per_seed = max(_MIN_TRIALS, trials // len(seeds))
    improved = best
    for index, seed in enumerate(seeds):
        now = time.monotonic()
        remaining = deadline - now
        if remaining <= 0.05:
            break
        slice_deadline = now + remaining / (len(seeds) - index)
        result = sched.improve_sequences(
            case,
            plan,
            seed,
            trials=per_seed,
            seed=20261020 + 7919 * index,
            deadline=slice_deadline,
        )
        candidate = _accept(case, improved, plan, best.config, best.rows, result, "anneal")
        if candidate is not None and candidate.time != improved.time:
            improved = candidate
            if log:
                log(
                    f"    [序列搜索] 种子{index}: Time={improved.time} (lb={improved.lb}, "
                    f"trials≤{per_seed})"
                )
    return improved


class _FrontierBudget(Exception):
    """frontier 候选扫描的预算用尽（内部使用）。"""


def _try_frontier(
    case: Case,
    best: _Best,
    deadline: float,
    mode: str,
    log: Log,
    seed: int = 20261020,
    reserve_s: float = 0.0,
) -> tuple[_Best, dict]:
    """在**同一配置**（best.plan）上用 frontier 内核再试一次；默认关闭，仅显式开关启用。

    只接受：``Time`` 严格更小 **且** 过 ``sched.memory_usage`` 的完整解；否则原样返回
    incumbent。这保证接入新内核不会让结果变差（只可能更好或不变）。
    """
    from . import frontier as frontier_mod

    info: dict = {
        "enabled": True,
        "mode": mode,
        "reserve_s": round(reserve_s, 3),
        "planned": 0,
        "run": 0,
        "hits": 0,
        "before": best.time,
        "after": best.time,
        "stop": "complete",
        "candidates": [],
    }
    if time.monotonic() >= deadline:
        info["stop"] = "no-window"
        return best, info
    plan = best.plan
    stats = frontier_mod.Stats()
    # 同配置下的小候选集：只保留在 t2 探索里真正赢过基线列表调度的拓扑/预留组合，
    # 并按实测单次耗时做预算保护，避免把一次 35k op 的调度排到 deadline 之后。
    variant_indices = (0, 2, 4, 5, 7) if case.n_ops <= 20_000 else (0, 4)
    policies = ("auto", "comm1") if case.n_ops <= 20_000 else ("auto",)
    if mode == "A":
        variant_indices = ()
        policies = ()
        info["planned"] = 1
    else:
        info["planned"] = len(variant_indices) * len(policies) + (
            1 if mode in ("C", "auto") else 0
        )
    candidates: list = []
    try:
        if mode == "A":
            began = time.monotonic()
            candidate = frontier_mod.search(
                case, plan, strategy="A", deadline=deadline, seed=seed, stats=stats,
            )
            spent = time.monotonic() - began
            info["run"] = 1
            info["candidates"].append({
                "variant": "A",
                "policy": "search",
                "time": None if candidate is None else candidate.time,
                "wall": round(spent, 4),
            })
            candidates.append((candidate, ("A", "search")))
        else:
            estimate = 0.0
            for variant_index in variant_indices:
                for policy in policies:
                    now = time.monotonic()
                    if now + max(0.02, estimate) > deadline:
                        raise _FrontierBudget()
                    began = time.monotonic()
                    candidate = frontier_mod.schedule(
                        case, plan, window=None,
                        variant=sched.VARIANTS[variant_index], gating=True,
                        zero_free=True, policy=policy, mode="event",
                        deadline=deadline, seed=seed, stats=stats,
                    )
                    spent = time.monotonic() - began
                    info["run"] += 1
                    info["candidates"].append({
                        "variant": variant_index,
                        "policy": policy,
                        "time": None if candidate is None else candidate.time,
                        "wall": round(spent, 4),
                    })
                    if spent > estimate:
                        estimate = spent
                    if candidate is not None:
                        candidates.append((candidate, (variant_index, policy)))
            if mode in ("C", "auto") and candidates:
                now = time.monotonic()
                if now + max(0.02, estimate) <= deadline:
                    began = time.monotonic()
                    candidate = frontier_mod.schedule(
                        case, plan, window=None, gating=True, zero_free=True,
                        policy=policies[0], mode="lookahead", lookahead=4,
                        deadline=deadline, seed=seed, stats=stats,
                    )
                    spent = time.monotonic() - began
                    info["run"] += 1
                    info["candidates"].append({"variant": "lookahead",
                                               "policy": policies[0],
                                               "time": None if candidate is None else candidate.time,
                                               "wall": round(spent, 4)})
                    if candidate is not None:
                        candidates.append((candidate, ("lookahead", policies[0])))
    except _FrontierBudget:
        info["stop"] = "deadline"
    except Exception as exc:  # pragma: no cover - 新内核失败时绝不影响既有结果
        info["stop"] = "exception"
        info["error"] = repr(exc)
        if log:
            log(f"    [frontier] 异常，保留原解：{exc!r}")
        return best, info
    improved = best
    for candidate, meta in candidates:
        if candidate is None or candidate.time >= improved.time:
            continue
        ok, groups = sched.memory_usage(case, plan, candidate.start, candidate.end)
        if not ok:
            continue
        improved = _Best(
            time=candidate.time,
            lb=best.lb,
            plan=plan,
            rows=best.rows,
            config=best.config,
            result=candidate,
            groups=groups,
            mode=f"frontier-{mode}",
        )
        info["hits"] += 1
        info["after"] = candidate.time
        if meta is None:
            info["accepted"] = {"variant": None, "policy": None}
        else:
            info["accepted"] = {"variant": meta[0], "policy": meta[1]}
        if log:
            log(
                f"    [frontier-{mode}] {meta} Time={candidate.time} (原 {best.time}) "
                f"peak=({[(g.peak_comm, g.peak_act) for g in groups]})"
            )
    return improved, info


def solve_case(
    case: Case,
    budget: float = 8.5,
    log: Log = None,
    exact: bool = False,
    frontier: bool = False,
    frontier_mode: str = "B",
) -> Optional[Solution]:
    """求解一个测试点，返回最优合法映射；``None`` 表示没找到（理论上不会）。

    ``exact=True`` 时，在常规搜索（网格枚举 + 贪心 + 序列退火）之后，对 ``nmb=2`` 且每
    stage 单层的形状再跑一次**精确搜索**（`solver/exact.py`：通信交错穷举 + 计算顺序线性
    扩展）。它只可能改进、不会更差；找不到更优解时把搜索统计带回给调用方（NOTES 需要）。

    ``frontier=True`` 时，在最优配置上再用 `solver/frontier.py` 的事件内核试一次
    （``frontier_mode`` = ``A``/``B``/``C``）；只接受更优且内存合法的解，默认关闭。
    """
    started = time.monotonic()
    deadline = started + budget
    # 给最终搜索之后留出预算：内存核算 + 渲染 + 落盘实测 ≈ 0.1 s + 0.5 µs/op
    # （640k 条约 0.4 s），再加上局部搜索不可打断的尾部，统一留 0.6 s。
    # 注意 `budget` 是**求解器内部**的时钟（调用方按「题面 10 s − 进程启动 − 渲染落盘」
    # 自己折算，见 `solve_all.auto_budget`），所以这里不再按 op 数加倍预留。
    reserve = 0.6
    # 显式 `--frontier` 时从同一份 B 里**预留**一小段时间给新内核（不能额外加预算）。
    # 这是"共享同一份 B"的唯一合法形式；若因此挤掉原搜索预算，报告里必须单独说明。
    frontier_reserve = min(0.9, max(0.4, budget * 0.12)) if frontier else 0.0
    search_deadline = min(
        deadline, started + max(0.05, budget - reserve - frontier_reserve)
    )
    configs, pmaps = enumerate_configs(case)
    if log:
        head = configs[0].lb if configs else "-"
        log(f"[枚举] {case.name}: {len(configs)} 个 (P,V,D,ψ) 候选，最小 lb={head}")
    big = case.n_ops > 120_000
    _debug = log if os.environ.get("SOLVER_DEBUG_LOG") else None
    cost = {"est": 0.0}
    best: Optional[_Best] = None
    for config in configs:
        if best is not None and config.lb >= best.time:
            continue  # 按 lb×fill 排序，后续候选的裸 lb 仍可能更小
        if time.monotonic() > search_deadline:
            if log:
                log("[预算] 搜索达到墙钟预算，返回当前最好解")
            break

        dominated = _dominated_over(case, config, best)
        best = _try_config(
            case, config, pmaps[config.P], best, search_deadline, big, log, cost, _debug,
            cheap_probe=dominated,
        )

    if best is None:
        # 回退：不限时间，窗口从小到大（内存最省优先），全部变体；
        # 再给通信引擎插空隙（comm_gap）——内存顶死时「零时长通信挤在同一时刻」会把
        # Movl 的闭区间峰值顶上去，留 1~2 单位空隙是用时间换内存的最后一招（题面 §4.6）。
        if log:
            log("[回退] 主搜索没有合法解，改为小窗口 + 全变体 + 通信空隙重扫")
        # 回退必须同样受预算约束：否则在 nmb=1000、内存顶死的用例上会无限扫下去，
        # 调用方（服务端队列）只能等 10 s 超时，用例直接判 0 分。
        fallback_deadline = time.monotonic() + max(0.5, (deadline - time.monotonic()))
        # `comm_gap` 放在**最内层**：内存极紧时 gap=0 往往永远不合法，如果按 gap 外层
        # 循环，预算会在 gap=0 上耗光，根本轮不到 gap=1（实测 fuzz 里出现过"其实有解、
        # 但求解器返回无解"→ 该测试点直接 0 分）。
        for config in configs:
            if time.monotonic() > fallback_deadline:
                if log:
                    log("[回退] 到达预算上限，返回当前最好解")
                break
            plan = _plan(case, pmaps[config.P], config)
            for window in sorted(sched.window_candidates(case, plan, big=big)):
                if time.monotonic() > fallback_deadline:
                    break
                for mode in ("prio", "early"):
                    for variant in sched.VARIANTS:
                        for gap in (0, 1, 2, 4, 8):
                            if time.monotonic() > fallback_deadline:
                                break
                            result = sched.schedule(
                                case, plan, window, variant, mode, comm_gap=gap
                            )
                            if result is None:  # pragma: no cover
                                continue
                            best = _accept(
                                case, best, plan, config, pmaps[config.P].rows, result, mode
                            )
                            if best is not None and best.time <= best.lb:
                                break
                        if best is not None and best.time <= best.lb:
                            break
                    if best is not None and best.time <= best.lb:
                        break
                if best is not None:
                    break
            if best is not None:
                break

    exact_stats: Optional[dict] = None
    frontier_info: Optional[dict] = None
    if best is not None:
        # 局部搜索用剩余预算的一半（上限 4 s），并给最终渲染留出 reserve
        # 填充专项先跑：每次只是一次列表调度，比退火便宜，且对 nmb<V 的用例收益最大
        fill_deadline = min(search_deadline, time.monotonic() + max(0.0, min(1.6, budget * 0.2)))
        best = _fill_boost_pass(case, best, pmaps[best.plan.P], fill_deadline, log)
        improve_deadline = min(search_deadline, time.monotonic() + max(0.0, min(4.0, budget * 0.5)))
        best = _improve_best(case, best, improve_deadline, log)
        if frontier:
            if frontier_mode == "noop":
                # no-op 控制臂：保留同样的预算预留，但不运行 frontier，用于度量
                # “给新路线让预算”本身的代价（对照不能只报 min(旧,新)）。
                frontier_info = {
                    "enabled": True, "mode": "noop",
                    "reserve_s": round(frontier_reserve, 3),
                    "planned": 0, "run": 0, "hits": 0,
                    "before": best.time, "after": best.time,
                    "stop": "noop-control", "candidates": [],
                }
            elif best.time <= best.lb:
                frontier_info = {"enabled": True, "mode": frontier_mode,
                                 "reserve_s": round(frontier_reserve, 3),
                                 "planned": 0, "run": 0, "hits": 0,
                                 "before": best.time, "after": best.time,
                                 "stop": "skipped-lb", "candidates": []}
            else:
                frontier_deadline = min(
                    deadline - reserve,
                    time.monotonic() + max(0.1, frontier_reserve),
                )
                best, frontier_info = _try_frontier(
                    case, best, frontier_deadline, frontier_mode, log,
                    reserve_s=frontier_reserve,
                )
        if exact and exact_mod.applicable(case, best.plan):
            # 精确搜索走独立时间片：用「总 deadline - 渲染预留」，最多再吃掉 80% 预算
            exact_deadline = min(deadline - reserve, time.monotonic() + max(0.5, budget * 0.8))
            exact_stats = {}
            outcome = exact_mod.search(case, best.plan, exact_deadline, best.time, log, exact_stats)
            if outcome is not None:
                schedule = sched.Schedule(
                    time=outcome.time,
                    start=outcome.start,
                    end=outcome.end,
                    window=best.result.window,
                    variant=best.result.variant,
                )
                best = _Best(
                    time=outcome.time,
                    lb=best.lb,
                    plan=best.plan,
                    rows=best.rows,
                    config=best.config,
                    result=schedule,
                    groups=outcome.groups,
                    mode="exact",
                )
        text = sched.render_output(case, best.plan, best.result, best.rows)
        solution = Solution(
            text=text,
            time=best.time,
            lb=best.lb,
            V=best.plan.V,
            P=best.plan.P,
            D=best.plan.D,
            K=best.plan.K,
            psi=best.plan.psi,
            window=best.result.window,
            variant=best.result.variant,
            mode=best.mode,
            elapsed=time.monotonic() - started,
            groups=best.groups,
            exact_stats=exact_stats,
            frontier_stats=frontier_info,
        )
        return solution
    return None
