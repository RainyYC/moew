"""读-only：b10 多 V 候选的静态评估（不调度，只看 lb×填充）。

b10 生产解 lb=1.5729e14 是按 V=64（每卡组 1 层）算的；V 变小时 `lower_bound` 变成
nmb·max(ΣC_v, ΣWc_v)，跨层累加 ⇒ lb 会上升。本脚本对 V ∈ {64,32,16,8} × P ∈ {4,8}
逐个算 lb 与 lb×填充，判断"多 V 候选"在 b10 上是否有静态空间。
用法：PYTHONPATH=. python3 runs/score-validation-20261030/scripts/b10_multiV.py
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
sys.path.insert(0, str(common.OUTDIR / "snapshot"))
from solver import formula, solve, psi as psi_mod  # noqa: E402
from solver.casein import parse_case  # noqa: E402

def main() -> int:
    case = parse_case(common.ROOT / "bigcases/battery/b10-high-k.in")
    rows = []
    for P in (1, 2, 4, 8):
        info = solve._pmap(case, P)
        per_layer_bytes = (case.E // P) * case.Z + case.Zs
        comp_w = [sum(row[i] for i in formula.COMP_OPS) for row in info.durations]
        comm_w = [sum(row[i] for i in formula.COMM_OPS) for row in info.durations]
        for V in (64, 32, 16, 8, 4):
            best = None
            for cuts in psi_mod.psi_candidates(case.L, V, comp_w, comm_w):
                psi_full = (0,) + cuts + (case.L,)
                layers = formula.group_layers(V, psi_full)
                if any(len(g) * per_layer_bytes > case.M for g in layers):
                    continue
                lb = formula.lower_bound(case, info.durations, layers)
                fill = (case.nmb + V - 1) / case.nmb
                key = lb * max(1, case.nmb + V - 1) // case.nmb
                if best is None or key < best["lb_x_fill"]:
                    best = {"P": P, "V": V, "lb": lb, "fill": round(fill, 4), "lb_x_fill": key}
            if best:
                rows.append(best)
    rows.sort(key=lambda r: r["lb_x_fill"])
    for r in rows[:12]:
        print(json.dumps(r, ensure_ascii=False))
    (common.OUTDIR / "battery/b10-multiv.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    print("prod T = 179346953034600 ; best static lb*fill =", rows[0]["lb_x_fill"],
          "ratio T/static =", round(179346953034600 / rows[0]["lb_x_fill"], 4))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
