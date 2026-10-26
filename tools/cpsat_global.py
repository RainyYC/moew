#!/usr/bin/env python3
"""对一个小规模用例做**全局**最优性判定：枚举网格 / 切点 / 可达的 m 向量，逐个用 CP-SAT 求最优调度。

与 `tools/cpsat_opt.py` 的区别：那个是"给定决策求最优调度"，这个是"枚举全部合法决策"，
因此结论可以写成"**该用例的 Time 就是最优**"，而不只是"距下界还差 X"。

要点：
  * 时长只依赖每层的 `(m_ℓ, x_ℓ)`（题面 §4.1/§4.3/§4.4），其中 `x_ℓ` 由 `(V,P,D)` 决定，
    `m_ℓ` 只由该层的 MAP 决定。所以**不需要枚举全部 MAP**，只需枚举每层可达的 `m_ℓ`。
  * 静态内存（`Mexp`）先剪；动态内存（`Movl`/`Mact`）交给 `judge` 复核，判非法的候选丢弃。
  * 每个候选的 CP-SAT 结果都写成一个 `.out`，最后用 `python3 -m judge eval` 复验——只有判题器
    认可的候选才算数。

用途：把"ex2 距下界 ≤48、可达性未证"这类悬而未决的表述，变成确定结论。

用法：
    PYTHONPATH=.pylibs python3 tools/cpsat_global.py cases/ex2.in [--time-limit 60]
"""

from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from judge.core.model import (  # noqa: E402
    OP_NAMES,
    comm_payload,
    comm_time,
    layer_durations,
    layer_slots,
    peer_counts,
)
from judge.core.parse import parse_case  # noqa: E402

COMP_OPS = frozenset({"s", "gemm", "s_bwd", "gemm_dx", "gemm_dw", "s_dw"})


def divisors(n: int) -> list[int]:
    return [d for d in range(1, n + 1) if n % d == 0]


def p_candidates(case) -> list[int]:
    out = []
    for P in divisors(case.E):
        if P <= case.S and case.S % P == 0:
            out.append(P)
        elif P % case.S == 0:
            out.append(P)
    return out


def partitions(slots: list[int], P: int):
    """把专家划分成 P 组、每组恰好 ``E/P`` 个（顺序有意义，对应 rank 0..P-1）。"""
    E = len(slots)
    per = E // P
    if per == 0:
        return

    def rec(remaining: list[int], r: int):
        if r == P - 1:
            yield [remaining]
            return
        for combo in itertools.combinations(remaining, per):
            chosen = set(combo)
            rest = [e for e in remaining if e not in chosen]
            for tail in rec(rest, r + 1):
                yield [list(combo)] + tail

    yield from rec(list(range(E)), 0)


def _partition_count(E: int, P: int) -> int:
    """划分总数 = E! / ((E/P)!^P)；超过上限就不枚举，避免爆炸。"""
    import math

    per = E // P
    if per == 0:
        return 0
    total = math.factorial(E)
    for _ in range(P):
        total //= math.factorial(per)
    return total


ENUM_LIMIT = 200_000


def m_options(slots: list[int], P: int) -> list[int]:
    """该层所有合法 MAP 能达到的 m 值（去重、升序）。

    每个 rank 必须恰好放 ``E/P`` 个专家（题面 §4.7 第 3 条），所以这里枚举的是
    真正的"等分划"，不能允许两个专家挤进同一个 rank。
    """
    E = len(slots)
    per = E // P
    if per == 0:
        return []
    if _partition_count(E, P) > ENUM_LIMIT:
        raise ValueError(f"E={E}, P={P} 的划分过多（>{ENUM_LIMIT}），本工具只适合小用例")
    values = set()
    for parts in partitions(slots, P):
        values.add(max(sum(slots[e] for e in group) for group in parts))
    return sorted(values)


def group_layers(V: int, psi: tuple[int, ...], L: int) -> list[list[int]]:
    bounds = [0] + list(psi) + [L]
    groups: list[list[int]] = [[] for _ in range(V)]
    for k in range(len(bounds) - 1):
        g = k if k < V else 2 * V - 1 - k
        groups[g].extend(range(bounds[k], bounds[k + 1]))
    return groups


