#!/usr/bin/env python3
"""13 个大用例批量求解 + judge 复核 + 几何平均分统计（score-impl 实验驱动）。

用法::

    PYTHONPATH=. python3 runs/score-impl-20261030/run_battery.py \
        --label baseline --out runs/score-impl-20261030/baseline \
        [--cases b13-balanced-compute b02-m512 ...] [--budget 9.2] [--explicit-budget]

* 每个用例**独立子进程**跑 `solver/solve_all.py <in> <out>`（与官方逐用例调用形态一致），
  用 ``/usr/bin/time`` 量**整个子进程墙钟**（含解释器启动），并记录退出码。
* 求解完成后用 `python3 -m judge eval --json` 复核：ok / errors / Time / lb / grid / 内存峰值。
* 输出 ``<out>/result.json``：逐例 Time/lb、相对 ``--ref``（默认 13 例基线）变化、
  几何平均 ``exp(mean log(time/base))``（base = 题面样例值；无样例时用生产 13 例的 Time）。
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from solver import casein  # noqa: E402

BATTERY = ROOT / "bigcases" / "battery"
DEFAULT_CASES = [
    "b01-loose", "b02-m512", "b03-m256", "b04-m96", "b05-maxmb",
    "b06-maxmb-tight", "b07-mixed", "b08-narrow", "b09-small-e",
    "b10-high-k", "b11-short-l", "b12-compute-bound", "b13-balanced-compute",
]


def judge_eval(inp: Path, out: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "judge", "eval", "--json", str(inp), str(out)],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return {"ok": False, "error": f"judge exit {proc.returncode}", "stderr": proc.stderr[-800:]}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        # judge 在成功时也可能先打人读摘要；取最后一个 JSON 对象
        text = proc.stdout
        start = text.find("{")
        data = json.loads(text[start:]) if start >= 0 else {"ok": False, "error": "no json"}
    groups = data.get("groups") or []
    peak = max((g["mexp"] + g["movl"] + g["mact"], g["limit"]) for g in groups) if groups else (0, 1)
    data["peak_bytes"], data["limit_bytes"] = peak
    data["peak_ratio"] = peak[0] / peak[1] if peak[1] else None
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cases", nargs="*", default=DEFAULT_CASES)
    ap.add_argument("--budget", type=float, default=None,
                    help="显式 --budget（不给则用 solve_all 的 auto_budget）")
    ap.add_argument("--ref", default=str(ROOT / "runs/score-impl-20261030/baseline/result.json"))
    args = ap.parse_args()

    out_dir = Path(args.out)
    (out_dir / "out").mkdir(parents=True, exist_ok=True)
    (out_dir / "logs").mkdir(parents=True, exist_ok=True)
    ref: dict = {}
    ref_path = Path(args.ref)
    if ref_path.exists():
        ref = {row["case"]: row for row in json.loads(ref_path.read_text())["rows"]}

    rows = []
    for name in args.cases:
        inp = BATTERY / f"{name}.in"
        outp = out_dir / "out" / f"{name}.out"
        cmd = [sys.executable, "solver/solve_all.py", str(inp), str(outp)]
        if args.budget is not None:
            cmd += ["--budget", str(args.budget)]
        began = time.monotonic()
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
        wall = time.monotonic() - began
        (out_dir / "logs" / f"{name}.log").write_text(proc.stderr)
        row: dict = {
            "case": name, "label": args.label, "exit": proc.returncode,
            "wall_s": round(wall, 3), "n_ops": casein.parse_case(str(inp)).n_ops,
        }
        if proc.returncode != 0 or not outp.exists():
            row["ok"] = False
            row["failure"] = (proc.stderr or proc.stdout)[-600:]
            if ref.get(name):
                row["baseline_time"] = ref[name].get("time")
            rows.append(row)
            print(f"{name}: FAILED exit={proc.returncode} wall={wall:.2f}s", file=sys.stderr)
            continue
        data = judge_eval(inp, outp)
        row.update({
            "ok": bool(data.get("ok")),
            "time": data.get("time"),
            "lb": data.get("lb"),
            "grid": data.get("grid"),
            "K": data.get("K"),
            "peak_ratio": data.get("peak_ratio"),
            "errors": data.get("errors")[:3] if data.get("errors") else [],
        })
        base = ref.get(name, {}).get("time")
        row["baseline_time"] = base
        if base and row["time"]:
            row["rel"] = row["time"] / base
        rows.append(row)
        rel = f"{row['rel']:.4f}" if row.get("rel") else "-"
        print(f"{name}: ok={row['ok']} time={row['time']} lb={row['lb']} "
              f"grid={row['grid']} rel={rel} wall={wall:.2f}s peak={row['peak_ratio']}", file=sys.stderr)

    scored = [r for r in rows if r.get("ok") and r.get("time") and r.get("baseline_time")]
    geo = math.exp(sum(math.log(r["time"] / r["baseline_time"]) for r in scored) / len(scored)) if scored else None
    summary = {
        "label": args.label,
        "cases": args.cases,
        "budget": args.budget,
        "all_ok": all(r.get("ok") for r in rows) and len(rows) == len(args.cases),
        "max_wall_s": max((r["wall_s"] for r in rows), default=None),
        "geomean_rel_vs_ref": geo,
        "rows": rows,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (out_dir / "result.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    total = len(rows)
    okc = sum(1 for r in rows if r.get("ok"))
    print(f"\n[{args.label}] ok={okc}/{total} max_wall={summary['max_wall_s']:.2f}s "
          f"geomean rel={geo:.5f}" if geo else f"\n[{args.label}] ok={okc}/{total}", file=sys.stderr)
    return 0 if okc == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
