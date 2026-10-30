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

import time
from dataclasses import dataclass
from typing import Callable, Optional

from . import exact as exact_mod, formula, place, psi as psi_mod, sched
from .casein import Case
from .formula import COMM_OPS, COMP_OPS

__all__ = ["Solution", "Config", "solve_case", "p_candidates", "divisors"]

Log = Optional[Callable[[str], None]]

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


def _pmap(case: Case, P: int) -> _PMap:
    rows, m = place.best_placement(case, P)
    pin, pout = formula.peer_counts(case, 1, P)
    payload = [formula.comm_payload(case, layer, P) for layer in range(case.L)]
    x = [formula.comm_time(case, payload[layer], pin, pout) for layer in range(case.L)]
    durations = [
        formula.layer_durations(case, layer, m[layer], x[layer]) for layer in range(case.L)
    ]
    return _PMap(P=P, pin=pin, pout=pout, rows=rows, m=m, payload=payload, x=x, durations=durations)


def enumerate_configs(case: Case) -> tuple[list[Config], dict[int, _PMap]]:
    """枚举全部 (P,V,ψ) 候选，并返回按 P 缓存的逐层量。

    2026-10-29 修订：网格约束是 ``V·P ≤ R``（可以是严格小于，允许有空闲卡），
    所以 ``V`` 与 ``P`` 是两个独立的自由度：``V ∈ [1, min(L, 64, R//P)]``。
    ``D`` 已从题面移除，恒为 1。EP 组的 ``(pin, pout)`` 只由 P 与 S 决定（§4.4），
    因此「与 P 相关的逐层量」只需算一次。
    """
    pmaps: dict[int, _PMap] = {}
    configs: list[Config] = []
    seen: set[tuple[int, int, tuple[int, ...]]] = set()
    for P in p_candidates(case):
        if case.R % P:
            continue
        info = _pmap(case, P)
        pmaps[P] = info
        per_layer_bytes = (case.E // P) * case.Z + case.Zs
        comp_w = [sum(row[i] for i in COMP_OPS) for row in info.durations]
        comm_w = [sum(row[i] for i in COMM_OPS) for row in info.durations]
        # 卡是"免费"的：加大 V 只会让每个卡组少背几层（lb 下降），代价是填充项
        # (nmb+V-1)/nmb 略增。两者的乘积 (nmb+V-1)/V 对 V 单调递减，所以**取最大的 V**。
        for V in (min(case.L, 64, case.R // P),):
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
                configs.append(Config(P=P, V=V, D=1, psi=cuts, lb=lb))
    # 排序键用 `lb × 填充代价` 而不是裸 lb：2026-10 版 `V=R/P` 后，V 大的配置 lb 小但
    # 流水线深、填充代价大（`(nmb+V-1)/nmb`）。按裸 lb 排序会在"lb 打平"的计算主导实例上
    # 一律先试 V 最大的那个，实测会丢掉 3%（b13：先试 P=16 得 4.86e16，P=32 是 4.70e16）。
    configs.sort(key=lambda item: (item.lb * max(1, case.nmb + item.V - 1) // case.nmb,
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


def _modes_for(case: Case, plan: formula.Plan, big: bool) -> tuple[str, ...]:
    """出堆模式的尝试顺序（见 `_try_config` 里的说明）。"""
    cap = _window_cap(case, plan)
    capped = cap is not None and cap < case.nmb
    return ("early", "prio") if (not big or capped) else ("prio", "early")


def _try_config(
    case: Case,
    config: Config,
    info: _PMap,
    best: Optional[_Best],
    deadline: float,
    big: bool,
    log: Log,
    cost: dict,
) -> Optional[_Best]:
    """在一个配置上扫 W / 变体 / 出堆模式，返回改进后的最优。

    ``cost["est"]`` 是实测出来的「单次调度耗时」，用于在开始下一次调度前确认预算够
    （每个用例 10 s 硬上限，不能让一次 640k 条的调度把预算撞穿）。
    """
    plan = _plan(case, info, config)
    windows = sched.window_candidates(case, plan, big=big)
    if big:
        cap = _window_cap(case, plan)
        if cap is not None:
            windows = [w for w in windows if w <= cap] or [max(1, cap)]
    variants = sched._SMALL_VARIANTS if big else sched.VARIANTS
    # 只用 `prio` 时，一旦窗口被内存压小，所有前向会挤成一批、反向再挤成一批，实测把
    # 64 个卡组的并行度压到 2 个、慢 29 倍（b06：1.57e17 vs 5.4e15）。`early`（按最早
    # 可开始时间出堆）天然按时间推进，能保持交错 —— 但它在 64 万条 op 上单次要 5 s 以上，
    # 所以只在"窗口确实被压小"时才优先用它；否则 `prio` 已经够好（b05：1.04×lb）。
    modes = _modes_for(case, plan, big)
    if 5_000 <= case.n_ops <= 200_000 and len(windows) > 3:
        # 中等规模的大用例：先花 3 次调度探一探窗口（W 对 Time 的影响比变体更大，
        # 实测 b11 在 W=nmb/8 时是 1.00×lb，而 W=nmb 只有 1.26×lb）。探完再回到最好的
        # 窗口上扫变体 —— 否则预算会全花在 W=nmb 的 3 个变体上。
        probe = []
        for frac in (1, 8, 32):
            target = max(1, case.nmb // frac)
            pick = min(windows, key=lambda w: abs(w - target))
            if pick not in probe:
                probe.append(pick)
        scored = []
        for window in sorted(probe):  # 小窗口更便宜，先探
            if time.monotonic() + cost.get("est", 0.0) * 1.3 > deadline:
                break
            started = time.monotonic()
            result = sched.schedule(case, plan, window, variants[0], modes[0])
            spent = time.monotonic() - started
            if spent > cost.get("est", 0.0):
                cost["est"] = spent
            if result is None:
                continue
            ok_mem, _groups = sched.memory_usage(case, plan, result.start, result.end)
            if not ok_mem:
                continue
            scored.append((result.time, window))
            before = best.time if best is not None else None
            best = _accept(case, best, plan, config, info.rows, result, modes[0])
            if best is not None and best.time != before and log:
                log(f"    [探窗] W={window} {modes[0]} → Time={best.time} (lb={plan.lb})")
        if scored:
            windows = [min(scored)[1]]
    for window in windows:
        if time.monotonic() > deadline:
            return best
        illegal_here = 0
        for mode in modes:
            for variant in variants:
                now = time.monotonic()
                if now > deadline or now + cost.get("est", 0.0) * 1.3 > deadline:
                    return best
                started = time.monotonic()
                result = sched.schedule(case, plan, window, variant, mode)
                spent = time.monotonic() - started
                if spent > cost.get("est", 0.0):
                    cost["est"] = spent
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
                        if spent2 > cost.get("est", 0.0):
                            cost["est"] = spent2
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


def solve_case(
    case: Case,
    budget: float = 8.5,
    log: Log = None,
    exact: bool = False,
) -> Optional[Solution]:
    """求解一个测试点，返回最优合法映射；``None`` 表示没找到（理论上不会）。

    ``exact=True`` 时，在常规搜索（网格枚举 + 贪心 + 序列退火）之后，对 ``nmb=2`` 且每
    stage 单层的形状再跑一次**精确搜索**（`solver/exact.py`：通信交错穷举 + 计算顺序线性
    扩展）。它只可能改进、不会更差；找不到更优解时把搜索统计带回给调用方（NOTES 需要）。
    """
    started = time.monotonic()
    deadline = started + budget
    # 给最终的「内存核算 + 渲染落盘」留时间（约 1 µs/op + 0.25 s；640k 条约 0.9 s）
    reserve = 0.25 + case.n_ops * 1.0e-6
    search_deadline = min(deadline, started + max(0.05, budget - reserve))
    configs, pmaps = enumerate_configs(case)
    if log:
        head = configs[0].lb if configs else "-"
        log(f"[枚举] {case.name}: {len(configs)} 个 (P,V,D,ψ) 候选，最小 lb={head}")
    big = case.n_ops > 120_000
    cost = {"est": 0.0}
    best: Optional[_Best] = None
    for config in configs:
        if best is not None and config.lb >= best.time:
            break  # 已按 lb 升序：后面的只会更差
        if time.monotonic() > search_deadline:
            if log:
                log("[预算] 搜索达到墙钟预算，返回当前最好解")
            break
        best = _try_config(
            case, config, pmaps[config.P], best, search_deadline, big, log, cost
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
    if best is not None:
        # 局部搜索用剩余预算的一半（上限 4s），并给最终渲染留出 reserve
        improve_deadline = min(search_deadline, time.monotonic() + max(0.0, min(4.0, budget * 0.5)))
        best = _improve_best(case, best, improve_deadline, log)
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
        )
        return solution
    return None
