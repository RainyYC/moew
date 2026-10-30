"""按 t1 的解析式独立复算 13 个电池用例的填充下界 (nmb+V−1)·seg 与 fm 比值。

与 t1 `probe_fill_floor.py` 的**唯一**差别：seg 取**所有**卡组里最大的
`max(Σcomp, Σcomm)`（t1 只取第 0 层/第一个卡组代表）。
用法：PYTHONPATH=. python3 runs/score-validation-20261030/scripts/fill_analytic.py
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

from solver import formula, place  # noqa: E402
from solver.casein import parse_case  # noqa: E402
from solver import psi as psi_mod  # noqa: E402

CASES = ["b01-loose", "b02-m512", "b03-m256", "b04-m96", "b05-maxmb", "b06-maxmb-tight",
         "b07-mixed", "b08-narrow", "b09-small-e", "b10-high-k", "b11-short-l",
         "b12-compute-bound", "b13-balanced-compute"]
HIST = {  # 生产解实际网格（t1 verify_battery_data.json / t2 final-13）
    "b01-loose": (1, 64), "b02-m512": (2, 64), "b03-m256": (4, 64), "b04-m96": (8, 64),
    "b05-maxmb": (1, 64), "b06-maxmb-tight": (4, 64), "b07-mixed": (2, 64), "b08-narrow": (4, 64),
    "b09-small-e": (1, 64), "b10-high-k": (2, 64), "b12-compute-bound": (1, 64),
}
GRIDS = {"b13-balanced-compute": (64, 8), "b11-short-l": (4, 4)}


def group_seg(case, P, V, cuts):
    pin, pout = formula.peer_counts(case, 1, P)
    _, m = place.best_placement(case, P)
    bounds = [0] + list(cuts) + [case.L]
    best = 0
    for k in range(len(bounds) - 1):
        comp = comm = 0
        for layer in range(bounds[k], bounds[k + 1]):
            payload = formula.comm_payload(case, layer, P)
            d = formula.layer_durations(case, layer, m[layer], x)
            comp += sum(d[i] for i in formula.COMP_OPS)
            comm += sum(d[i] for i in formula.COMM_OPS)
        best = max(best, comp, comm)
    return best


def main() -> int:
    rows = []
    for name in CASES:
        case = parse_case(common.ROOT / f"bigcases/battery/{name}.in")
        if name in GRIDS:
            P, V = GRIDS[name]
        else:
            # 其余用例生产解都是 V=L、P 由枚举给出：从历史记录取实际网格
            P, V = HIST.get(name, (1, case.L))
        cuts = [round(case.L * k / V) for k in range(1, V)]  # 均匀切分
        seg = group_seg(case, P, V, cuts)
        bound = (case.nmb + V - 1) * seg
        rows.append({"case": name, "P": P, "V": V, "nmb": case.nmb, "seg": seg,
                     "bound": bound, "K_min_blocks": case.nmb + V - 1})
    out = common.OUTDIR / "battery" / "fill_analytic.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    print(json.dumps(rows, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
