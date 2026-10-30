#!/usr/bin/env python3
"""Paired, sequential timing recheck for the module split solver binaries."""

import csv
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "build/solver_before_module_split"
NEW = ROOT / "build/solver_modular_candidate"
CASES = ROOT / "data/official/Problem/cases"
GRADER = ROOT / "data/official/Problem/grader.py"
OUT = ROOT / "results/module_refactor/paired_recheck"
TARGETS = ["r24_p3_flat", "x09_lr_skew_p6", "x12_lr_close_p10"]
ENGINE_RE = re.compile(r"LOCAL_ENGINE\s+([^\r\n]+)")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def engine_counts(path):
    raw = path.read_text(encoding="utf-8", errors="replace")
    return [dict(re.findall(r"([A-Za-z_]+)=([^\s]+)", m))
            for m in ENGINE_RE.findall(raw)]


def stable_engine_counts(records):
    """Drop only measured duration fields; retain counters and score values."""
    return [{k: v for k, v in record.items() if not k.endswith("_seconds")}
            for record in records]


def cpu_seconds(usage):
    return usage.ru_utime + usage.ru_stime


def run_solver(tag, binary, case, pass_limit, order):
    pass_label = "default" if pass_limit is None else str(pass_limit)
    stem = f"{order:02d}_{tag}_{case.stem}_pass{pass_label}"
    stdout_path = OUT / f"{stem}.out"
    stderr_path = OUT / f"{stem}.stderr"
    argv = [str(binary)]
    if pass_limit is not None:
        argv.append(f"--polish-pass-limit={pass_limit}")
    argv.append(str(case))
    started = time.monotonic()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=stdout,
                                stderr=stderr, start_new_session=True)
        timed_out = False
        try:
            try:
                rc = proc.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                rc = proc.wait()
        finally:
            # Match the official runner: stdin is a pipe and remains open while
            # the solver runs; EOF is sent only after it exits or is killed.
            if proc.stdin is not None:
                proc.stdin.close()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    wall = time.monotonic() - started
    result = {
        "order": order, "tag": tag, "binary": str(binary), "case": case.stem,
        "polish_pass_limit": pass_label, "argv": argv, "return_code": rc,
        "timed_out": timed_out, "wall_seconds": wall,
        "solver_child_cpu_seconds": cpu_seconds(after) - cpu_seconds(before),
        "stdout": stdout_path.name, "stderr": stderr_path.name,
        "stdout_sha256": digest(stdout_path), "stderr_sha256": digest(stderr_path),
        "local_engine_counts": engine_counts(stderr_path),
    }
    if not timed_out and rc == 0:
        check = subprocess.run([sys.executable, str(GRADER), str(case), str(stdout_path)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=10, check=False)
        checker_path = OUT / f"{stem}.checker.stdout"
        checker_err_path = OUT / f"{stem}.checker.stderr"
        checker_path.write_bytes(check.stdout)
        checker_err_path.write_bytes(check.stderr)
        match = re.fullmatch(rb"\s*(\d+)\s*", check.stdout)
        result["grader_return_code"] = check.returncode
        result["grader_stdout"] = checker_path.name
        result["grader_stderr"] = checker_err_path.name
        result["score"] = int(match.group(1)) if check.returncode == 0 and match else None
    else:
        result["grader_return_code"] = None
        result["score"] = None
    return result


def main():
    for p in (OLD, NEW, GRADER):
        if not p.is_file():
            raise SystemExit(f"missing required file: {p}")
    OUT.mkdir(parents=True, exist_ok=True)
    cases = {name: CASES / f"{name}.txt" for name in TARGETS}
    for name, path in cases.items():
        if not path.is_file():
            raise SystemExit(f"missing case: {path}")

    runs = []
    order = 0
    # Default-budget runs: each case gets both binary orders.
    for round_no, sequence in [(1, ["old", "new"]), (2, ["new", "old"])]:
        for case_name in TARGETS:
            for tag in sequence:
                order += 1
                binary = OLD if tag == "old" else NEW
                runs.append(run_solver(tag, binary, cases[case_name], None, order))
    # The tighter cap is independently order-balanced on r24.
    for round_no, sequence in [(1, ["old", "new"]), (2, ["new", "old"])]:
        for tag in sequence:
            order += 1
            binary = OLD if tag == "old" else NEW
            runs.append(run_solver(tag, binary, cases["r24_p3_flat"], 8, order))

    (OUT / "runs.json").write_text(json.dumps(runs, indent=2) + "\n", encoding="utf-8")
    fields = ["order", "tag", "case", "polish_pass_limit", "return_code", "timed_out",
              "wall_seconds", "solver_child_cpu_seconds", "score", "stdout_sha256",
              "stderr_sha256", "local_engine_counts"]
    with (OUT / "summary.tsv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in runs:
            item = dict(row)
            item["wall_seconds"] = f"{row['wall_seconds']:.6f}"
            item["solver_child_cpu_seconds"] = f"{row['solver_child_cpu_seconds']:.6f}"
            item["local_engine_counts"] = json.dumps(row["local_engine_counts"],
                                                       separators=(",", ":"))
            writer.writerow({k: item.get(k) for k in fields})
    # Derive compact parity and CPU summaries without discarding any run.
    comparisons = []
    for case_name in TARGETS:
        a = [x for x in runs if x["case"] == case_name and x["polish_pass_limit"] == "default"]
        old = [x for x in a if x["tag"] == "old"]
        new = [x for x in a if x["tag"] == "new"]
        comparisons.append({
            "case": case_name, "old_scores": [x["score"] for x in old],
            "new_scores": [x["score"] for x in new],
            "old_cpu_seconds": [x["solver_child_cpu_seconds"] for x in old],
            "new_cpu_seconds": [x["solver_child_cpu_seconds"] for x in new],
            "old_stdout_sha256": [x["stdout_sha256"] for x in old],
            "new_stdout_sha256": [x["stdout_sha256"] for x in new],
            "old_engine_counts": [x["local_engine_counts"] for x in old],
            "new_engine_counts": [x["local_engine_counts"] for x in new],
            "old_stable_engine_counts": [stable_engine_counts(x["local_engine_counts"]) for x in old],
            "new_stable_engine_counts": [stable_engine_counts(x["local_engine_counts"]) for x in new],
        })
    cap8 = [x for x in runs if x["polish_pass_limit"] == "8"]
    cap8_comparison = {
        "old_stdout_sha256": [x["stdout_sha256"] for x in cap8 if x["tag"] == "old"],
        "new_stdout_sha256": [x["stdout_sha256"] for x in cap8 if x["tag"] == "new"],
        "old_engine_counts": [x["local_engine_counts"] for x in cap8 if x["tag"] == "old"],
        "new_engine_counts": [x["local_engine_counts"] for x in cap8 if x["tag"] == "new"],
        "old_cpu_seconds": [x["solver_child_cpu_seconds"] for x in cap8 if x["tag"] == "old"],
        "new_cpu_seconds": [x["solver_child_cpu_seconds"] for x in cap8 if x["tag"] == "new"],
        "all_stdout_identical": len({x["stdout_sha256"] for x in cap8}) == 1,
        "all_engine_counts_identical": len({json.dumps(stable_engine_counts(x["local_engine_counts"]), sort_keys=True)
                                             for x in cap8}) == 1,
    }
    report = {"runs": len(runs), "all_successful": all(
        x["return_code"] == 0 and not x["timed_out"] and x.get("grader_return_code") == 0
        and x.get("score") is not None for x in runs),
        "default_pairs": comparisons, "pass8": cap8_comparison}
    (OUT / "comparison.json").write_text(json.dumps(report, indent=2) + "\n",
                                         encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
