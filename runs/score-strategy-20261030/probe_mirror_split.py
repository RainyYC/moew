"""只读探针：分块切层（K=2V 镜像 DualPipe 网格）对 Time/lb 的潜在收益。

动机（题面 §3.1 / §7）：`K=2V` 时每个卡组持两块（一块靠前、一块靠后），
两块的**层可以不同**。真实学习器里前向铺得宽、反向耗时是前向的 α(1+β) 倍，
计算负载天然不对称，于是"前块少放 2 层、后块多放 2 层"可能让卡组的
`max(ΣC, ΣWc)` 下降（要求 `2V ≤ L` 且每卡 Mexp 不超）。

题面 §4.6 的 Mexp 按卡组持有层数计，所以 K=2V 时每卡组层数与 K=V 完全一样，
**没有内存代价**；调度上只是把层的"阶段归属"改了一下。

本脚本只做**静态模型核算**（不做调度）：对每个 (P, 对子数 n=V) 用 DP 求
"把层序切成 2n 个连续块、对子 (i, 2n-1-i) 的层集合"下最小的
max_i max(ΣC, ΣWc)，比较 K=V 与 K=2V 两种数字。

命令：
    PYTHONPATH=. python3 runs/score-strategy-20261030/probe_mirror_split.py \
        > runs/score-strategy-20261030/probe_mirror_split.json
"""
from __future__ import annotations

import glob
import json
import re
import sys

from solver import formula, place
from solver.casein import Case, parse_case

ALPHA = re.compile(r"^(\d+)\s")


def p_candidates(case):
    out = []
    for P in range(1, min(case.E, case.R) + 1):
        if case.E % P or case.R % P:
            continue
        if not (case.S % P == 0 or P % case.S == 0):
            continue
        out.append(P)
    return out


def layer_weights(case, P):
    pin, pout = formula.peer_counts(case, 1, P)
    _, m = place.best_placement(case, P)
    comp, comm = [], []
    for layer in range(case.L):
        x = formula.comm_time(case, formula.comm_payload(case, layer, P), pin, pout)
        d = formula.layer_durations(case, layer, m[layer], x)
        comp.append(sum(d[i] for i in formula.COMP_OPS))
        comm.append(sum(d[i] for i in formula.COMM_OPS))
    return m, comp, comm


def split_max(weights, V):
    """连续切 V 段，最小化 max_v seg_v（一维标准 DP）。"""
    L = len(weights)
    pre = [0] * (L + 1)
    for i in range(L):
        pre[i + 1] = pre[i] + weights[i]
    INF = float("inf")
    dp = [[INF] * (L + 1) for _ in range(V + 1)]
    dp[0][0] = 0
    for v in range(1, V + 1):
        for end in range(1, L + 1):
            best = INF
            for start in range(v - 1, end):
                cand = max(dp[v - 1][start], pre[end] - pre[start])
                if cand < best:
                    best = cand
            dp[v][end] = best
    return dp[V][L]


def dual_weights(comp, comm, comp_rev, comm_rev):
    """K=2V 的卡组负载：卡组 i 拿前向块 i 与后向块 2n-1-i（层按序），
    计算/反向通信按 α(1+β) 放大后一起算进两套引擎。"""
    raise NotImplementedError


def analyse(case, label):
    out = {"case": label, "L": case.L, "E": case.E, "nmb": case.nmb,
           "beta_x": case.beta_x, "alpha_x": case.alpha_x, "rows": []}
    for P in p_candidates(case):
        m, comp, comm = layer_weights(case, P)
        pin, pout = formula.peer_counts(case, 1, P)
        # 计算 / 通信两套引擎的下界：对 K=V 用两维 DP；K=2V 时每个卡组的层集合是
        # {i, 2n-1-i}，两块的 Σ 相加（引擎互斥是对卡组的，两块共用引擎）
        vmax = min(case.L, 64, case.R // P)
        for V in sorted({vmax, vmax // 2}):
            if V < 1 or V > case.L or V * P > case.R:
                continue
            if case.L % V == 0:
                chunk = case.L // V
                cv = [sum(comp[i * chunk:(i + 1) * chunk]) for i in range(V)]
                wv = [sum(comm[i * chunk:(i + 1) * chunk]) for i in range(V)]
                kv_lb = max(max(a, b) for a, b in zip(cv, wv)) * case.nmb
            else:
                kv_lb = None
            # K=2V：V 个卡组、2V 块（连续、每块 ≥1 层），对子 (i, 2V-1-i) 合并
            k2v = case.L // (2 * V)
            k2v_lb = None
            if case.L % (2 * V) == 0 and 2 * V <= case.L:
                n = 2 * V
                chunk = case.L // n
                bc = [sum(comp[i * chunk:(i + 1) * chunk]) for i in range(n)]
                bw = [sum(comm[i * chunk:(i + 1) * chunk]) for i in range(n)]
                # 镜像配对：卡组 i -> 块 i 与 块 2V-1-i
                vals = [max(bc[i] + bc[n - 1 - i], bw[i] + bw[n - 1 - i]) for i in range(V)]
                k2v_lb = max(vals) * case.nmb
            out["rows"].append({
                "P": P, "V": V, "pin": pin, "pout": pout,
                "layers_per_group_KV": case.L // V if case.L % V == 0 else None,
                "layers_per_block_K2V": k2v,
                "lb_KV_equal_split": kv_lb,
                "lb_K2V_equal_split": k2v_lb,
                "ratio_K2V_over_KV": (k2v_lb / kv_lb) if (k2v_lb and kv_lb) else None,
            })
    return out


def main():
    paths = sorted(glob.glob("bigcases/battery/*.in")) + [f"cases/ex{i}.in" for i in range(1, 7)]
    res = []
    for path in paths:
        case = parse_case(path)
        res.append(analyse(case, path.rsplit("/", 1)[-1].replace(".in", "")))
        sys.stderr.write(f"done {path}\n")
    json.dump(res, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
