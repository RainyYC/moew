#!/usr/bin/env python3
"""Run an experimental solver on official cases and compare with a saved baseline."""

import argparse
import csv
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "data/official/Problem/cases"
GRADER = ROOT / "data/official/Problem/grader.py"
DEFAULT_BASELINE = ROOT / "results/budget_search/full50/summary.tsv"


def read_baseline(path):
    """Read and validate the reference summary before starting any solver."""
    baseline = {}
    with path.open(newline="", encoding="utf-8") as f:
        rows = csv.DictReader(f, delimiter="\t")
        required = {"case", "exit", "checker_time"}
        if not rows.fieldnames or not required.issubset(rows.fieldnames):
            raise ValueError("baseline must contain case, exit, and checker_time columns")
        for line, row in enumerate(rows, start=2):
            name = row.get("case", "")
            if not name:
                raise ValueError("baseline row %d has an empty case" % line)
            if name in baseline:
                raise ValueError("baseline contains duplicate case: %s" % name)
            if row.get("exit", "") != "0":
                raise ValueError("baseline case %s does not have exit 0" % name)
            score = row.get("checker_time", "")
            if not score.isdigit() or int(score) <= 0:
                raise ValueError("baseline case %s has an invalid checker_time" % name)
            baseline[name] = int(score)
    if not baseline:
        raise ValueError("baseline contains no cases")
    return baseline


def run_solver(argv, out_path, err_path, timeout_seconds):
    start = time.monotonic()
    with out_path.open("wb") as stdout, err_path.open("wb") as stderr:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=stdout,
                                stderr=stderr, start_new_session=True)
        timed_out = False
        try:
            try:
                rc = proc.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                rc = proc.wait()
        finally:
            if proc.stdin is not None:
                proc.stdin.close()
    return rc, time.monotonic() - start, timed_out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path, help="candidate solver executable")
    parser.add_argument("output_dir", type=Path, help="directory for outputs and reports")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE,
                        help="reference summary TSV (default: %(default)s)")
    parser.add_argument("--case-regex", help="run only case names matching this regex")
    parser.add_argument("--timeout", type=float, default=10.0,
                        help="per-case timeout in seconds (default: 10)")
    parser.add_argument("--solver-arg", action="append", default=[],
                        help="argument passed to solver; may be repeated")
    args = parser.parse_args()

    candidate = args.candidate.resolve()
    if not candidate.is_file():
        parser.error("candidate binary does not exist: %s" % candidate)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        case_re = re.compile(args.case_regex) if args.case_regex else None
    except re.error as exc:
        parser.error("invalid --case-regex: %s" % exc)

    outdir = args.output_dir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    baseline_path = args.baseline.resolve()
    try:
        baseline = read_baseline(baseline_path)
    except (OSError, ValueError) as exc:
        parser.error("invalid baseline %s: %s" % (baseline_path, exc))
    cases = sorted(CASES.glob("*.txt"))
    if case_re:
        cases = [p for p in cases if case_re.search(p.stem)]
    if not cases:
        parser.error("no official cases matched")
    missing = [p.stem for p in cases if p.stem not in baseline]
    if missing:
        parser.error("baseline is missing target case(s): %s" % ", ".join(missing))

    fields = ["case", "exit", "wall_seconds", "checker_time", "baseline_time",
              "absolute_improvement", "improvement_pct"]
    results = []
    with (outdir / "summary.tsv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for case in cases:
            name = case.stem
            output = outdir / (name + ".out")
            error = outdir / (name + ".stderr")
            command = [str(candidate), *args.solver_arg, str(case)]
            rc, wall, timed_out = run_solver(command, output, error, args.timeout)
            checker_time = None
            failure = "timeout" if timed_out else ("solver_exit_%d" % rc if rc else None)
            if not failure:
                try:
                    checked = subprocess.run(
                        [sys.executable, str(GRADER), str(case), str(output)],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, check=False, timeout=10)
                    (outdir / (name + ".checker.stderr")).write_text(
                        checked.stderr, encoding="utf-8")
                    match = re.fullmatch(r"\s*(\d+)\s*", checked.stdout)
                except subprocess.TimeoutExpired as exc:
                    failure = "checker_timeout"
                    rc = 102
                    stderr_text = exc.stderr or ""
                    if isinstance(stderr_text, bytes):
                        stderr_text = stderr_text.decode("utf-8", errors="replace")
                    (outdir / (name + ".checker.stderr")).write_text(
                        stderr_text + "\ngrader exceeded 10 second timeout\n", encoding="utf-8")
                    match = None
                if failure == "checker_timeout":
                    pass
                elif checked.returncode or not match:
                    failure = "invalid_output"
                    rc = 100 + checked.returncode if checked.returncode else 101
                else:
                    checker_time = int(match.group(1))
            base = baseline.get(name)
            absolute = (base - checker_time) if base is not None and checker_time is not None else None
            pct = (100.0 * absolute / base) if absolute is not None and base else None
            row = {"case": name, "exit": rc, "wall_seconds": "%.3f" % wall,
                   "checker_time": checker_time if checker_time is not None else "",
                   "baseline_time": base if base is not None else "",
                   "absolute_improvement": absolute if absolute is not None else "",
                   "improvement_pct": ("%.6f" % pct) if pct is not None else ""}
            writer.writerow(row)
            f.flush()
            print("%s\tTime=%s\timprovement=%s\twall=%s" % (
                name,
                checker_time if checker_time is not None else "INVALID",
                absolute if absolute is not None else "N/A",
                "%.3f" % wall), flush=True)
            results.append({"case": name, "failure": failure, "wall_seconds": wall,
                            "checker_time": checker_time, "baseline_time": base,
                            "improvement": absolute, "improvement_pct": pct})

    valid = [r for r in results if r["checker_time"] is not None]
    paired = [r for r in valid if r["baseline_time"] is not None]
    improvements = [r["improvement"] for r in paired]
    walls = [r["wall_seconds"] for r in results]
    validation = {
        "candidate": str(candidate), "output_dir": str(outdir),
        "baseline": str(baseline_path),
        "timeout_seconds": args.timeout, "case_regex": args.case_regex,
        "solver_args": args.solver_arg, "cases": len(results),
        "successful_valid": len(valid), "failed_or_invalid": len(results) - len(valid),
        "timeouts": sum(r["failure"] == "timeout" for r in results),
        "compared_cases": len(paired),
        "improved": sum(x > 0 for x in improvements),
        "tied": sum(x == 0 for x in improvements),
        "regressed": sum(x < 0 for x in improvements),
        "mean_checker_time": (sum(r["checker_time"] for r in valid) / len(valid)) if valid else None,
        "mean_baseline_time": (sum(r["baseline_time"] for r in paired) / len(paired)) if paired else None,
        "mean_absolute_improvement": (sum(improvements) / len(improvements)) if improvements else None,
        "mean_point_relative_improvement_pct": (sum(r["improvement_pct"] for r in paired) / len(paired)) if paired else None,
        "mean_wall_seconds": sum(walls) / len(walls) if walls else None,
        "max_wall_seconds": max(walls) if walls else None,
        "max_wall_case": max(results, key=lambda r: r["wall_seconds"])["case"] if results else None,
    }
    (outdir / "validation.json").write_text(json.dumps(validation, indent=2) + "\n",
                                              encoding="utf-8")
    print(json.dumps(validation, indent=2))
    return 0 if len(valid) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
