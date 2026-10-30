#!/usr/bin/env python3
"""A/B 单例对比：同一输入、同一个预算，分别用「开工前源码快照」与「当前工作区求解器」求解，
并用 judge 复核。子进程隔离（源码快照先拷进临时目录、用 PYTHONPATH 指过去）。

用法::

    PYTHONPATH=. python3 runs/score-impl-20261030/ab_test.py --out runs/score-impl-20261030/ab-final \
        [--budget auto] [--cases b13-balanced-compute ...]
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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from solver import casein  # noqa: E402

BATTERY = ROOT / "bigcases" / "battery"
SNAPSHOT = ROOT / "runs/score-impl-20261030/src-snapshots/prior"
CASES = [
    "b01-loose", "b02-m512", "b03-m256", "b04-m96", "b05-maxmb",
    "b06-maxmb-tight", "b07-mixed", "b08-narrow", "b09-small-e",
    "b10-high-k", "b11-short-l", "b12-compute-bound", "b13-balanced-compute",
]


def run_one(inp: Path, out: Path, budget: float | None, solver_dir: Path | None) -> dict:
    cmd = [sys.executable, "solver/solve_all.py", str(inp), str(out)]
    if budget is not None:
        cmd += ["--budget", str(budget)]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    if solver_dir is not None:
        # 源码快照里的 solver/ 优先于工作区：把快照目录放在 sys.path 最前
        env["PYTHONPATH"] = f"{solver_dir}{os.pathsep}{ROOT}"
    began = time.monotonic()
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, env=env)
    wall = time.monotonic() - began
    row = {"exit": proc.returncode, "wall_s": round(wall, 3)}
    if proc.returncode != 0 or not out.exists():
        row["ok"] = False
        row["failure"] = (proc.stderr or proc.stdout)[-500:]
        return row
    ev = subprocess.run([sys.executable, "-m", "judge", "eval", "--json", str(inp), str(out)],
                        cwd=str(ROOT), capture_output=True, text=True)
    try:
        data = json.loads(ev.stdout)
    except json.JSONDecodeError:
        data = {"ok": False, "errors": ["judge json parse failed"], "raw": ev.stdout[-300:]}
    groups = data.get("groups") or []
    peak = max(((g["mexp"] + g["movl"] + g["mact"]) / g["limit"] for g in groups), default=0.0)
    row.update({"ok": bool(data.get("ok")), "time": data.get("time"), "lb": data.get("lb"),
                "grid": data.get("grid"), "peak_ratio": round(peak, 4),
                "errors": (data.get("errors") or [])[:2]})
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--budget", default="auto")
    ap.add_argument("--cases", nargs="*", default=CASES)
    args = ap.parse_args()
    budget = None if args.budget == "auto" else float(args.budget)
    out_dir = Path(args.out)
    (out_dir / "out").mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="score-impl-prior-"))
    shutil.copytree(SNAPSHOT, tmp / "solver")
    rows = []
    for name in args.cases:
        inp = BATTERY / f"{name}.in"
        n_ops = casein.parse_case(str(inp)).n_ops
        prior = run_one(inp, out_dir / "out" / f"{name}.prior.out", budget, tmp)
        cur = run_one(inp, out_dir / "out" / f"{name}.cur.out", budget, None)
        rel = None
        if prior.get("time") and cur.get("time"):
            rel = cur["time"] / prior["time"]
        rows.append({"case": name, "n_ops": n_ops, "prior": prior, "current": cur,
                     "time_rel": round(rel, 5) if rel else None})
        print(f"{name}: prior={prior.get('time')} ({prior.get('wall_s')}s, ok={prior.get('ok')}) "
              f"cur={cur.get('time')} ({cur.get('wall_s')}s, ok={cur.get('ok')}) rel={rel}", file=sys.stderr)
    summary = {"budget": args.budget, "rows": rows}
    (out_dir / "ab.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
