"""题面 §4 的公式实现（**唯一权威**，CONTRACT §0 铁律）。

全整数运算
----------
所有时长 / 内存量都是 Python ``int``；本模块不使用 ``float``、不使用真除法 ``/``。
反向系数按题面 §4.1 的单次向上取整展开：

* ``ceil(α·v)   = ceil_div(α×·v, 10^6)``
* ``ceil(αβ·v)  = ceil_div(α×·β×·v, 10^12)``

操作表（题面 §4.1）
-------------------
=========  ======  ============
操作       引擎    时长
=========  ======  ============
s          计算    s_l
disp       通信    x_l
gemm       计算    m_l·Fin
comb       通信    x_l
s_bwd      计算    α·s_l
comb_bwd   通信    α·x_l
gemm_dx    计算    α·m_l·Fin
gemm_dw    计算    α·β·m_l·Fin
disp_bwd   通信    α·x_l
s_dw       计算    α·β·s_l
=========  ======  ============
"""

from __future__ import annotations

from typing import Sequence

from .parse import Case

__all__ = [
    "MICRO",
    "MICRO2",
    "OP_NAMES",
    "OP_INDEX",
    "ENGINE",
    "COMP",
    "COMM",
    "COMP_OPS",
    "COMM_OPS",
    "COMM_NAMES",
    "DEPS",
    "ceil_div",
    "layer_slots",
    "peer_counts",
    "comm_payload",
    "comm_time",
    "layer_m",
    "layer_durations",
    "layer_block",
    "block_group",
    "group_layers",
    "group_of_layer",
    "lower_bound",
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

COMP = 0
COMM = 1
#: 每个操作占用的引擎（题面 §4.1）。
ENGINE: tuple[int, ...] = (COMP, COMM, COMP, COMM, COMP, COMM, COMP, COMP, COMM, COMP)
COMP_OPS: tuple[int, ...] = tuple(i for i, engine in enumerate(ENGINE) if engine == COMP)
COMM_OPS: tuple[int, ...] = tuple(i for i, engine in enumerate(ENGINE) if engine == COMM)
COMM_NAMES: frozenset[str] = frozenset(OP_NAMES[i] for i in COMM_OPS)

#: 层内依赖：操作为索引 → 必须先完成的同层操作（题面 §4.2 第 1 条）。
#:
#: 2026-10-29 修订：**共享专家（``s`` / ``s_bwd`` / ``s_dw``）与同层其余操作解耦**。
#:
#: * 前向：``disp`` 不再等 ``s`` ⇒ 共享专家前向可与分发/专家计算/汇集重叠；
#: * 反向：``comb_bwd`` 不再等 ``s_bwd``，改为等本层 ``comb``（"前向完成才反向"这条
#:   因果仍然成立，只是不再穿过共享专家）⇒ 共享专家反向可与反向链重叠；
#: * ``s_dw`` 只等 ``s_bwd``（自己的输入梯度），不再等 ``comb_bwd``；
#: * ``s_bwd ≥ comb`` 保留（本层前向完成后才能算它的输入梯度）。
DEPS: tuple[tuple[int, ...], ...] = (
    (),  # s（共享专家前向：同层无前驱）
    (),  # disp（不再等 s：共享专家前向可重叠；跨层的"上一层的 comb"在 sim 里加）
    (OP_INDEX["disp"],),  # gemm
    (OP_INDEX["gemm"],),  # comb
    (OP_INDEX["s"], OP_INDEX["comb"]),  # s_bwd（自己的前向 + 本层前向完成）
    (OP_INDEX["comb"],),  # comb_bwd（反向链的头：等本层前向，不再等 s_bwd）
    (OP_INDEX["comb_bwd"],),  # gemm_dx
    (OP_INDEX["comb_bwd"],),  # gemm_dw
    (OP_INDEX["gemm_dx"],),  # disp_bwd
    (OP_INDEX["s_bwd"],),  # s_dw（只等共享专家的输入梯度）
)


def ceil_div(a: int, b: int) -> int:
    """整数向上取整除法 ``ceil(a / b)``（``b > 0``），不做 float 运算。"""
    if b <= 0:  # pragma: no cover - 输入校验已保证
        raise ZeroDivisionError(f"ceil_div 的分母必须为正，得到 {b}")
    return -((-a) // b)


# --------------------------------------------------------------------------- #
# 负载、放置与计算时长（题面 §4.3）
# --------------------------------------------------------------------------- #


def layer_slots(case: Case, layer: int) -> tuple[int, ...]:
    """层 ``layer`` 逐专家的 slot 数 ``a_{l,e}``。

    输入没带负载向量时，评测器把 ``T_l`` 尽量均分给 ``E`` 个专家：前
    ``T_l % E`` 个各多 1（题面 §4.3）。
    """
    load = case.loads[layer]
    if load is not None:
        return load
    total = case.T[layer]
    base, remainder = divmod(total, case.E)
    return tuple(base + (1 if expert < remainder else 0) for expert in range(case.E))


# --------------------------------------------------------------------------- #
# 通信时长（题面 §4.4）
# --------------------------------------------------------------------------- #


def peer_counts(case: Case, V: int, P: int) -> tuple[int, int]:
    """一个 EP 组内单个 rank 的 (节点内对端数 pin, 跨节点对端数 pout)。

    按题面 §3.1 的嵌入 ``q = v·P + p`` 直接从物理卡复核：卡 ``q`` 属于节点
    ``q // S``。``P∣S`` 或 ``S∣P`` 保证每个 EP 组要么整组落在节点内、要么整齐
    跨节点，因此同一份映射下所有 (v,p) 的 (pin, pout) 相同。

    2026-10-29 修订把网格约束放松为 ``V·P ≤ R``（不要求用满所有卡），因此这里只按
    前 ``V·P`` 张卡计算，剩余卡不参与本步（等价于数据并行副本，不影响单步时间）。
    """
    if P == 1:
        return 0, 0
    if V * P > case.R:  # pragma: no cover - 调用前已校验
        raise ValueError(f"V·P={V * P} > R={case.R}，无法嵌入物理卡")
    seen: set[tuple[int, int]] = set()
    for v in range(V):
        first = v * P
        nodes = [(first + p) // case.S for p in range(P)]
        pin = sum(1 for node in nodes if node == nodes[0]) - 1
        seen.add((pin, P - 1 - pin))
    if len(seen) != 1:  # pragma: no cover - P∣S 或 S∣P 保证不会发生
        raise ValueError(f"EP 组未与节点对齐：得到多组 (pin,pout)={sorted(seen)}")
    return seen.pop()


def comm_payload(case: Case, layer: int, P: int) -> int:
    """每个**对端**的字节数 ``X_l = ceil(T_l·H / P)``（题面 §4.4 2026-10 修订版）。

    注意不是 ``T_l·H·(P-1)/P``——那是发给**所有**对端的总量；而 ``x_l`` 的公式里又乘了
    ``pin``/``pout``，若两者都按总量算会重复计费（P≥3 时差 (P-1) 倍）。P=2 时两式相同，
    所以旧版题面的六个样例都掩盖了这个差别。
    """
    if P <= 1:
        return 0
    return ceil_div(case.T[layer] * case.H, P)


def comm_time(case: Case, payload: int, pin: int, pout: int) -> int:
    """一次 AllToAll 的时长 ``x_l``（题面 §4.4）。

    ``x_l = max(⌈pin·X_l / Bin⌉, ⌈pout·X_l / Bout⌉) · Fio``；``pin = pout = 0``
    （``P = 1``）时 ``X_l = 0``、``x_l = 0``，通信类操作以 0 时长出现。
    """
    if payload <= 0:
        return 0
    node_in = ceil_div(pin * payload, case.Bin) if pin else 0
    node_out = ceil_div(pout * payload, case.Bout) if pout else 0
    return max(node_in, node_out) * case.Fio


def layer_m(case: Case, layer: int, P: int, map_row: Sequence[int]) -> int:
    """``m_l = max_r Σ_{e: σ_{l,e}=r} a_{l,e}``（题面 §4.3）。

    计算类操作取**组内最慢 rank**：某个 rank 上的专家越热，整层就得等它。偏斜只抬高
    计算，不改变通信量 ``X_l``（后者只依赖 ``T_l``）。
    """
    slots = layer_slots(case, layer)
    per_rank = [0] * P
    for expert, count in enumerate(slots):
        per_rank[map_row[expert]] += count
    return max(per_rank)


def layer_durations(case: Case, layer: int, m: int, x: int) -> tuple[int, ...]:
    """层 ``layer`` 十个操作的时长，顺序与 :data:`OP_NAMES` 一致。"""
    s = case.T[layer] * case.Fs
    gemm = m * case.Fin
    alpha = case.alpha_x
    alpha_beta = case.alpha_x * case.beta_x
    s_bwd = ceil_div(alpha * s, MICRO)
    comb_bwd = ceil_div(alpha * x, MICRO)
    return (
        s,  # s
        x,  # disp
        gemm,  # gemm
        x,  # comb
        s_bwd,  # s_bwd
        comb_bwd,  # comb_bwd
        ceil_div(alpha * gemm, MICRO),  # gemm_dx
        ceil_div(alpha_beta * gemm, MICRO2),  # gemm_dw
        comb_bwd,  # disp_bwd
        ceil_div(alpha_beta * s, MICRO2),  # s_dw
    )


# --------------------------------------------------------------------------- #
# PSI / 块 / 卡组（题面 §3.1、§4.6）
# --------------------------------------------------------------------------- #


def layer_block(psi_full: Sequence[int], layer: int) -> int:
    """层 ``layer`` 落在哪一块（``psi_full = [0, ψ_1, …, ψ_{K−1}, L]``）。"""
    low, high = 0, len(psi_full) - 1
    while low + 1 < high:
        mid = (low + high) // 2
        if psi_full[mid] <= layer:
            low = mid
        else:
            high = mid
    return low


def block_group(block: int, V: int) -> int:
    """块 → 卡组：``g(k) = k (k<V)``，否则镜像配对 ``2V−1−k``（题面 §3.1）。"""
    return block if block < V else 2 * V - 1 - block


def group_layers(V: int, psi_full: Sequence[int]) -> list[list[int]]:
    """每个卡组持有的层号（升序）。``K = 2V`` 时一个卡组持有两块。"""
    K = len(psi_full) - 1
    layers: list[list[int]] = [[] for _ in range(V)]
    for block in range(K):
        group = block_group(block, V)
        layers[group].extend(range(psi_full[block], psi_full[block + 1]))
    for group in layers:
        group.sort()
    return layers


def group_of_layer(V: int, psi_full: Sequence[int], L: int) -> list[int]:
    """每个层号 → 卡组号。"""
    mapping = [0] * L
    for layer in range(L):
        mapping[layer] = block_group(layer_block(psi_full, layer), V)
    return mapping


# --------------------------------------------------------------------------- #
# 下界（CONTRACT §6 / 题面 §4.2 第 3 条）
# --------------------------------------------------------------------------- #


def lower_bound(case: Case, durations: Sequence[Sequence[int]], layers: Sequence[Sequence[int]]) -> int:
    """``lb = max_v nmb·max(ΣC_v, ΣWc_v)``。

    每个卡组的两套引擎各自串行执行全部 microbatch 的工作量，这是不可压缩的下界
    （题面 §4.2 第 3 条；CONTRACT §1 的 ``lb`` 字段）。
    """
    best = 0
    for group_layers_of_v in layers:
        compute = 0
        comm = 0
        for layer in group_layers_of_v:
            row = durations[layer]
            compute += sum(row[index] for index in COMP_OPS)
            comm += sum(row[index] for index in COMM_OPS)
        best = max(best, case.nmb * max(compute, comm))
    return best
