"""只读探针：网格候选不应被"V 取最大"锁死 —— 对每个 (P, V) 组合估 lb，找相对当前解的潜力。

背景：`solve.enumerate_configs` 对每个 P 只取 `V = min(L, 64, R//P)`，排序键是
`lb × (nmb+V−1)/nmb`，而 `_try_config` 有很大概率在第一个 / 前几个配置上就用完预算
（}`_improve_best` 之后不复用剩余时间）。于是"V 更大的配置 lb 更小"这条假设一旦
不成立（负载偏斜、E/P 小、内存紧），就会漏掉真正好的网格。

本脚本对每个 case 的每个 (P, V) 组合，用 solve 自己的 psi 候选 + formula.lower_bound
算 lb 与填充估计，并与**当前生产解**（runs/val-t1-battery-.../judge 里的 time）对比，
报出"估计下界 × 填充 < 当前 Time"的组合。

命令：
    PYTHONPATH=. python3 runs/score-strategy-20261030/probe_grid_sweep.py \
        > runs/score-strategy-20261030/probe_grid_sweep.json
"""
from __future__ import annotations

import glob
import json
import sys

from solver import formula, psi as psi_mod
from solver.casein import parse_case
from solver.solve import _pmap, p_candidates

#: 当前生产解的 judge Time（来自 runs/val-t1-battery-20261029-2308/judge/current-*.json）。
CURRENT = {
    "b01-loose": 5_904_000_000_000,
    "b02-m512": 542_157_603_132_750,
    "b03-m256": 811_784_777_827_320,
    "b04-m96": 946_917_900_211_470,
    "b05-maxmb": 49_008_000_000_000,
    "b06-maxmb-tight": 5_229_861_932_305_704,
    "b07-mixed": 3_492_805_460_668_064,
    "b08-narrow": 1_569_450_570_466_152,
    "b09-small-e": 49_008_000_000_000,
    "b10-high-k": 179_346_953_034_600,
    "b11-short-l": 4_934_667_467_641_224,
    "b12-compute-bound": 83_843_497_367_000_000,
    "b13-balanced-compute": 46_326_548_000_000_000,
}


def analyse(path):
    case = parse_case(path)
    name = path.rsplit("/", 1)[-1].replace(".in", "")
    cur = CURRENT.get(name)
    rows = []
    for P in p_candidates(case):
        info = _pmap(case, P)
        comp_w = [sum(row[i] for i in formula.COMP_OPS) for row in info.durations]
        comm_w = [sum(row[i] for i in formula.COMM_OPS) for row in info.durations]
        per_layer = (case.E // P) * case.Z + case.Zs
        vmax = min(case.L, 64, case.R // P)
        vset = sorted({vmax, max(1, vmax // 2), max(1, vmax // 4), 1})
        for V in vset:
            if V > case.L or V * P > case.R:
                continue
            if case.L % V:
                continue  # 只评估能均分层的 V（psi 候选里也有非均分，这里取乐观估计）
            best_lb = None
            for cuts in psi_mod.psi_candidates(case.L, V, comp_w, comm_w):
                psi_full = (0,) + cuts + (case.L,)
                layers = formula.group_layers(V, psi_full)
                if any(len(g) * per_layer > case.M for g in layers):
                    continue
                lb = formula.lower_bound(case, info.durations, layers)
                if best_lb is None or lb < best_lb:
                    best_lb = lb
            if best_lb is None:
                continue
            fill = case.nmb + V - 1
            rows.append({
                "P": P, "V": V, "lb": best_lb,
                "lb_x_fill": best_lb * fill // case.nmb,
                "ratio_vs_current_lb": (best_lb / cur) if cur else None,
                "ratio_vs_current_fill": (best_lb * fill / case.nmb / cur) if cur else None,
                "is_default_V": V == vmax,
                "Mexp": (case.L // V) * per_layer,
                "M": case.M,
                "Mexp_ok": (case.L // V) * per_layer <= case.M,
            })
    rows.sort(key=lambda r: r["lb_x_fill"])
    return {"case": name, "current_time": cur,
            "current_PV": None,
            "best": rows[0] if rows else None,
            "best_nondefault": next((r for r in rows if not r["is_default_V"]), None),
            "rows": rows[:20]}


def main():
    paths = sorted(glob.glob("bigcases/battery/*.in")) + [f"cases/ex{i}.in" for i in range(1, 7)]
    res = []
    for path in paths:
        res.append(analyse(path))
        sys.stderr.write(f"done {path}\n")
    json.dump(res, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
