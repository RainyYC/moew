"""历史对照：t2 start-snapshot（本轮增量基线）在官方 50 例上的逐例 TIME。

用途：把"本轮增量"（工作区 vs start-snapshot）单独隔离出来；HEAD 只作历史对照。
用法：PYTHONPATH=. python3 runs/score-validation-20261030/scripts/snapshot_sweep.py
输出：runs/score-validation-20261030/official/base/result.json
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

def main() -> int:
    out = common.OUTDIR / "official/base"
    (out / "maps").mkdir(parents=True, exist_ok=True)
    rows = []
    for case in sorted((common.PROB / "cases").glob("*.txt")):
        outp = out / "maps" / (case.stem + ".out")
        row = {"case": case.name}
        row.update(common.solve(case, outp, src=common.ROOT / "runs/score-impl-t2-20261030/start-snapshot", timeout=10.0))
        if row["status"] == "OK":
            row.update(common.official_grade(case, outp))
        rows.append(row)
        print(json.dumps({k: row.get(k) for k in ("case", "status", "time", "wall_s")}, ensure_ascii=False), flush=True)
    ok = [r for r in rows if "time" in r]
    summary = {"tag": "base(start-snapshot)", "n": len(rows), "graded_ok": len(ok),
               "timeout": sum(1 for r in rows if r["status"] == "TO"),
               "invalid": sum(1 for r in rows if "invalid" in r),
               "max_wall_s": max(r["wall_s"] for r in rows),
               "mean_time": sum(r["time"] for r in ok) / len(ok) if ok else None, "rows": rows}
    (out / "result.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
