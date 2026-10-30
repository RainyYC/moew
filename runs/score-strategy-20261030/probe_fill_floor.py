"""只读探针：为什么"填充型"用例停在 (nmb+V−1)/nmb，以及 b01/b12 的可达终点。

1. `fill_exact()`：对一组**理想化的逐层时长**（不考虑取整与偏斜），把 Time 解析成
   (流水线填充块数 × 块时长 + 尾段) 的形式，与 judge 的 Time 对比，说明 b02/b13 这类
   用例的时间**恰好等于** `nmb·(K−1)·seg + seg`，也就是"总共只有 nmb 个块可排"，
   填充不是调度器浪费，而是**作业数不足**。
2. `b01_bound()`：P=1、x=0 的纯计算用例，逐层计算量给定，求单卡组（L 层 + nmb 个
   mb）在一条计算引擎上的最短 makespan 下界（带丢弃权重梯度 `gemm_dw`/`s_dw` 的口径），
   用来判断"b01 现在离终点还有多远"。

命令：
    PYTHONPATH=. python3 runs/score-strategy-20261030/probe_fill_floor.py
"""
from __future__ import annotations

import json

from solver import formula, place
from solver.casein import parse_case

CASES = ["b02-m512", "b03-m256", "b04-m96", "b08-narrow", "b11-short-l", "b13-balanced-compute",
         "b10-high-k", "b07-mixed"]


def fill_exact(name, P, V):
    case = parse_case(f"bigcases/battery/{name}.in")
    pin, pout = formula.peer_counts(case, 1, P)
    _, m = place.best_placement(case, P)
    per_group = case.L // V
    # 取最重卡组（各层时长几乎相同，这里直接用该卡组第一层代表）
    comp = comm = 0
    for layer in range(per_group):
        x = formula.comm_time(case, formula.comm_payload(case, layer, P), pin, pout)
        d = formula.layer_durations(case, layer, m[layer], x)
        comp += sum(d[i] for i in formula.COMP_OPS)
        comm += sum(d[i] for i in formula.COMM_OPS)
    seg = max(comp, comm)
    # 每个 mb 在卡组上至少占 seg（两套引擎串行）；nmb 个 mb 串起来 + 1 次跨组传递
    K_min = case.nmb + V - 1
    return {
        "case": name, "P": P, "V": V, "layers_per_group": per_group,
        "comp_per_group": comp, "comm_per_group": comm, "seg": seg,
        "nmb": case.nmb,
        "analytic_min_blocks": K_min,
        "analytic_bound": K_min * seg,
        "old_serial_bound": case.nmb * seg * V,
    }


def b01_bound(name, P, drop_wg):
    case = parse_case(f"bigcases/battery/{name}.in")
    _, m = place.best_placement(case, P)
    # 每个 (mb, ℓ) 的计算工作量，分四类
    chain = wg = 0
    for layer in range(case.L):
        d = formula.layer_durations(case, layer, m[layer], 0)
        chain += d[0] + d[2] + d[4] + d[6]  # s, gemm, s_bwd, gemm_dx
        wg += d[7] + d[9]                     # gemm_dw, s_dw
    per_mb = chain
    total_compute = case.nmb * case.L * ((chain + (0 if drop_wg else wg)))
    # 单卡组（V=L，每卡组 1 层）上的总工作量
    per_group = case.nmb * ((chain + (0 if drop_wg else wg)))
    return {
        "case": name, "P": P, "drop_wg": drop_wg,
        "work_per_mb_all_layers": per_mb + (0 if drop_wg else wg),
        "work_per_group": per_group,
        "max_end_per_group": case.L * case.nmb * (per_mb // case.L + (0 if drop_wg else wg // case.L)),
        "note": "V=L 时每卡组只管 1 层，Time ≥ nmb×(该层计算工作量)；调度还须串行 nmb 个 mb",
    }


def main():
    out = {"fill": [], "b01": []}
    for name, P, V in [("b02-m512", 2, 64), ("b03-m256", 4, 64), ("b04-m96", 8, 64),
                       ("b08-narrow", 4, 64), ("b11-short-l", 4, 4), ("b13-balanced-compute", 64, 8),
                       ("b10-high-k", 4, 64), ("b07-mixed", 2, 64)]:
        out["fill"].append(fill_exact(name, P, V))
    for name in ("b01-loose", "b12-compute-bound"):
        case = parse_case(f"bigcases/battery/{name}.in")
        for P, drop in [(1, False), (1, True)]:
            if P not in [p for p in range(1, min(case.E, case.R) + 1)]:
                continue
            out["b01"].append(b01_bound(name, P, drop))
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
