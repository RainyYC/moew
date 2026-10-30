"""只读：对 battery 13 例 + 官方 6 例，按题面 §4.3/§4.4 精确计算每个可达 P 的
(实际最优 m_l、X_l、x_l、s_l、gemm_l)，再用 DP 求"连续切 V 段"的最小
max_v max(ΣC_v, ΣWc_v)，得到 **模型层** 下界（不含填充与调度损失）。

它回答的是"网格 (P,V,ψ) 决策还能改变多少分"，而不是当前调度器的质量。

命令：
    PYTHONPATH=. python3 runs/score-strategy-20261030/model_margins.py \
        > runs/score-strategy-20261030/model_margins.json
"""
from __future__ import annotations

import glob
import json
import sys

from solver import formula, place
from solver.casein import parse_case


def p_candidates(case):
    out = []
    for P in range(1, min(case.E, case.R) + 1):
        if case.E % P or case.R % P:
            continue
        if not (case.S % P == 0 or P % case.S == 0):
            continue
        out.append(P)
    return out


def split_min_max(case, comp, comm, V):
    """连续切 V 段，最小化 max_v max(ΣC_v, ΣWc_v)（精确 DP，L,V ≤ 64）。"""
    L = case.L
    pc = [0] * (L + 1)
    pw = [0] * (L + 1)
    for i in range(L):
        pc[i + 1] = pc[i] + comp[i]
        pw[i + 1] = pw[i] + comm[i]
    INF = float("inf")
    dp = [[INF] * (L + 1) for _ in range(V + 1)]
    dp[0][0] = 0
    for v in range(1, V + 1):
        for end in range(1, L + 1):
            for start in range(v - 1, end):
                seg = max(pc[end] - pc[start], pw[end] - pw[start])
                cand = max(dp[v - 1][start], seg)
                if cand < dp[v][end]:
                    dp[v][end] = cand
    return dp[V][L]


def analyse(case, label):
    rows = []
    for P in p_candidates(case):
        pin, pout = formula.peer_counts(case, 1, P)
        rows_p, m_p = place.best_placement(case, P)
        xs = [formula.comm_time(case, formula.comm_payload(case, l, P), pin, pout) for l in range(case.L)]
        comp, comm = [], []
        for l in range(case.L):
            d = formula.layer_durations(case, l, m_p[l], xs[l])
            comp.append(sum(d[i] for i in formula.COMP_OPS))
            comm.append(sum(d[i] for i in formula.COMM_OPS))
        vmax = min(case.L, 64, case.R // P)
        vset = {vmax, vmax // 2, vmax // 4}
        for V in sorted(v for v in vset if 1 <= v <= case.L and v * P <= case.R):
            seg = split_min_max(case, comp, comm, V)
            rows.append({
                "P": P,
                "V": V,
                "pin": pin,
                "pout": pout,
                "s": case.T[0] * case.Fs,
                "x": xs[0],
                "gemm_max": max(m_p) * case.Fin,
                "m_place_max": max(m_p),
                "m_uniform_ceil": (case.T[0] + P - 1) // P,
                "load_slack": max(m_p) - (case.T[0] + P - 1) // P,
                "model_lb": case.nmb * seg,
                "model_lb_x_fill": case.nmb * seg * (1 + (V - 1) / case.nmb),
            })
    rows.sort(key=lambda r: r["model_lb_x_fill"])
    return {
        "case": label,
        "N": case.N, "S": case.S, "R": case.R, "L": case.L, "E": case.E, "nmb": case.nmb,
        "Fs": case.Fs, "Fio": case.Fio, "Fin": case.Fin,
        "alpha_x": case.alpha_x, "beta_x": case.beta_x, "U": case.U, "Uact": case.Uact,
        "M": case.M, "T_min": min(case.T), "T_max": max(case.T),
        "skewed_layers": sum(1 for x in case.loads if x is not None),
        "rows": rows[:12],
    }


def main():
    paths = sorted(glob.glob("bigcases/battery/*.in")) + [f"cases/ex{i}.in" for i in range(1, 7)]
    out = []
    for path in paths:
        case = parse_case(path)
        out.append(analyse(case, path.rsplit("/", 1)[-1].replace(".in", "")))
        sys.stderr.write(f"done {path}\n")
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
