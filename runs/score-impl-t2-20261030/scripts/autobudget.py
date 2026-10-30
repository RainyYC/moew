"""校准 ``solve_all.auto_budget``：给定内部预算 B，量「求解结束后」还需多久（渲染+落盘）
以及整个子进程墙钟。目标：任何用例墙钟 < 9.6 s（题面硬上限 10 s）。

用法：
    PYTHONPATH=. python3 runs/score-impl-t2-20261030/scripts/autobudget.py \
        --cases b01-loose,b02-m512 --budgets 7.0,8.0,8.4
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUTDIR = ROOT / "runs/score-impl-t2-20261030/budget-cal"
CASES_DEFAULT = ["b01-loose", "b02-m512", "b08-narrow", "b11-short-l", "b13-balanced-compute",
                 "b05-maxmb", "b07-mixed"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=",".join(CASES_DEFAULT))
    ap.add_argument("--budgets", default="7.0,8.0,8.4")
    args = ap.parse_args()
    OUTDIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in args.cases.split(","):
        for budget in (float(x) for x in args.budgets.split(",")):
            out = OUTDIR / f"{name}-{budget}.out"
            inp = ROOT / "bigcases/battery" / f"{name}.in"
            began = time.monotonic()
            proc = subprocess.run(
                [sys.executable, "solver/solve_all.py", str(inp), str(out), "--budget", str(budget)],
                cwd=ROOT, capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=str(ROOT)),
            )
            wall = time.monotonic() - began
            solve = None
            for line in proc.stderr.splitlines():
                if "solve=" in line and "Time=" in line:
                    solve = float(line.split("solve=")[1].split("s")[0])
            ev = subprocess.run([sys.executable, "-m", "judge", "eval", "--json", str(inp), str(out)],
                                cwd=ROOT, capture_output=True, text=True)
            text = ev.stdout
            start = text.find("{\n") if "{" in text else -1
            data = json.loads(text[start:]) if start >= 0 else {
                "ok": False, "time": None, "lb": None,
                "errors": [f"judge exit {ev.returncode}: {(ev.stderr or text)[-300:]}"],
            }
            row = {"case": name, "budget": budget, "solve_s": solve,
                   "post_s": round(wall - (solve or 0.0), 3), "wall_s": round(wall, 3),
                   "ok": data["ok"], "time": data["time"], "lb": data["lb"]}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    (OUTDIR / "calibration.json").write_text(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
