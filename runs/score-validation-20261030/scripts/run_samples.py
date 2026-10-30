"""官方六样例（cases/ex1..ex6, mini）独立复验：
① 用我们的求解器重新求解 → 官方 grader.py 判 TIME → 与 cases/expected.json 的 base 比较；
② 对仓库里现成的 cases/*.out 也用官方 grader 复核 base 本身（确认 base 口径一致）。

用法：PYTHONPATH=. python3 runs/score-validation-20261030/scripts/run_samples.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

NAMES = ["ex1", "ex2", "ex3", "ex4", "ex5", "ex6", "mini"]


def main() -> int:
    out = common.OUTDIR / "samples"
    (out / "outs").mkdir(parents=True, exist_ok=True)
    expected = json.loads((common.ROOT / "cases/expected.json").read_text(encoding="utf-8"))
    rows = []
    for name in NAMES:
        inp = common.ROOT / f"cases/{name}.in"
        outp = out / "outs" / f"{name}.out"
        solve = common.solve(inp, outp, src=common.OUTDIR / "snapshot", timeout=10.0)
        row = {"case": name, "solve": solve,
               "expected_json": expected.get(name)}
        if solve["status"] == "OK":
            row["official"] = common.official_grade(inp, outp)
            row["judge"] = common.judge_eval(inp, outp)
            if "time" in row["official"]:
                row["time"] = row["official"]["time"]
        base_out = common.ROOT / f"cases/{name}.out"
        if base_out.exists() and name != "mini":
            row["base_out_official"] = common.official_grade(inp, base_out)
            row["base_out_sha256"] = common.sha256(base_out)
        exp = (expected.get(name) or {}).get("time")
        row["expected_time"] = exp
        if row.get("time") and exp:
            row["ratio_vs_expected"] = round(row["time"] / exp, 6)
        rows.append(row)
        print(json.dumps({k: row.get(k) for k in ("case", "time", "expected_time",
                                                  "ratio_vs_expected")}, ensure_ascii=False), flush=True)
    ok = [r for r in rows if r.get("time")]
    ratios = [r["time"] / r["expected_time"] for r in ok if r.get("expected_time")]
    summary = {"n": len(rows), "ok": len(ok), "all_legal": len(ok) == len(rows),
               "geomean_vs_expected": common.geomean(ratios), "rows": rows}
    (out / "result.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