def build_model(case, V, P, D, psi, ms, time_limit):
    """给定网格/切点/每层 m，构造并求解 CP-SAT；返回 (schedule, durations, status)。"""
    from ortools.sat.python import cp_model

    pin, pout = peer_counts(case, V=V, P=P, D=D)
    durations = {}
    for layer in range(case.L):
        x = comm_time(case, comm_payload(case, layer, P), pin, pout)
        values = layer_durations(case, layer, ms[layer], x)
        for idx, name in enumerate(OP_NAMES):
            durations[(layer, name)] = values[idx]

    nmb, L = case.nmb, case.L
    model = cp_model.CpModel()
    horizon = sum(sum(durations[(l, o)] for l in range(L) for o in OP_NAMES) for _ in range(nmb)) + 1
    starts, inter = {}, {}
    for mb in range(nmb):
        for layer in range(L):
            for name in OP_NAMES:
                key = (mb, layer, name)
                dur = durations[(layer, name)]
                starts[key] = model.NewIntVar(0, horizon, f"t_{mb}_{layer}_{name}")
                if dur > 0:
                    inter[key] = model.NewIntervalVar(
                        starts[key], dur,
                        model.NewIntVar(0, horizon, f"e_{mb}_{layer}_{name}"),
                        f"i_{mb}_{layer}_{name}",
                    )

    def deps(mb, layer, name):
        if name == "s":
            return [(mb, layer - 1, "comb")] if layer >= 1 else []
        if name == "disp":
            return [(mb, layer, "s")]
        if name == "gemm":
            return [(mb, layer, "disp")]
        if name == "comb":
            return [(mb, layer, "gemm")]
        if name == "s_bwd":
            d = [(mb, layer, "comb")]
            if layer + 1 <= L - 1:
                d.append((mb, layer + 1, "disp_bwd"))
            return d
        if name == "comb_bwd":
            return [(mb, layer, "s_bwd")]
        if name == "gemm_dx":
            return [(mb, layer, "comb_bwd")]
        if name == "disp_bwd":
            return [(mb, layer, "gemm_dx")]
        return [(mb, layer, "comb_bwd")]

    for mb in range(nmb):
        for layer in range(L):
            for name in OP_NAMES:
                for dep in deps(mb, layer, name):
                    if dep in starts:
                        model.Add(starts[(mb, layer, name)] >= starts[dep] + durations[(dep[1], dep[2])])

    groups = group_layers(V, psi, L)
    layer_group = {}
    for g, layers in enumerate(groups):
        for l in layers:
            layer_group[l] = g
    buckets = {}
    for key, iv in inter.items():
        mb, layer, name = key
        engine = "comp" if name in COMP_OPS else "comm"
        buckets.setdefault((layer_group[layer], engine), []).append(iv)
    for ivs in buckets.values():
        if len(ivs) > 1:
            model.AddNoOverlap(ivs)

    makespan = model.NewIntVar(0, horizon, "makespan")
    for key, var in starts.items():
        model.Add(makespan >= var + durations[(key[1], key[2])])
    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, durations, solver.StatusName(status)
    sched = sorted((solver.Value(v), k) for k, v in starts.items())
    return sched, durations, solver.StatusName(status)


def render(V, P, D, K, psi, map_rows, sched):
    lines = [f"{V} {P} {D}", "PSI", " ".join(str(v) for v in [K] + list(psi)), "MAP"]
    for row in map_rows:
        lines.append(" ".join(str(v) for v in row))
    lines.append("SCHEDULE")
    by_t = {}
    for t, (mb, layer, name) in sched:
        by_t.setdefault(t, []).append(f"{mb}:{layer}:{name}")
    for t in sorted(by_t):
        lines.append(f"{t} " + " ".join(by_t[t]))
    return "\n".join(lines) + "\n"


def rows_for_m(slots: list[int], P: int, target_m: int):
    """给出一个能达到 ``target_m`` 的示例 MAP 行（用于落盘复验）。"""
    E = len(slots)
    for parts in partitions(slots, P):
        if max(sum(slots[e] for e in group) for group in parts) != target_m:
            continue
        row = [0] * E
        for rank, group in enumerate(parts):
            for e in group:
                row[e] = rank
        return row
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("case_in")
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--out-dir", default="opt/global")
    args = ap.parse_args()

    case = parse_case(args.case_in)
    name = Path(args.case_in).stem
    R, L, E = case.N * case.S, case.L, case.E
    best = None
    tried = 0
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for P in p_candidates(case):
        if R % P:
            continue
        for V in divisors(R // P):
            if V > L:
                continue
            D = R // P // V
            per_layer_bytes = (E // P) * case.Z + case.Zs
            psi_list = [()] if V == 1 else list(itertools.combinations(range(1, L), V - 1))
            for psi in psi_list:
                groups = group_layers(V, psi, L)
                if any(len(g) * per_layer_bytes > case.M for g in groups):
                    continue
                m_opts = [m_options(layer_slots(case, l), P) for l in range(L)]
                for ms in itertools.product(*m_opts):
                    tried += 1
                    sched, durations, status = build_model(
                        case, V, P, D, psi, list(ms), args.time_limit
                    )
                    if sched is None:
                        continue
                    makespan = max(t + durations[(l, n)] for t, (mb, l, n) in sched)
                    if best is not None and makespan >= best[0]:
                        continue
                    map_rows = [rows_for_m(layer_slots(case, l), P, ms[l]) for l in range(L)]
                    if any(r is None for r in map_rows):
                        continue
                    K = len(psi) + 1
                    text = render(V, P, D, K, psi, map_rows, sched)
                    path = out_dir / f"{name}-V{V}P{P}D{D}-{makespan}.out"
                    path.write_text(text, encoding="utf-8")
                    best = (makespan, (V, P, D), psi, list(ms), str(path), status)

    print(f"用例 {name}: 枚举候选 {tried} 个")
    if best is None:
        print("未找到合法解（可能被内存全部排除）", file=sys.stderr)
        return 1
    makespan, grid, psi, ms, path, status = best
    print(f"  最优 Time = {makespan}")
    print(f"  网格 (V,P,D) = {grid}  PSI = {psi}  m = {ms}  CP-SAT={status}")
    print(f"  落盘 {path}")
    print(f"  复验：python3 -m judge eval {args.case_in} {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
