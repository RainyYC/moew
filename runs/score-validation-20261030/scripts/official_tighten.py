"""压力验证（读-only）：把所有官方 50 例的求解预算人为提到 9.6 s（比生产 7.6 高 2 s），
看"预算余量还有多少"。目的：判断 7.35 s 峰值是预算决定的（安全）还是计算量决定的（有风险）。

用法：PYTHONPATH=. python3 runs/score-validation-20261030/scripts/official_tighten.py
输出：runs/score-validation-20261030/official/tighten/result.json
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

BUDGET = 9.6

def main() -> int:
    out = common.OUTDIR / "official/tighten"
    (out / "maps").mkdir(parents=True, exist_ok=True)
    rows = []
    for case in sorted((common.PROB / "cases").glob("*.txt")):
        outp = out / "maps" / (case.stem + ".out")
        row = {"case": case.name}
        row.update(common.solve(case, outp, src=common.OUTDIR / "snapshot", timeout=10.0, budget=BUDGET))
        if row["status"] == "OK":
            row.update(common.official_grade(case, outp))
        rows.append(row)
        print(json.dumps({k: row.get(k) for k in ("case", "status", "time", "wall_s")}, ensure_ascii=False), flush=True)
    ok = [r for r in rows if "time" in r]
    summary = {"tag": "tighten", "budget": BUDGET, "n": len(rows), "graded_ok": len(ok),
               "timeout": sum(1 for r in rows if r["status"] == "TO"),
               "invalid": sum(1 for r in rows if "invalid" in r),
               "max_wall_s": max(r["wall_s"] for r in rows),
               "max_wall_case": max(rows, key=lambda r: r["wall_s"])["case"],
               "mean_time": sum(r["time"] for r in ok) / len(ok) if ok else None, "rows": rows}
    (out / "result.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
