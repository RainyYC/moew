"""官方 50 例独立复验：当前工作区（经验证快照）+ 官方 grader.py，逐例 10 s 墙钟。

用法：PYTHONPATH=. python3 runs/score-validation-20261030/scripts/run_official50.py --tag cur
输出：runs/score-validation-20261030/official/<tag>/result.json + maps/
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--src", default=None, help="源码目录（默认：验证快照）")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--budget", type=float, default=None)
    args = ap.parse_args()
    src = Path(args.src) if args.src else common.OUTDIR / "snapshot"
    out = common.OUTDIR / "official" / args.tag
    (out / "maps").mkdir(parents=True, exist_ok=True)
    rows = []
    for case in sorted((common.PROB / "cases").glob("*.txt")):
        outp = out / "maps" / (case.stem + ".out")
        row = {"case": case.name}
        row.update(common.solve(case, outp, src=src, timeout=args.timeout, budget=args.budget))
        if row["status"] == "OK":
            row.update(common.official_grade(case, outp))
        rows.append(row)
        print(json.dumps({k: row.get(k) for k in ("case", "status", "time", "wall_s", "grader_s")},
                         ensure_ascii=False), flush=True)
    ok = [r for r in rows if "time" in r]
    summary = {"tag": args.tag, "src": str(src), "n": len(rows), "graded_ok": len(ok),
               "timeout": sum(1 for r in rows if r["status"] == "TO"),
               "invalid": sum(1 for r in rows if "invalid" in r),
               "error": sum(1 for r in rows if r["status"] == "ERROR"),
               "max_wall_s": max(r["wall_s"] for r in rows),
               "max_wall_case": max(rows, key=lambda r: r["wall_s"])["case"],
               "mean_time": sum(r["time"] for r in ok) / len(ok) if ok else None,
               "geomean_time": common.geomean([r["time"] for r in ok]),
               "rows": rows}
    (out / "result.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
