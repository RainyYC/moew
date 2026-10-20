"""校验 + 事件驱动模拟 + 结果装配（题面 §4，CONTRACT §1）。

这里实现的是 CONTRACT 的「唯一权威」那一份：

1. 网格、切点、MAP 的**字段类**合法性（``category="field"``）；
2. 调度守恒：每个 ``(mb, ℓ, op)`` 恰好出现一次（``missing`` / ``duplicate``）；
3. 题面 §4.2 的四条规则：层内依赖、管线依赖、卡组引擎互斥、因果性
   （``dependency`` / ``engine``）；
4. 题面 §4.6 的三块内存（``memory``）；
5. ``Time = max(start + dur)`` 与 ``lb = max_v nmb·max(ΣC_v, ΣWc_v)``。

语义要点（都以题面为准，CONTRACT §6 复述）：

* **时长为 0 的操作不占用引擎**（题面 §7.2 的 ``s = 0``、§7.5 的 ``x = 0``；
  否则样例自相矛盾）；
* 引擎在**相等时刻释放**：``t == 上一操作结束`` 合法；
* ``s_bwd`` 同时依赖**本层 comb 结束**与**下一层 disp_bwd 结束**（§4.2 第 2 条）；
  ``gemm_dw`` / ``s_dw`` 只依赖 ``comb_bwd``（可推迟到计算引擎空闲处）；
* 管线依赖建在**层**上而不是块上（§4.2 第 2 条），共卡的两层之间同样成立；
* 卡组 = ``g(k) = k``（``k<V``）或 ``2V−1−k``（``K=2V`` 镜像配对），``K=2V`` 时
  一个卡组的两块共用同一对引擎（§4.2 第 3 条）。

性能：单份 64 万条（``L=64, nmb=1000``）的调度也要在服务端的单例预算内跑完，因此模拟
是**两趟线性扫描**（① 登记全部 ``(start,end)``；② 依赖与引擎区间检查，均用扁平数组，
不看行序），通信缓冲峰值用「结束时刻小顶堆」流式统计（不落 64 万条区间），
只有 ``evaluate_detailed`` 才展开 ops 列表。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Optional, Sequence

from . import memory as memory_mod
from .model import (
    COMM,
    COMM_OPS,
    COMP,
    COMP_OPS,
    DEPS,
    ENGINE,
    OP_INDEX,
    OP_NAMES,
    comm_payload,
    comm_time,
    group_layers,
    group_of_layer,
    layer_durations,
    layer_m,
    lower_bound,
    peer_counts,
)
from .parse import Case, Output

__all__ = ["MAX_ERRORS", "evaluate_output"]

#: 一份非法解最多报这么多条错误（避免 64 万条调度把响应撑爆）。
MAX_ERRORS = 64

_OI_S = OP_INDEX["s"]
_OI_COMB = OP_INDEX["comb"]
_OI_S_BWD = OP_INDEX["s_bwd"]
_OI_DISP_BWD = OP_INDEX["disp_bwd"]

_ENGINE_NAME = {COMP: "计算", COMM: "通信"}

#: ``rows``：``[(t, [(mb, ℓ, oi, "mb:ℓ:op"), …])]``，按调度书写顺序。
Rows = list[tuple[int, list[tuple[int, int, int, str]]]]


def _error(category: str, message: str, t: Optional[int] = None, at: Optional[str] = None, **extra: object) -> dict:
    """构造一条可定位的错误。

    统一带 ``category``（missing/duplicate/dependency/engine/memory/field）、``t``
    （出错的时刻；字段类错误为 ``null``）与 ``at``（``mb:ℓ:op``；字段类错误为
    ``null``），另有面向人类的 ``message`` 与若干结构化附加字段。
    """
    item: dict = {"category": category, "message": message, "t": t, "at": at}
    item.update(extra)
    return item


def _add(errors: list[dict], item: dict) -> None:
    if len(errors) < MAX_ERRORS:
        errors.append(item)
    elif len(errors) == MAX_ERRORS:
        errors.append(_error("field", f"错误超过 {MAX_ERRORS} 条，后续省略（请先修前面这些）"))


# --------------------------------------------------------------------------- #
# 字段类校验：网格 / PSI / MAP
# --------------------------------------------------------------------------- #


def _check_grid(case: Case, out: Output, errors: list[dict]) -> bool:
    V, P, D = out.V, out.P, out.D
    ok = True
    for name, value in (("V", V), ("P", P), ("D", D)):
        if value < 1:
            ok = False
            _add(errors, _error("field", f"网格非法：{name}={value} 必须 ≥ 1", section="grid"))
    if not ok:
        return False
    if V * P * D != case.R:
        ok = False
        _add(
            errors,
            _error(
                "field",
                f"网格非法：V·P·D={V}·{P}·{D}={V * P * D} ≠ R=N·S={case.R}（题面 §4.7.1）",
                section="grid",
            ),
        )
    if case.E % P:
        ok = False
        _add(errors, _error("field", f"P={P} 必须整除 E={case.E}（题面 §4.7.1）", section="grid"))
    if not (case.S % P == 0 or P % case.S == 0):
        ok = False
        _add(
            errors,
            _error(
                "field",
                f"P={P} 与 S={case.S} 既不满足 P∣S 也不满足 S∣P（EP 组无法与节点对齐，题面 §4.7.1）",
                section="grid",
            ),
        )
    if V > case.L:
        ok = False
        _add(errors, _error("field", f"V={V} 大于层数 L={case.L}，切点无法严格递增（题面 §3.1）", section="grid"))
    return ok


def _check_psi(case: Case, out: Output, errors: list[dict]) -> bool:
    V, K = out.V, out.K
    ok = True
    if K not in (V, 2 * V):
        ok = False
        _add(
            errors,
            _error(
                "field",
                f"PSI 非法：块数 K={K} 只能取 V={V} 或 2V={2 * V}（题面 §3.1）",
                section="psi",
                K=K,
            ),
        )
    expected = K - 1
    if len(out.psi) != expected:
        ok = False
        _add(
            errors,
            _error(
                "field",
                f"PSI 非法：K={K} 需要恰好 {expected} 个切点，实际 {len(out.psi)} 个（题面 §3.1/§4.7.2）",
                section="psi",
                K=K,
            ),
        )
    previous = 0  # ψ_0 = 0 是隐含端点
    for index, point in enumerate(out.psi, 1):
        if point <= previous:
            ok = False
            _add(
                errors,
                _error(
                    "field",
                    f"PSI 非法：切点非严格递增，ψ_{index}={point} 不大于前一个 {previous}（题面 §4.7.2）",
                    section="psi",
                    psi_index=index,
                ),
            )
        elif point >= case.L:
            ok = False
            _add(
                errors,
                _error(
                    "field",
                    f"PSI 非法：切点 ψ_{index}={point} 越界，必须落在 (0, L={case.L}) 内（题面 §4.7.2）",
                    section="psi",
                    psi_index=index,
                ),
            )
        previous = max(previous, point)
    return ok


def _check_map(case: Case, out: Output, errors: list[dict]) -> bool:
    ok = True
    P = out.P
    if len(out.map_rows) != case.L:
        ok = False
        _add(
            errors,
            _error(
                "field",
                f"MAP 非法：需要 L={case.L} 行，实际 {len(out.map_rows)} 行（题面 §3.1）",
                section="map",
            ),
        )
    per_rank = case.E // P if P else 0
    for layer, row in enumerate(out.map_rows):
        if len(row) != case.E:
            ok = False
            _add(
                errors,
                _error(
                    "field",
                    f"MAP 非法：层 {layer} 需要 E={case.E} 个整数，实际 {len(row)} 个（题面 §3.1）",
                    section="map",
                    layer=layer,
                ),
            )
            continue
        bad = [(expert, rank) for expert, rank in enumerate(row) if not (0 <= rank < P)]
        if bad:
            ok = False
            expert, rank = bad[0]
            _add(
                errors,
                _error(
                    "field",
                    f"MAP 非法：层 {layer} 的 σ_{{{layer},{expert}}}={rank} 不在 [0,P={P}) 内"
                    f"（越界 {len(bad)} 处，题面 §4.7.3）",
                    section="map",
                    layer=layer,
                ),
            )
            continue
        counts = [0] * P
        for rank in row:
            counts[rank] += 1
        if per_rank and any(count != per_rank for count in counts):
            ok = False
            _add(
                errors,
                _error(
                    "field",
                    f"MAP 非法：层 {layer} 各 rank 的专家数 {counts} 不等于 "
                    f"E/P={case.E}/{P}={per_rank}（题面 §4.7.3）",
                    section="map",
                    layer=layer,
                ),
            )
    return ok


# --------------------------------------------------------------------------- #
# 调度：语义校验
# --------------------------------------------------------------------------- #


def _check_schedule_tokens(case: Case, out: Output, errors: list[dict]) -> tuple[Rows, bool]:
    ok = True
    rows: Rows = []
    previous_t = 0
    nmb = case.nmb
    L = case.L
    for row in out.sched:
        t = row.t
        if t < 0:
            ok = False
            _add(errors, _error("field", f"调度行的时刻 t={t} 必须 ≥ 0（题面 §3.2）", t=t))
            continue
        if t < previous_t:
            ok = False
            _add(
                errors,
                _error(
                    "field",
                    f"调度行的时刻必须非降：t={t} 早于上一行 t={previous_t}（题面 §3.2 第 1 条）",
                    t=t,
                ),
            )
        previous_t = t
        items: list[tuple[int, int, int, str]] = []
        for op in row.ops:
            at = op.raw
            oi = OP_INDEX.get(op.op)
            if oi is None:
                ok = False
                _add(
                    errors,
                    _error(
                        "field",
                        f"未知操作名 {op.op!r}：只允许题面 §4.1 的十种操作（{', '.join(OP_NAMES)}）",
                        t=t,
                        at=at,
                    ),
                )
                continue
            if not (0 <= op.mb < nmb):
                ok = False
                _add(
                    errors,
                    _error(
                        "field",
                        f"{at} 的 mb={op.mb} 越界，必须在 [0,nmb={nmb}) 内（题面 §3.2）",
                        t=t,
                        at=at,
                    ),
                )
                continue
            if not (0 <= op.l < L):
                ok = False
                _add(
                    errors,
                    _error(
                        "field",
                        f"{at} 的层号 ℓ={op.l} 越界，必须在 [0,L={L}) 内（题面 §3.2）",
                        t=t,
                        at=at,
                    ),
                )
                continue
            items.append((op.mb, op.l, oi, at))
        rows.append((t, items))
    return rows, ok


def _check_coverage(case: Case, rows: Rows, errors: list[dict]) -> bool:
    """每个 ``(microbatch, 层, 操作)`` 恰好出现一次（题面 §3.2）。"""
    ok = True
    seen: dict[tuple[int, int, int], int] = {}
    for t, items in rows:
        for (mb, layer, oi, at) in items:
            key = (mb, layer, oi)
            first = seen.get(key)
            if first is not None:
                ok = False
                _add(
                    errors,
                    _error(
                        "duplicate",
                        f"{at} 重复出现：首次在 t={first}，又在 t={t} 出现（题面 §3.2）",
                        t=t,
                        at=at,
                        first_t=first,
                    ),
                )
            else:
                seen[key] = t
    examples: list[str] = []
    missing = 0
    for mb in range(case.nmb):
        for layer in range(case.L):
            for oi in range(10):
                if (mb, layer, oi) not in seen:
                    missing += 1
                    if len(examples) < 20:
                        examples.append(f"{mb}:{layer}:{OP_NAMES[oi]}")
    if missing:
        ok = False
        for at in examples:
            _add(errors, _error("missing", f"调度缺少操作 {at}（每层每 microbatch 需十个操作，题面 §3.2）", at=at))
        if missing > len(examples):
            _add(errors, _error("missing", f"还有 {missing - len(examples)} 个操作缺失（共缺 {missing} 个）"))
    return ok


# --------------------------------------------------------------------------- #
# 模拟（题面 §4.2 / §4.5）
# --------------------------------------------------------------------------- #


@dataclass
class _Plan:
    """由输入 + 网格 + PSI + MAP 推出的逐层常量。"""

    V: int
    P: int
    D: int
    K: int
    psi_full: tuple[int, ...]
    layers_of_group: list[list[int]]
    group_of_layer: list[int]
    durations: list[tuple[int, ...]]
    m: list[int]
    x: list[int]
    payload: list[int]
    pin: int
    pout: int
    lb: int
    #: ``deps[ℓ][op] = ((ℓ', op'), …)``：该操作的全部前置（含跨层）。
    deps: list[list[tuple[tuple[int, int], ...]]]


def _dependency_table(L: int) -> list[list[tuple[tuple[int, int], ...]]]:
    table: list[list[tuple[tuple[int, int], ...]]] = []
    for layer in range(L):
        per_layer: list[tuple[tuple[int, int], ...]] = []
        for oi in range(10):
            deps: list[tuple[int, int]] = [(layer, other) for other in DEPS[oi]]
            if oi == _OI_S and layer > 0:
                deps.append((layer - 1, _OI_COMB))  # 层 ℓ 的前向等层 ℓ−1 的 comb
            if oi == _OI_S_BWD and layer < L - 1:
                deps.append((layer + 1, _OI_DISP_BWD))  # 层 ℓ 的反向等层 ℓ+1 的 disp_bwd
            per_layer.append(tuple(deps))
        table.append(per_layer)
    return table


def _build_plan(case: Case, out: Output) -> _Plan:
    psi_full = (0,) + tuple(out.psi) + (case.L,)
    layers = group_layers(out.V, psi_full)
    mapping = group_of_layer(out.V, psi_full, case.L)
    pin, pout = peer_counts(case, out.V, out.P, out.D)
    durations: list[tuple[int, ...]] = []
    ms: list[int] = []
    xs: list[int] = []
    payloads: list[int] = []
    for layer in range(case.L):
        m = layer_m(case, layer, out.P, out.map_rows[layer])
        payload = comm_payload(case, layer, out.P)
        x = comm_time(case, payload, pin, pout)
        ms.append(m)
        payloads.append(payload)
        xs.append(x)
        durations.append(layer_durations(case, layer, m, x))
    return _Plan(
        V=out.V,
        P=out.P,
        D=out.D,
        K=out.K,
        psi_full=psi_full,
        layers_of_group=layers,
        group_of_layer=mapping,
        durations=durations,
        m=ms,
        x=xs,
        payload=payloads,
        pin=pin,
        pout=pout,
        lb=lower_bound(case, durations, layers),
        deps=_dependency_table(case.L),
    )


def _simulate(case: Case, plan: _Plan, rows: Rows, errors: list[dict]) -> tuple[bool, list[int], list[int]]:
    """两趟模拟，返回 ``(ok, start, end)``。

    **第 1 趟 · 登记**：遍历全部行，把每个 ``(mb, ℓ, op)`` 的 ``(start, end)`` 写进扁平
    数组。``t`` 非降与 ``mb``/``ℓ``/``op`` 合法性、重复/缺失已在
    :func:`_check_schedule_tokens` / :func:`_check_coverage` 查过，这一趟不看行序。

    **第 2 趟 · 检查**（题面 §3.2 只要求 ``t`` 非降，§4.2.4 只比较时刻，行序没有语义）：

    * 依赖 + 因果性：逐个操作比较 ``t >= dep_end``，全量检查，与写在哪个行无关；
    * 引擎互斥：按 ``(卡组, 引擎)`` 收集 ``dur > 0`` 的 ``[t, t+dur)`` 区间，按起点排序后
      要求 ``next.start >= prev.end``。**时长 0 的操作不占用引擎，相等时刻释放合法。**

    这样同一时刻写在多行、或行内顺序被打乱，都不会改变判定（F1 修复）。
    """
    L = case.L
    stride = L * 10
    size = case.nmb * stride
    start = [-1] * size
    end = [-1] * size
    durations = plan.durations
    group_of = plan.group_of_layer
    deps = plan.deps

    # ---- 第 1 趟：登记全部 (start, end)；行序不参与语义 ----
    for t, items in rows:
        for (mb, layer, oi, _at) in items:
            index = mb * stride + layer * 10 + oi
            start[index] = t
            end[index] = t + durations[layer][oi]

    ok = True

    # ---- 第 2 趟 a：依赖 + 因果性（t >= 前置完成时刻）----
    for t, items in rows:
        for (mb, layer, oi, at) in items:
            for (dep_layer, dep_oi) in deps[layer][oi]:
                dep_end = end[mb * stride + dep_layer * 10 + dep_oi]
                if dep_end < 0:
                    # 覆盖检查已保证每个操作都被登记；留作防御（未来若允许部分调度）
                    ok = False
                    dep_at = f"{mb}:{dep_layer}:{OP_NAMES[dep_oi]}"
                    _add(
                        errors,
                        _error(
                            "dependency",
                            f"{at} 的前置 {dep_at} 没有登记在调度里（内部不一致）",
                            t=t,
                            at=at,
                            depends_on=dep_at,
                        ),
                    )
                elif t < dep_end:
                    ok = False
                    dep_at = f"{mb}:{dep_layer}:{OP_NAMES[dep_oi]}"
                    _add(
                        errors,
                        _error(
                            "dependency",
                            f"{at} 在 t={t} 开始，早于前置 {dep_at} 的完成时刻 {dep_end}"
                            f"（差 {dep_end - t}；题面 §4.2 第 1/2/4 条）",
                            t=t,
                            at=at,
                            depends_on=dep_at,
                            dep_end=dep_end,
                        ),
                    )

    # ---- 第 2 趟 b：引擎互斥（按 (卡组, 引擎) 收集区间，排序后查重叠）----
    intervals: dict[tuple[int, int], list[tuple[int, int, str]]] = {}
    for t, items in rows:
        for (_mb, layer, oi, at) in items:
            duration = durations[layer][oi]
            if duration <= 0:
                continue  # 零时长不占用引擎
            intervals.setdefault((group_of[layer], ENGINE[oi]), []).append(
                (t, t + duration, at)
            )
    for key in sorted(intervals):
        group, engine = key
        booked = intervals[key]
        booked.sort()  # 按 (start, end, at)；对已按 t 排好的序列 Timsort 是 O(n)
        previous_at: Optional[str] = None
        previous_end = -1
        for (begin, finish, at) in booked:
            if begin < previous_end:
                ok = False
                _add(
                    errors,
                    _error(
                        "engine",
                        f"{at} 需要{_ENGINE_NAME[engine]}引擎，但卡组 {group} 的该引擎到 "
                        f"t={previous_end} 仍被 {previous_at} 占用（题面 §4.2 第 3 条）",
                        t=begin,
                        at=at,
                        conflicts_with=previous_at,
                        group=group,
                        engine=_ENGINE_NAME[engine],
                    ),
                )
            else:
                previous_at = at
                previous_end = finish
    return ok, start, end


# --------------------------------------------------------------------------- #
# 装配
# --------------------------------------------------------------------------- #


def _op_code(mb: int, layer: int, oi: int) -> tuple[int, int, int]:
    """报错定位用的 witness（只在内存超限时才被格式化成 ``mb:ℓ:op``）。"""
    return mb, layer, oi


def _code_text(code: object) -> Optional[str]:
    """witness → ``mb:ℓ:op``。"""
    if isinstance(code, tuple) and len(code) == 3:
        mb, layer, oi = code
        return f"{mb}:{layer}:{OP_NAMES[oi]}"
    return None if code is None else str(code)


def _comm_stream(plan: _Plan, rows: Rows) -> Iterator[tuple[int, int, int, object]]:
    """按 ``start`` 非降给出 ``(卡组, 起, 止, witness)`` 的通信缓冲流（题面 §4.6）。"""
    durations = plan.durations
    group_of = plan.group_of_layer
    for t, items in rows:
        for (mb, layer, oi, _at) in items:
            if ENGINE[oi] != COMM:
                continue
            yield group_of[layer], t, t + durations[layer][oi], _op_code(mb, layer, oi)


def _activation_intervals(
    case: Case, plan: _Plan, start: Sequence[int], end: Sequence[int]
) -> list[list[memory_mod.Interval]]:
    """激活区间 ``[comb 结束, s_bwd 开始]``，逐卡组（闭区间，题面 §4.6）。"""
    stride = case.L * 10
    intervals: list[list[memory_mod.Interval]] = [[] for _ in range(plan.V)]
    group_of = plan.group_of_layer
    for mb in range(case.nmb):
        for layer in range(case.L):
            base = mb * stride + layer * 10
            intervals[group_of[layer]].append(
                (end[base + _OI_COMB], start[base + _OI_S_BWD], _op_code(mb, layer, _OI_COMB))
            )
    return intervals


def _engines(case: Case, plan: _Plan, rows: Rows) -> list[dict]:
    """每卡组两套引擎的工作量与通信首尾（CONTRACT §1 的 ``engines`` 字段）。"""
    first: list[Optional[int]] = [None] * plan.V
    last: list[Optional[int]] = [None] * plan.V
    durations = plan.durations
    group_of = plan.group_of_layer
    for t, items in rows:
        for (_mb, layer, oi, _at) in items:
            if ENGINE[oi] != COMM:
                continue
            group = group_of[layer]
            if first[group] is None or t < first[group]:
                first[group] = t
            finish = t + durations[layer][oi]
            if last[group] is None or finish > last[group]:
                last[group] = finish
    engines: list[dict] = []
    for group in range(plan.V):
        layers = plan.layers_of_group[group]
        compute = case.nmb * sum(plan.durations[layer][oi] for layer in layers for oi in COMP_OPS)
        comm = case.nmb * sum(plan.durations[layer][oi] for layer in layers for oi in COMM_OPS)
        engines.append(
            {
                "v": group,
                "comp": compute,
                "comm": comm,
                "comm_first": first[group],
                "comm_last": last[group],
            }
        )
    return engines


def _ops_payload(plan: _Plan, rows: Rows) -> list[dict]:
    """给服务层 / CLI 的扁平 ops（CONTRACT §2.5 的字段名）。"""
    durations = plan.durations
    group_of = plan.group_of_layer
    return [
        {
            "t": t,
            "mb": mb,
            "l": layer,
            "op": OP_NAMES[oi],
            "dur": durations[layer][oi],
            "g": group_of[layer],
        }
        for (t, items) in rows
        for (mb, layer, oi, _at) in items
    ]


def evaluate_output(case: Case, out: Output, with_ops: bool = True) -> tuple[dict, list[dict]]:
    """校验并模拟一份输出。

    返回 ``(result, ops)``：``result`` 即 CONTRACT §1 的响应体（不含 ``ops``），
    ``ops`` 供服务层写 ``runs/ops/<run_id>/<case>.jsonl``（CONTRACT §3）。
    ``with_ops=False`` 时不必展开 ops（纯评估路径，省掉 64 万条 dict 的分配）。
    """
    errors: list[dict] = []
    result: dict = {
        "ok": False,
        "time": None,
        "lb": None,
        "groups": [],
        "engines": [],
        "grid": {"V": out.V, "P": out.P, "D": out.D},
        "K": out.K,
        "psi": list(out.psi),
        "errors": errors,
    }

    if not _check_grid(case, out, errors):
        return result, []
    if not _check_psi(case, out, errors):
        return result, []
    if not _check_map(case, out, errors):
        return result, []

    plan = _build_plan(case, out)
    result["lb"] = plan.lb

    rows, tokens_ok = _check_schedule_tokens(case, out, errors)
    if not tokens_ok:
        return result, []
    if not _check_coverage(case, rows, errors):
        return result, []

    simulated_ok, start, end = _simulate(case, plan, rows, errors)
    ops = _ops_payload(plan, rows) if with_ops else []
    if not simulated_ok:
        return result, ops

    result["engines"] = _engines(case, plan, rows)
    comm_peaks = memory_mod.streamed_peaks(_comm_stream(plan, rows), plan.V)
    groups, details = memory_mod.group_memory(
        case, plan.layers_of_group, comm_peaks, _activation_intervals(case, plan, start, end), plan.P
    )
    result["groups"] = groups
    for group, detail in zip(groups, details):
        used = group["mexp"] + group["movl"] + group["mact"]
        if used <= case.M:
            continue
        if detail["peak_act"] > 0 and (case.Uact * detail["peak_act"] >= case.U * detail["peak_comm"]):
            t = detail["time_act"]
            at = _code_text(detail["tag_act"])
        else:
            t = detail["time_comm"]
            at = _code_text(detail["tag_comm"])
        _add(
            errors,
            _error(
                "memory",
                f"内存超限：卡组 {group['v']} 的 Mexp+Movl+Mact="
                f"{group['mexp']}+{group['movl']}+{group['mact']}={used} > M={case.M}"
                f"（Mexp={group['mexp']}，通信峰值 {detail['peak_comm']} 块 @t={detail['time_comm']}，"
                f"激活峰值 {detail['peak_act']} 份 @t={detail['time_act']}；题面 §4.6/§4.7）",
                t=t,
                at=at,
                group=group["v"],
                mexp=group["mexp"],
                movl=group["movl"],
                mact=group["mact"],
                limit=case.M,
            ),
        )
    if errors:
        return result, ops

    result["ok"] = True
    result["time"] = max(end)
    return result, ops
