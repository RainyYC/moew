"""逐卡组 seg 校验"choppy 空隙"假设：对每个卡组算两套引擎的 Σcomp、Σcomm，看
 |Σcomp−Σcomm| 的异质性（只读，不调度）。

对 t1 的 old_serial_bound（每层 ≤20% 差）与真实 per-group seg 对照：
  extra_fill = (nmb+V−1)·(Σ_seg_g / V) / ((nmb+V−1)·max_g seg_g) − 1
即在"每卡组独立填满自己的引擎"前提下，比"所有卡组都等于最慢 seg"多出的比例。
用法：PYTHONPATH=. python3 runs/score-validation-20261030/scripts/choppy_vs_prod.py
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
from solver import formula, place  # noqa: E402
from solver.casein import parse_case  # noqa: E402

CASES = {"b02-m512": (2, 64), "b03-m256": (4, 64), "b04-m96": (8, 64), "b07-mixed": (2, 64),
         "b08-narrow": (4, 64), "b10-high-k": (2, 64), "b11-short-l": (4, 4),
         "b13-balanced-compute": (64, 8), "b06-maxmb-tight": (4, 64)}


def main() -> int:
    prods = {r["case"]: r["time"] for r in json.loads((common.OUTDIR / "battery/b13b12/result.json").read_text())["rows"]
             if r["variant"] == "cur"} if False else {}
    out = {}
    for name, (P, V) in CASES.items():
        case = parse_case(common.ROOT / f"bigcases/battery/{name}.in")
        pin, pout = formula.peer_counts(case, 1, P)
        _, m = place.best_placement(case, P)
        per = case.L // V
        segs = []
        for g in range(V):
            comp = comm = 0
            for layer in range(g * per, (g + 1) * per):
                x = formula.comm_time(case, formula.comm_payload(case, layer, P), pin, pout)
                d = formula.layer_durations(case, layer, m[layer], x)
                comp += sum(d[i] for i in formula.COMP_OPS)
                comm += sum(d[i] for i in formula.COMM_OPS)
            segs.append({"comp": comp, "comm": comm, "seg": max(comp, comm)})
        segmax = max(s["seg"] for s in segs)
        segmean = sum(s["seg"] for s in segs) / V
        out[name] = {"P": P, "V": V, "nmb": case.nmb,
                     "comp_span_pct": 100 * (max(s["comp"] for s in segs) / min(s["comp"] for s in segs) - 1),
                     "comm_span_pct": 100 * (max(s["comm"] for s in segs) / min(s["comm"] for s in segs) - 1),
                     "seg_span_pct": 100 * (segmax / min(s["seg"] for s in segs) - 1),
                     "seg_mean_over_max": round(segmean / segmax, 6),
                     "bound_mean": int((case.nmb + V - 1) * segmean),
                     "bound_max": int((case.nmb + V - 1) * segmax)}
        print(name, json.dumps(out[name], ensure_ascii=False), flush=True)
    (common.OUTDIR / "battery/choppy_vs_prod.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
