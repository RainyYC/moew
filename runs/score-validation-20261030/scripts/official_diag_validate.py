"""独立复算官方 50 例诊断量（ratio_lb / 填充地板 / excess），核对 t2 的 official50-diag.json。

填充地板 = (nmb+V−1)/nmb；excess = ratio_lb / 填充地板。
用法：PYTHONPATH=. python3 runs/score-validation-20261030/scripts/official_diag_validate.py
"""
from __future__ import annotations
import json, sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

def main() -> int:
    t2 = {r["case"]: r for r in json.loads((common.ROOT / "runs/score-impl-t2-20261030/official50-diag.json").read_text())}
    mine = {r["case"]: r for r in json.loads((common.OUTDIR / "official/cur/result.json").read_text())["rows"]}
    rows = []
    for case, r in mine.items():
        sol = r.get("solver_time") or ""
        m = re.search(r"V=(\d+) P=(\d+)", sol)
        lb = re.search(r"\(lb=(\d+)\)", sol)
        if not (m and lb and r.get("time")):
            rows.append({"case": case, "missing": True, "solver_time": sol})
            continue
        V, P = int(m.group(1)), int(m.group(2))
        nmb = int((common.PROB / "cases" / case).read_text().split("\n")[0].split()[0])
        lb_v = int(lb.group(1))
        floor = (nmb + V - 1) / nmb
        row = {"case": case, "V": V, "P": P, "nmb": nmb, "time": r["time"], "lb": lb_v,
               "ratio_lb": round(r["time"] / lb_v, 4), "fill_floor": round(floor, 4),
               "excess": round((r["time"] / lb_v) / floor, 4)}
        t = t2.get(case, {})
        row["t2_V"] = t.get("V"); row["t2_P"] = t.get("P"); row["t2_lb"] = t.get("lb")
        row["t2_ratio_lb"] = t.get("ratio_lb"); row["t2_excess"] = t.get("excess_over_fill")
        row["agree_VP"] = (t.get("V"), t.get("P")) == (V, P)
        row["agree_lb"] = t.get("lb") == lb_v
        rows.append(row)
    good = [r for r in rows if not r.get("missing")]
    exc = sorted([r["excess"] for r in good])
    summary = {
        "n": len(rows), "n_ok": len(good),
        "agree_VP": sum(1 for r in good if r["agree_VP"]),
        "agree_lb": sum(1 for r in good if r["agree_lb"]),
        "max_abs_excess_diff": max(abs(r["excess"] - r["t2_excess"]) for r in good if r["t2_excess"] is not None),
        "excess_median": exc[len(exc) // 2],
        "n_excess_gt_1.02": sum(1 for e in exc if e > 1.02),
        "n_excess_le_1.0": sum(1 for e in exc if e <= 1.0),
        "ratio_lb_median": sorted(r["ratio_lb"] for r in good)[len(good) // 2],
        "worst_excess": sorted(good, key=lambda r: -r["excess"])[:6],
        "rows": rows,
    }
    out = common.OUTDIR / "official/diag-validate.json"
    out.write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in summary.items() if k not in ("rows", "worst_excess")}, ensure_ascii=False))
    for r in summary["worst_excess"]:
        print(r["case"], r["V"], r["P"], r["nmb"], "ratio_lb", r["ratio_lb"], "excess", r["excess"], "t2", r["t2_excess"])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
