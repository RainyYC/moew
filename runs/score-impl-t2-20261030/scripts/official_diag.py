"""官方 50 例诊断：逐例解析输入与本次映射，算三类指标：

1. **下界裕量**：`time / lb`（lb 用求解器自算的 `formula.lower_bound`，与 judge 同式）；
2. **填充地板**：`(nmb+V−1)/nmb`（V=卡组数、nmb=microbatch 数）—— 这部分不是调度失误；
3. **相对样本基线**：`time / sample_ref`（`report_python.txt` 的样例解 TIME；样例解是官方提供的合法参照，
   但**不是 base**，只能说明"我们比样例快多少"）；
4. 覆盖：`time / best_seen`（50 例里我们目前自己的最好值，用来看还有多少是"已被我们自己找到过的"）。

输出 `regimes`：按 (通信主导? x=0?, L、V、nmb、内存余量分档) 归类，按"最差得分"排序。

用法：PYTHONPATH=. python3 runs/score-impl-t2-20261030/scripts/official_diag.py \
        --result runs/score-impl-t2-20261030/official50-cur/result.json \
        --out runs/score-impl-t2-20261030/official50-diag.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
import sys
sys.path.insert(0, str(ROOT))
from solver import casein, formula  # noqa: E402

PROB = ROOT / "official/extracted/Problem"


def sample_ref() -> dict[str, int]:
    txt = (PROB / "report_python.txt").read_text()
    out = {}
    for line in txt.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0].endswith(".txt") and parts[1] in ("OK", "TO", "INVALID"):
            if parts[1] == "OK":
                out[parts[0]] = int(parts[2])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    refs = sample_ref()
    runs = [json.loads(Path(p).read_text()) for p in args.result]
    times: dict[str, list[int]] = {}
    for run in runs:
        for row in run["rows"]:
            if row.get("time"):
                times.setdefault(row["case"], []).append(row["time"])
    best = {k: min(v) for k, v in times.items()}
    rows = []
    for run in runs:
        for row in run["rows"]:
            case = row["case"]
            if row["status"] != "OK":
                rows.append({"case": case, "label": run["label"], "status": row["status"]})
                continue
            input_path = PROB / "cases" / case
            c = casein.parse_case(input_path)
            out_file = Path(args.out).parent / f"official50-{run['label']}" / "maps" / case.replace(".txt", ".out")
            V = P = None
            if out_file.exists():
                head = out_file.read_text().splitlines()[0].split()
                V, P = int(head[0]), int(head[1])
            comm = 2 * formula.comm_payload(c, 0, P or 1) * c.Fio if (P or 1) > 1 else 0
            compute = 0
            fill = (c.nmb + (V or 1) - 1) / c.nmb
            rows.append({
                "case": case, "label": run["label"], "status": "OK", "time": row["time"],
                "lb": row.get("solver_lb"), "grid": row.get("grid"), "V": V, "P": P,
                "wall_s": row["wall_s"],
                "ratio_lb": round(row["time"] / row["solver_lb"], 4) if row.get("solver_lb") else None,
                "fill_floor": round(fill, 4),
                "excess_over_fill": round(row["time"] / row["solver_lb"] / fill, 4) if row.get("solver_lb") else None,
                "vs_sample": round(row["time"] / refs[case], 4) if case in refs else None,
                "over_best": round(row["time"] / best[case], 4),
                "L": c.L, "nmb": c.nmb, "E": c.E, "S": c.S, "R": c.R, "M": c.M,
                "x_zero": (P == 1), "Fs": c.Fs, "Fio": c.Fio, "Fin": c.Fin,
            })
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    worst = sorted([r for r in rows if r.get("ratio_lb")], key=lambda r: -r["ratio_lb"])[:10]
    print("worst ratio_lb:")
    for r in worst:
        print(f"  {r['case']:24s} {r['label']:5s} time={r['time']} lb={r['lb']} V={r['V']} P={r['P']} "
              f"ratio_lb={r['ratio_lb']} fill={r['fill_floor']} excess={r['excess_over_fill']} "
              f"vs_sample={r['vs_sample']} L={r['L']} nmb={r['nmb']}")
    print(f"rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
