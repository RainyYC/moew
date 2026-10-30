"""b13 A/B（独立子进程，逐个变体落盘）：旧求解器（src-snapshots/prior）vs 当前工作区。

每个变体跑 N 次，记录：solver 自报 Time、judge Time/ok/内存峰值、墙钟；并保留原始输出。
用法：PYTHONPATH=. python3 runs/score-impl-t2-20261030/scripts/ab_b13.py --reps 2 \
        --out runs/score-impl-t2-20261030/b13-ab
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PRIOR = ROOT / "runs/score-impl-20261030/src-snapshots/prior"
CASE = ROOT / "bigcases/battery/b13-balanced-compute.in"


def run(src_dir: Path | None, out: Path) -> dict:
    cmd = [sys.executable, "solver/solve_all.py", str(CASE), str(out)]
    env = dict(os.environ, PYTHONPATH=f"{src_dir}{os.pathsep}{ROOT}" if src_dir else str(ROOT))
    began = time.monotonic()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=env)
    wall = time.monotonic() - began
    if proc.returncode != 0:
        return {"ok": False, "exit": proc.returncode, "wall_s": round(wall, 3),
                "failure": (proc.stderr or proc.stdout)[-400:]}
    ev = subprocess.run([sys.executable, "-m", "judge", "eval", "--json", str(CASE), str(out)],
                        cwd=ROOT, capture_output=True, text=True)
    text = ev.stdout
    idx = text.find("{\n")
    if idx < 0:
        return {"ok": False, "wall_s": round(wall, 3), "failure": f"judge: {(ev.stderr or text)[-300:]}"}
    data = json.loads(text[idx:])
    peak = max((g["mexp"] + g["movl"] + g["mact"]) / g["limit"] for g in data["groups"])
    solver_time = None
    for line in proc.stderr.splitlines():
        if "Time=" in line and "solve=" in line:
            solver_time = int(line.split("Time=")[1].split(" ")[0])
    return {"ok": data["ok"], "judge_time": data["time"], "solver_time": solver_time,
            "lb": data["lb"], "grid": data["grid"], "K": data["K"], "n_errors": len(data["errors"]),
            "peak_mem_ratio": round(peak, 4), "wall_s": round(wall, 3)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    outdir = Path(args.out)
    (outdir / "prior").mkdir(parents=True, exist_ok=True)
    (outdir / "current").mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="t2-prior-"))
    shutil.copytree(PRIOR, tmp / "solver")
    rows = []
    for rep in range(args.reps):
        for label, src, sub in (("prior", tmp, "prior"), ("current", None, "current")):
            row = run(src, outdir / sub / f"b13.r{rep}.out")
            row.update({"variant": label, "rep": rep})
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    shutil.rmtree(tmp, ignore_errors=True)
    (outdir / "ab.json").write_text(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
