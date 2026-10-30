#!/usr/bin/env python3
"""给定已选定的 (V,P,D) / PSI / MAP，用 CP-SAT 求**最优调度**。

用途：判断"我们退火得到的 Time 是否已是最优"。地图（网格/切点/放置）保持不变，
只优化调度，因此这是一个纯粹的 job-shop 问题，CP-SAT 可以在秒级给出**最优性证明**。

模型（与题面 §4.2 逐条对应）：
  * 每个操作一个 start 变量，时长由 judge.core.model 给出（单一出处，避免两套公式）；
  * 层内依赖（2026-10-29 修订）：disp→gemm→comb；s_bwd 只等本层 comb；
    comb_bwd 等本层 comb；gemm_dx→disp_bwd；gemm_dw 等 comb_bwd；s_dw 等 s_bwd；
    共享专家前向 s 与 disp 之间不再有依赖；
  * 层序依赖 s(mb,ℓ) ≥ comb(mb,ℓ-1)；s_bwd(mb,ℓ) ≥ disp_bwd(mb,ℓ+1)；
  * 每个卡组一套计算引擎 + 一套通信引擎，各用 NoOverlap 保证互斥；
  * **时长 0 的操作不建区间变量**（题面：不占用引擎）；
  * 目标：最小化 makespan。

内存（§4.6）**不**建成约束：Movl/Mact 依赖"同时进行的操作数"峰值，不是纯调度约束。
求解后交给 `python3 -m judge eval` 复核——判题器会查内存，也查全部依赖。

用法：
    python3 tools/cpsat_opt.py cases/ex2.in out/ex2.out [--time-limit 120] [-o opt/ex2.out]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from judge.core.model import (  # noqa: E402
    OP_NAMES,
    comm_payload,
    comm_time,
    layer_durations,
    layer_m,
    peer_counts,
)
from judge.core.parse import parse_case, parse_output  # noqa: E402

COMP_OPS = frozenset({"s", "gemm", "s_bwd", "gemm_dx", "gemm_dw", "s_dw"})
COMM_OPS = frozenset({"disp", "comb", "comb_bwd", "disp_bwd"})


def group_of(layer: int, V: int, psi: list[int], L: int) -> int:
    """层 → 卡组（题面 §3.1：块 k 属于卡组 k（k<V）或 2V-1-k）。"""
    bounds = [0] + list(psi) + [L]
    K = len(bounds) - 1
    for k in range(K):
        if bounds[k] <= layer < bounds[k + 1]:
            return k if k < V else 2 * V - 1 - k
    raise ValueError(f"层 {layer} 不属于任何块")


def build_durations(case, out):
    """每个 (layer, op) 的时长；返回 {(l, op): dur}。"""
    pin, pout = peer_counts(case, V=out.V, P=out.P)
    table = {}
    for layer in range(case.L):
        m = layer_m(case, layer, out.P, out.map_rows[layer])
        x = comm_time(case, comm_payload(case, layer, out.P), pin, pout)
        values = layer_durations(case, layer, m, x)
        for idx, name in enumerate(OP_NAMES):
            table[(layer, name)] = values[idx]
    return table


def deps_of(mb: int, layer: int, name: str, L: int) -> list[tuple[int, int, str]]:
    """§4.2 第 1、2 条（2026-10-29 修订版）：返回 [(mb, layer, op), ...]。

    修订点：共享专家与同层其余操作解耦 —— ``disp`` 不再等 ``s``；``comb_bwd`` 改为等
    本层 ``comb``（不再等 ``s_bwd``）；``s_dw`` 改为等 ``s_bwd``。
    """
    if name == "s":
        return [(mb, layer - 1, "comb")] if layer >= 1 else []
    if name == "disp":
        return [(mb, layer - 1, "comb")] if layer >= 1 else []
    if name == "gemm":
        return [(mb, layer, "disp")]
    if name == "comb":
        return [(mb, layer, "gemm"), (mb, layer, "s")]  # 共享专家前向须在 comb 之前收尾
    if name == "s_bwd":
        out = [(mb, layer, "s"), (mb, layer, "comb")]
        if layer + 1 <= L - 1:
            out.append((mb, layer + 1, "disp_bwd"))
        return out
    if name == "comb_bwd":
        out = [(mb, layer, "comb")]
        if layer + 1 <= L - 1:
            out.append((mb, layer + 1, "disp_bwd"))
        return out
    if name == "gemm_dx":
        return [(mb, layer, "comb_bwd")]
    if name == "disp_bwd":
        return [(mb, layer, "gemm_dx"), (mb, layer, "s_bwd")]
    if name in ("gemm_dw", "s_dw"):
        return [(mb, layer, "comb_bwd")]
    raise ValueError(name)


def solve(case, out, time_limit: float, workers: int):
    from ortools.sat.python import cp_model

    durations = build_durations(case, out)
    nmb, L, V = case.nmb, case.L, out.V
    model = cp_model.CpModel()

    starts: dict[tuple[int, int, str], object] = {}
    inter: dict[tuple[int, int, str], object] = {}
    horizon = sum(sum(durations.values()) for _ in range(nmb)) + 1

    for mb in range(nmb):
        for layer in range(L):
            for name in OP_NAMES:
                key = (mb, layer, name)
                dur = durations[(layer, name)]
                starts[key] = model.NewIntVar(0, horizon, f"t_{mb}_{layer}_{name}")
                if dur > 0:
                    inter[key] = model.NewIntervalVar(
                        starts[key], dur, model.NewIntVar(0, horizon, f"e_{mb}_{layer}_{name}"),
                        f"i_{mb}_{layer}_{name}",
                    )

    # 依赖：start[后] >= start[前] + dur[前]
    for mb in range(nmb):
        for layer in range(L):
            for name in OP_NAMES:
                for dep in deps_of(mb, layer, name, L):
                    if dep not in starts:
                        continue
                    model.Add(
                        starts[(mb, layer, name)]
                        >= starts[dep] + durations[(dep[1], dep[2])]
                    )

    # 每卡组 × 每引擎：NoOverlap
    buckets: dict[tuple[int, str], list] = {}
    for key, iv in inter.items():
        mb, layer, name = key
        g = group_of(layer, V, list(out.psi), L)
        engine = "comp" if name in COMP_OPS else "comm"
        buckets.setdefault((g, engine), []).append(iv)
    for ivs in buckets.values():
        if len(ivs) > 1:
            model.AddNoOverlap(ivs)

    makespan = model.NewIntVar(0, horizon, "makespan")
    for key, var in starts.items():
        model.Add(makespan >= var + durations[(key[1], key[2])])
    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = workers
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, solver.StatusName(status), durations

    schedule = []
    for key, var in starts.items():
        schedule.append((solver.Value(var), key))
    schedule.sort()
    return schedule, solver.StatusName(status), durations


def render(out, schedule, durations) -> str:
    # 2026-10 版题面取消了 D：网格只有 (V,P)
    lines = [f"{out.V} {out.P}", "PSI", " ".join(str(v) for v in [out.K] + list(out.psi))]
    lines.append("MAP")
    for row in out.map_rows:
        lines.append(" ".join(str(v) for v in row))
    lines.append("SCHEDULE")
    by_t: dict[int, list[str]] = {}
    for t, (mb, layer, name) in schedule:
        by_t.setdefault(t, []).append(f"{mb}:{layer}:{name}")
    for t in sorted(by_t):
        lines.append(f"{t} " + " ".join(by_t[t]))
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("case_in")
    ap.add_argument("case_out", help="含 V/P/D/PSI/MAP 的现有输出（只取决策，不用其调度）")
    ap.add_argument("--time-limit", type=float, default=120.0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("-o", "--out", default="")
    args = ap.parse_args()

    case = parse_case(args.case_in)
    out = parse_output(Path(args.case_out).read_text(encoding="utf-8"))
    schedule, status, durations = solve(case, out, args.time_limit, args.workers)
    if schedule is None:
        print(f"CP-SAT 未找到解：{status}", file=sys.stderr)
        return 1

    text = render(out, schedule, durations)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"写入 {args.out}")
    else:
        sys.stdout.write(text)

    makespan = max(t + durations[(layer, name)] for t, (mb, layer, name) in schedule)
    print(f"[cpsat] 状态={status} 最优-ish makespan={makespan}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
