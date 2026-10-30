#!/usr/bin/env python3
"""Run the official grader on every lower-makespan sequence-left-shift candidate."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "algorithm_v5" / "borrow_probe"
report = json.loads((DIR / "probe.json").read_text())
for row in report:
    if not row.get("candidate"):
        continue
    inp = ROOT / "data/official/Problem/cases" / f"{row['case']}.txt"
    out = ROOT / row["candidate"]
    run = subprocess.run([sys.executable, str(ROOT / "data/official/Problem/grader.py"),
                          str(inp), str(out)], cwd=ROOT, text=True, capture_output=True)
    try:
        grader_time = int(run.stdout.strip().splitlines()[-1]) if run.stdout.strip() else None
    except ValueError:
        grader_time = None
    row["official_exit"] = run.returncode
    row["official_time"] = grader_time
    row["official_legal"] = run.returncode == 0 and grader_time == row["after"]
    row["official_stderr"] = run.stderr[-1000:]
    print(f"{row['case']} exit={run.returncode} time={grader_time} after={row['after']} legal={row['official_legal']}")
(DIR / "probe.json").write_text(json.dumps(report, indent=2) + "\n")
