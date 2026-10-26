#!/usr/bin/env python3
"""独立复核 ex3 的最优值 6072：穷举两张通信引擎的操作次序，不用 OR-Tools。

原理
----
给定「每台引擎上操作的先后次序」，把每个操作尽量早地排下去（start = max(前驱结束)）
得到该次序下最早的调度。任何真实调度都对应某个次序，因此

    min over 全部次序 = 真正的最优 makespan

这是个**松弛**：计算引擎上的互斥被去掉（等价于假设计算引擎容量无限）。去掉约束只会让
最小值更小，所以如果松弛后的最小值仍是 6072，真实最优就不可能低于 6072；而 6072 已经有
一份合法解（opt/global/ex3-V2P2D1-6072.out，判题器判过），于是 6072 = 最优。

规模
----
* P=2, V=2：两个卡组各持一层，通信引擎各 8 个操作。每个 microbatch 有
  disp<comb、comb_bwd<disp_bwd 两条链 => 8!/(2!^4) = 2520 种次序；两个卡组 => 2520^2，
  再用"两个 microbatch 可互换"对称性固定第一个操作，降到约 79 万。
* P=4, V=1：单卡组 16 个通信操作，两个 microbatch 各一条 8 长链 => C(16,8) = 12870。

用法：
    python3 tools/ex3_verify.py
    python3 tools/ex3_verify.py --zero-compute     # 消融：计算时长归零
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from judge.core.model import (  # noqa: E402
    comm_payload, comm_time, layer_durations, layer_slots, peer_counts,
)
from judge.core.parse import parse_case  # noqa: E402

OPS = ("s", "disp", "gemm", "comb", "s_bwd",
       "comb_bwd", "gemm_dx", "gemm_dw", "disp_bwd", "s_dw")
COMP = {"s", "gemm", "s_bwd", "gemm_dx", "gemm_dw", "s_dw"}


def best_m(slots, P):
    """LPT 放置下的每 rank 最大 slot 数（§4.7.3：每 rank 恰好 E/P 个专家）。"""
    per = len(slots) // P
    order = sorted(range(len(slots)), key=lambda e: (-slots[e], e))
    load = [0] * P
    cnt = [0] * P
    for e in order:
        cand = [r for r in range(P) if cnt[r] < per]
        r = min(cand, key=lambda r: (load[r], r))
        load[r] += slots[e]
        cnt[r] += 1
    return max(load)


def layer_dur(case, P, V):
    pin, pout = peer_counts(case, V, P, 1)
    out = {}
    for l in range(case.L):
        x = comm_time(case, comm_payload(case, l, P), pin, pout)
        m = best_m(layer_slots(case, l), P)
        vals = layer_durations(case, l, m, x)
        out[l] = {op: vals[i] for i, op in enumerate(OPS)}
    return out


def build_ops(case, P):
    R = case.N * case.S
    V = R // P
    L = case.L
    per_layer = layer_dur(case, P, V)
    group_of_layer = [min(V - 1, l * V // L) for l in range(L)]
    ops, dur, deps = [], {}, {}
    for mb in range(case.nmb):
        for l in range(L):
            for op in OPS:
                key = (mb, l, op)
                ops.append(key)
                dur[key] = per_layer[l][op]
                ps = []
                if op == "s":
                    if l > 0:
                        ps.append((mb, l - 1, "comb"))
                elif op == "disp":
                    ps.append((mb, l, "s"))
                elif op == "gemm":
                    ps.append((mb, l, "disp"))
                elif op == "comb":
                    ps.append((mb, l, "gemm"))
                elif op == "s_bwd":
                    ps.append((mb, l, "comb"))
                    if l < L - 1:
                        ps.append((mb, l + 1, "disp_bwd"))
                elif op == "comb_bwd":
                    ps.append((mb, l, "s_bwd"))
                elif op == "gemm_dx":
                    ps.append((mb, l, "comb_bwd"))
                elif op == "disp_bwd":
                    ps.append((mb, l, "gemm_dx"))
                elif op in ("gemm_dw", "s_dw"):
                    ps.append((mb, l, "comb_bwd"))
                deps[key] = ps
    return ops, dur, deps, group_of_layer


def interleavings(chains):
    total = sum(len(c) for c in chains)
    pos = [0] * len(chains)
    cur, out = [], []

    def rec():
        if len(cur) == total:
            out.append(tuple(cur))
            return
        for i, chain in enumerate(chains):
            if pos[i] < len(chain):
                cur.append(chain[pos[i]])
                pos[i] += 1
                rec()
                pos[i] -= 1
                cur.pop()

    rec()
    return out


def makespan(ops, dur, deps, comm_orders):
    preds = {k: list(v) for k, v in deps.items()}
    for seq in comm_orders.values():
        for a, b in zip(seq, seq[1:]):
            preds[b].append(a)
    indeg = {k: len(ps) for k, ps in preds.items()}
    succ = {k: [] for k in ops}
    for k, ps in preds.items():
        for p in ps:
            succ[p].append(k)
    stack = [k for k in ops if indeg[k] == 0]
    topo = []
    while stack:
        k = stack.pop()
        topo.append(k)
        for n in succ[k]:
            indeg[n] -= 1
            if indeg[n] == 0:
                stack.append(n)
    if len(topo) != len(ops):
        return None
    start = {}
    for k in topo:
        start[k] = max((start[p] + dur[p] for p in preds[k]), default=0)
    return max(start[k] + dur[k] for k in ops)


def chains_for(layers, nmb):
    chains = []
    for mb in range(nmb):
        for l in layers:
            chains.append([(mb, l, "disp"), (mb, l, "comb")])
            chains.append([(mb, l, "comb_bwd"), (mb, l, "disp_bwd")])
    return chains


def check_grid(case, P, zero_compute):
    R = case.N * case.S
    V = R // P
    L = case.L
    if V > min(L, 64):
        return None
    ops, dur, deps, group_of_layer = build_ops(case, P)
    if zero_compute:
        for k in list(dur):
            if k[2] in COMP:
                dur[k] = 0
    nmb = case.nmb
    if V == 1:
        chains = []
        for mb in range(nmb):
            chain = [(mb, 0, "disp"), (mb, 0, "comb"), (mb, 1, "disp"), (mb, 1, "comb"),
                     (mb, 1, "comb_bwd"), (mb, 1, "disp_bwd"),
                     (mb, 0, "comb_bwd"), (mb, 0, "disp_bwd")]
            chains.append(chain)
        seqs = interleavings(chains)
        best = None
        for seq in seqs:
            mk = makespan(ops, dur, deps, {0: seq})
            if mk is not None and (best is None or mk < best):
                best = mk
        print(f"  P={P} V={V}: 枚举 {len(seqs):,} 种次序 -> 最优 {best}")
        return best

    per_group = []
    for g in range(V):
        layers = [l for l in range(L) if group_of_layer[l] == g]
        per_group.append(interleavings(chains_for(layers, nmb)))
    total = 0
    best = None
    first = per_group[0]
    sym = [s for s in first if s[0][0] == 0]
    for s0 in sym:
        for s1 in per_group[1]:
            total += 1
            mk = makespan(ops, dur, deps, {0: s0, 1: s1})
            if mk is not None and (best is None or mk < best):
                best = mk
    print(f"  P={P} V={V}: 枚举 {total:,} 种次序组合 -> 最优 {best}")
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", default="cases/ex3.in")
    ap.add_argument("--zero-compute", action="store_true")
    args = ap.parse_args()
    case = parse_case(args.case)
    R = case.N * case.S
    tag = "（计算时长归零）" if args.zero_compute else ""
    print(f"用例 {args.case}: R={R} L={case.L} E={case.E} nmb={case.nmb} M={case.M}{tag}")
    results = {}
    for P in (1, 2, 4):
        if R % P or case.E % P:
            continue
        if not (case.S % P == 0 or P % case.S == 0):
            continue
        mk = check_grid(case, P, args.zero_compute)
        if mk is not None:
            results[P] = mk
    if not results:
        print("没有可行网格")
        return 1
    best_P = min(results, key=results.get)
    print(f"\n全局最优 = {results[best_P]}（P={best_P}, V={R // best_P}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
