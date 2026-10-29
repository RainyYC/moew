"""求解器侧自算的题面量（m_l / x_l / 十种操作时长 / 卡组 / 下界）。

⚠️ 这份实现是**给搜索用的**：求解器必须知道每层 ``m_l``、``x_l`` 才能排调度与剪枝
（任务书明确允许的重复）。判分权威仍然是 `judge/core`（CONTRACT §0 铁律）；最终合法性
只认 ``python3 -m judge eval`` 子进程的判定（`solver/judgebridge.py`）。

全整数运算，公式逐条对照题面 §4：

* ``s = T·Fs``、``gemm = m·Fin``（§4.1）
* ``H = ⌊d·b/k⌋``、``X = ⌈T·H/P⌉``（每对端字节数）、``x = max(⌈pin·X/Bin⌉, ⌈pout·X/Bout⌉)·Fio``（§4.4）
* ``m = max_r Σ_{e: σ(e)=r} a_{l,e}``（§4.3）
* 反向按题面 §4.1 的单次向上取整展开：``ceil(α·v) = ⌈α×·v/10^6⌉``、
  ``ceil(αβ·v) = ⌈α×·β×·v/10^12⌉``
* 卡组：``g(k) = k (k<V)``，``K=2V`` 时 ``g(k) = 2V−1−k``（§3.1）
* 下界：``lb = max_v nmb·max(ΣC_v, ΣWc_v)``（§4.2 第 3 条 / CONTRACT §6）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .casein import Case

__all__ = [
    "MICRO",
    "MICRO2",
    "OP_NAMES",
    "OP_INDEX",
    "COMP",
    "COMM",
    "ENGINE",
    "COMP_OPS",
    "COMM_OPS",
    "DEPS",
    "ceil_div",
    "layer_slots",
    "peer_counts",
    "comm_payload",
    "comm_time",
    "layer_m",
    "layer_durations",
    "group_layers",
    "group_of_layer",
    "lower_bound",
    "Plan",
    "build_plan",
    "build_plan_from_parts",
]

MICRO = 10**6
MICRO2 = 10**12

#: 题面 §4.1 的十个操作，顺序即内部索引。
OP_NAMES: tuple[str, ...] = (
    "s",
    "disp",
    "gemm",
    "comb",
    "s_bwd",
    "comb_bwd",
    "gemm_dx",
    "gemm_dw",
    "disp_bwd",
    "s_dw",
)
OP_INDEX: dict[str, int] = {name: index for index, name in enumerate(OP_NAMES)}

OP_S, OP_DISP, OP_GEMM, OP_COMB = 0, 1, 2, 3
OP_S_BWD, OP_COMB_BWD, OP_GEMM_DX, OP_GEMM_DW, OP_DISP_BWD, OP_S_DW = 4, 5, 6, 7, 8, 9

COMP, COMM = 0, 1
#: 每个操作占用的引擎（题面 §4.1）。
ENGINE: tuple[int, ...] = (COMP, COMM, COMP, COMM, COMP, COMM, COMP, COMP, COMM, COMP)
COMP_OPS: tuple[int, ...] = tuple(i for i, engine in enumerate(ENGINE) if engine == COMP)
COMM_OPS: tuple[int, ...] = tuple(i for i, engine in enumerate(ENGINE) if engine == COMM)

#: 层内依赖（题面 §4.2 第 1 条，2026-10-29 修订版）：
#: **共享专家（``s``/``s_bwd``/``s_dw``）与同层其余操作解耦**，可与分发/专家计算/汇集重叠。
#: 前向 MoE 链变为 ``disp → gemm → comb``；反向 MoE 链的头是 ``comb_bwd``；
#: 共享专家自身保持 ``s → s_bwd → s_dw``。与 `judge/core/model.DEPS` 逐项一致。
DEPS: tuple[tuple[int, ...], ...] = (
    (),  # s
    (),  # disp（不再等 s；跨层边由 sched 加）
    (OP_DISP,),  # gemm
    (OP_GEMM, OP_S),  # comb（共享专家前向须在 comb 之前收尾）
    (OP_COMB,),  # s_bwd
    (OP_COMB,),  # comb_bwd（反向链的头）
    (OP_COMB_BWD,),  # gemm_dx
    (OP_COMB_BWD,),  # gemm_dw
    (OP_GEMM_DX, OP_S_BWD),  # disp_bwd（须等共享专家的输入梯度）
    (OP_COMB_BWD,),  # s_dw
)


def ceil_div(a: int, b: int) -> int:
    """``ceil(a / b)``（``b > 0``），不做 float 运算。"""
    if b <= 0:
        raise ZeroDivisionError(f"ceil_div 的分母必须为正，得到 {b}")
    return -((-a) // b)


# --------------------------------------------------------------------------- #
# 负载、放置与计算时长（题面 §4.3）
# --------------------------------------------------------------------------- #


def layer_slots(case: Case, layer: int) -> tuple[int, ...]:
    """层 ``layer`` 逐专家的 slot 数；无负载向量时把 ``T_l`` 尽量均分给 E 个专家。"""
    load = case.loads[layer]
    if load is not None:
        return load
    base, remainder = divmod(case.T[layer], case.E)
    if remainder == 0:
        return (base,) * case.E
    return tuple(base + (1 if expert < remainder else 0) for expert in range(case.E))


# --------------------------------------------------------------------------- #
# 通信时长（题面 §4.4）
# --------------------------------------------------------------------------- #


def peer_counts(case: Case, V: int, P: int) -> tuple[int, int]:
    """EP 组内单 rank 的 (pin, pout)（题面 §4.4）。

    按题面 §3.1 的嵌入 ``q = v·P + p`` 从物理卡复核：P=1 时没有 EP 对端，返回
    ``(0, 0)``；否则要求 ``P∣S`` 或 ``S∣P``（保证 EP 组与节点对齐）。
    2026-10-29 修订后网格约束是 ``V·P ≤ R``，未用到的卡不参与本步。
    """
    if P == 1:
        return 0, 0
    if V * P > case.R:
        raise ValueError(f"V·P={V * P} > R={case.R}，无法嵌入物理卡")
    seen: set[tuple[int, int]] = set()
    for v in range(V):
        first = v * P
        nodes = [(first + p) // case.S for p in range(P)]
        pin = sum(1 for node in nodes if node == nodes[0]) - 1
        seen.add((pin, P - 1 - pin))
    if len(seen) != 1:
        raise ValueError(f"EP 组未与节点对齐：得到多组 (pin,pout)={sorted(seen)}")
    return seen.pop()


def comm_payload(case: Case, layer: int, P: int) -> int:
    """每 rank 每层发往一个对端的字节数 ``X_l = ⌈T_l·H·(P−1)/P⌉``。"""
    if P <= 1:
        return 0
    return ceil_div(case.T[layer] * case.H, P)  # 每对端字节数（§4.4 修订版）


def comm_time(case: Case, payload: int, pin: int, pout: int) -> int:
    """一次 AllToAll 的时长 ``x_l = max(⌈pin·X/Bin⌉, ⌈pout·X/Bout⌉)·Fio``。"""
    if payload <= 0:
        return 0
    node_in = ceil_div(pin * payload, case.Bin) if pin else 0
    node_out = ceil_div(pout * payload, case.Bout) if pout else 0
    return max(node_in, node_out) * case.Fio


def layer_m(case: Case, layer: int, P: int, map_row: Sequence[int]) -> int:
    """``m_l = max_r Σ_{e: σ_{l,e}=r} a_{l,e}``（题面 §4.3）。"""
    slots = layer_slots(case, layer)
    per_rank = [0] * P
    for expert, count in enumerate(slots):
        per_rank[map_row[expert]] += count
    return max(per_rank)


def layer_durations(case: Case, layer: int, m: int, x: int) -> tuple[int, ...]:
    """层 ``layer`` 十个操作的时长，顺序与 :data:`OP_NAMES` 一致（题面 §4.1）。"""
    s = case.T[layer] * case.Fs
    gemm = m * case.Fin
    alpha = case.alpha_x
    alpha_beta = case.alpha_x * case.beta_x
    s_bwd = ceil_div(alpha * s, MICRO)
    comm_bwd = ceil_div(alpha * x, MICRO)
    return (
        s,  # s
        x,  # disp
        gemm,  # gemm
        x,  # comb
        s_bwd,  # s_bwd
        comm_bwd,  # comb_bwd
        ceil_div(alpha * gemm, MICRO),  # gemm_dx
        ceil_div(alpha_beta * gemm, MICRO2),  # gemm_dw
        comm_bwd,  # disp_bwd
        ceil_div(alpha_beta * s, MICRO2),  # s_dw
    )


# --------------------------------------------------------------------------- #
# 卡组（题面 §3.1 / §4.6）
# --------------------------------------------------------------------------- #


def group_layers(V: int, psi_full: Sequence[int]) -> list[list[int]]:
    """每个卡组持有的层号（升序）。本求解器只产出 ``K=V``（每卡组一块）。"""
    K = len(psi_full) - 1
    layers: list[list[int]] = [[] for _ in range(V)]
    for block in range(K):
        group = block if block < V else 2 * V - 1 - block
        layers[group].extend(range(psi_full[block], psi_full[block + 1]))
    for group in layers:
        group.sort()
    return layers


def group_of_layer(V: int, psi_full: Sequence[int], L: int) -> list[int]:
    """每个层号 → 卡组号。"""
    mapping = [0] * L
    for layer in range(L):
        low, high = 0, len(psi_full) - 1
        while low + 1 < high:
            mid = (low + high) // 2
            if psi_full[mid] <= layer:
                low = mid
            else:
                high = mid
        mapping[layer] = low if low < V else 2 * V - 1 - low
    return mapping


def lower_bound(case: Case, durations: Sequence[Sequence[int]], layers: Sequence[Sequence[int]]) -> int:
    """``lb = max_v nmb·max(ΣC_v, ΣWc_v)``：每个卡组两套引擎各自串行完成全部工作量。"""
    best = 0
    for group_layers_of_v in layers:
        compute = 0
        comm = 0
        for layer in group_layers_of_v:
            row = durations[layer]
            compute += sum(row[i] for i in COMP_OPS)
            comm += sum(row[i] for i in COMM_OPS)
        bound = case.nmb * max(compute, comm)
        if bound > best:
            best = bound
    return best


# --------------------------------------------------------------------------- #
# 一份候选映射的静态常量
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Plan:
    """由输入 + 网格 + PSI + MAP 推出的逐层常量（排调度所需的一切）。"""

    V: int
    P: int
    D: int
    K: int
    psi: tuple[int, ...]
    psi_full: tuple[int, ...]
    layers_of_group: tuple[tuple[int, ...], ...]
    first_layer_of_group: tuple[int, ...]
    group_of_layer: tuple[int, ...]
    durations: tuple[tuple[int, ...], ...]
    m: tuple[int, ...]
    x: tuple[int, ...]
    payload: tuple[int, ...]
    pin: int
    pout: int
    lb: int


def build_plan_from_parts(
    case: Case,
    V: int,
    P: int,
    D: int,
    psi: Sequence[int],
    map_rows: Sequence[Sequence[int]],
    m: Sequence[int],
    x: Sequence[int],
    payload: Sequence[int],
    durations: Sequence[Sequence[int]],
) -> Plan:
    """由已算好的逐层量装配 :class:`Plan`（避免重复计算 m/x/时长）。"""
    psi_full = (0,) + tuple(psi) + (case.L,)
    layers = group_layers(V, psi_full)
    mapping = group_of_layer(V, psi_full, case.L)
    pin, pout = peer_counts(case, V, P)
    return Plan(
        V=V,
        P=P,
        D=D,
        K=V,
        psi=tuple(psi),
        psi_full=psi_full,
        layers_of_group=tuple(tuple(row) for row in layers),
        first_layer_of_group=tuple(row[0] for row in layers),
        group_of_layer=tuple(mapping),
        durations=tuple(tuple(row) for row in durations),
        m=tuple(m),
        x=tuple(x),
        payload=tuple(payload),
        pin=pin,
        pout=pout,
        lb=lower_bound(case, durations, layers),
    )


def build_plan(
    case: Case,
    V: int,
    P: int,
    D: int,
    psi: Sequence[int],
    map_rows: Sequence[Sequence[int]],
) -> Plan:
    """完整的 :class:`Plan`（自己算 m / x / 时长）。"""
    pin, pout = peer_counts(case, V, P)
    m = [layer_m(case, layer, P, map_rows[layer]) for layer in range(case.L)]
    payload = [comm_payload(case, layer, P) for layer in range(case.L)]
    x = [comm_time(case, payload[layer], pin, pout) for layer in range(case.L)]
    durations = [layer_durations(case, layer, m[layer], x[layer]) for layer in range(case.L)]
    return build_plan_from_parts(case, V, P, D, psi, map_rows, m, x, payload, durations)


def compute_layer_quantities(
    case: Case, P: int, pin: int, pout: int, map_rows: Sequence[Sequence[int]]
) -> tuple[list[int], list[int], list[int], list[tuple[int, ...]]]:
    """按 P/(pin,pout)/MAP 算逐层 ``(m, payload, x, durations)``。"""
    m = [layer_m(case, layer, P, map_rows[layer]) for layer in range(case.L)]
    payload = [comm_payload(case, layer, P) for layer in range(case.L)]
    x = [comm_time(case, payload[layer], pin, pout) for layer in range(case.L)]
    durations = [layer_durations(case, layer, m[layer], x[layer]) for layer in range(case.L)]
    return m, payload, x, durations
