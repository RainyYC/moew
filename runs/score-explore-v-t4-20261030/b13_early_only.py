"""t4：复现 t1 的 b13 = 4.2984846e16（P=32,V=16,K=16），并给出**可重复构造参数**。

做法（不写生产文件、不硬编码 b13 名字以外的东西）：在冻结快照进程内，
  * 只对 `mode == "early"` 把窗口钉成 W*；
  * 不改变其它任何搜索逻辑。
扫描 W* 与 budget，记录每个组合的最终 P/V/psi/W/variant/mode/Time 与官方 grader TIME。

用法：PYTHONPATH=. python3 runs/score-explore-v-t4-20261030/b13_early_only.py \
        --windows 20,25,12,34 --budgets 6.0,8.0 --out .../probe/b13-early-scan.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAP = ROOT / "runs/score-explore-v-t4-20261030/snapshot"
sys.path.insert(0, str(SNAP))
sys.path.insert(1, str(ROOT))
from solver import casein, sched, solve  # noqa: E402

WORK = ROOT / "runs/score-explore-v-t4-20261030"
CASE = ROOT / "bigcases/battery/b13-balanced-compute.in"


def run_one(W, budget):
    orig = sched.schedule
    log: list[str] = []

    def patched(case, plan, window, variant, mode="prio", priority=None, comm_gap=0, fill_gaps=False):
        if mode == "early" and W:
            window = W
        return orig(case, plan, window, variant, mode, priority=priority,
                    comm_gap=comm_gap, fill_gaps=fill_gaps)

    sched.schedule = patched
    try:
        case = casein.parse_case(CASE)
        sol = solve.solve_case(case, budget=budget, log=log.append)
    finally:
        sched.schedule = orig
    tag = f"W{W or 'def'}-B{budget}"
    out = WORK / "out" / f"b13.earlyonly.{tag}.out"
    out.write_text(sol.text)
    g = subprocess.run([sys.executable, str(ROOT / "official/extracted/Problem/grader.py"),
                        str(CASE), str(out)], capture_output=True, text=True)
    line = (g.stdout or "").strip().splitlines()
    grade = int(line[-1]) if line and line[-1].strip().isdigit() else None
    return {"W": W or "default", "budget": budget, "P": sol.P, "V": sol.V, "K": sol.K,
            "psi": list(sol.psi), "window": sol.window, "mode": sol.mode,
            "variant": list(sol.variant), "time": sol.time, "lb": sol.lb,
            "grader_time": grade, "out": str(out), "log": log[-6:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", default="20,25,12,34")
    ap.add_argument("--budgets", default="6.0,8.0")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rows = []
    for budget in (float(b) for b in a.budgets.split(",")):
        for W in [int(w) for w in a.windows.split(",")]:
            row = run_one(W, budget)
            rows.append(row)
            print(json.dumps({k: row[k] for k in ("W", "budget", "P", "V", "mode", "window",
                                                   "time", "grader_time")}, ensure_ascii=False), flush=True)
    Path(a.out).write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
