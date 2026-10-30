#!/usr/bin/env python3
"""Validate paired behavior and CPU cost of two solver binaries."""

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import statistics
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = ROOT / "data/official/Problem/cases"
GRADER = ROOT / "data/official/Problem/grader.py"
TARGETS = [
    "r128_v4_c4a",
    "r16_p4_trap",
    "x01_lr_block_p2",
    "x10_lr_tight_p8",
    "x12_lr_close_p10",
    "x20_vl_flat_control",
]
ENGINE_RE = re.compile(r"LOCAL_ENGINE\s+([^\r\n]+)")
TIME_FIELDS = {
    "extension_seconds",
    "main_seconds",
    "elapsed_seconds",
    "elapsed_ms",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def engine_records(path: Path) -> list[dict[str, str]]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    return [dict(re.findall(r"([A-Za-z_]+)=([^\s]+)", match))
            for match in ENGINE_RE.findall(raw)]


def stable_engine_records(records: list[dict[str, str]]) -> list[dict[str, str]]:
    """Remove only timing-valued LOCAL_ENGINE fields, retaining counters/order."""
    return [
        {key: value for key, value in record.items() if key not in TIME_FIELDS}
        for record in records
    ]


def child_cpu(usage) -> float:
    return usage.ru_utime + usage.ru_stime


def run_solver(tag: str, binary: Path, binary_sha: str, case: Path,
               pass_limit: int, order: int, out_dir: Path) -> dict:
    stem = f"{order:02d}_{tag}_{case.stem}_pass{pass_limit}"
    stdout_path = out_dir / f"{stem}.out"
    stderr_path = out_dir / f"{stem}.stderr"
    argv = [str(binary), f"--polish-pass-limit={pass_limit}", str(case)]
    started = time.monotonic()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=stdout,
                                stderr=stderr, start_new_session=True)
        timed_out = False
        try:
            try:
                return_code = proc.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                return_code = proc.wait()
        finally:
            # Keep stdin open until the solver exits, matching the official runner.
            if proc.stdin is not None:
                proc.stdin.close()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {
        "order": order,
        "tag": tag,
        "binary": str(binary),
        "binary_sha256": binary_sha,
        "case": case.stem,
        "polish_pass_limit": pass_limit,
        "argv": argv,
        "return_code": return_code,
        "timed_out": timed_out,
        "wall_seconds": time.monotonic() - started,
        "solver_child_cpu_seconds": child_cpu(after) - child_cpu(before),
        "stdout": stdout_path.name,
        "stderr": stderr_path.name,
        "stdout_sha256": sha256(stdout_path),
        "stderr_sha256": sha256(stderr_path),
        "local_engine_counts": engine_records(stderr_path),
        "grader_return_code": None,
        "score": None,
    }
    checker_stdout = out_dir / f"{stem}.checker.stdout"
    checker_stderr = out_dir / f"{stem}.checker.stderr"
    try:
        check = subprocess.run(
            [sys.executable, str(GRADER), str(case), str(stdout_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=10.0, check=False)
        checker_stdout.write_bytes(check.stdout)
        checker_stderr.write_bytes(check.stderr)
        match = re.fullmatch(rb"\s*(\d+)\s*", check.stdout)
        result.update({
            "grader_return_code": check.returncode,
            "grader_stdout": checker_stdout.name,
            "grader_stderr": checker_stderr.name,
            "score": int(match.group(1)) if check.returncode == 0 and match else None,
        })
    except subprocess.TimeoutExpired as exc:
        checker_stdout.write_bytes(exc.stdout or b"")
        checker_stderr.write_bytes(exc.stderr or b"")
        result.update({
            "grader_timed_out": True,
            "grader_stdout": checker_stdout.name,
            "grader_stderr": checker_stderr.name,
        })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--polish-pass-limit", type=int, default=24)
    args = parser.parse_args()

    baseline = args.baseline.resolve()
    candidate = args.candidate.resolve()
    out_dir = args.output_dir.resolve()
    for binary in (baseline, candidate):
        if not binary.is_file():
            parser.error(f"binary does not exist: {binary}")
        if not os.access(binary, os.X_OK):
            parser.error(f"binary is not executable: {binary}")
    if not GRADER.is_file():
        parser.error(f"official grader does not exist: {GRADER}")
    cases = {name: CASES_DIR / f"{name}.txt" for name in TARGETS}
    for case in cases.values():
        if not case.is_file():
            parser.error(f"official case does not exist: {case}")
    if args.polish_pass_limit < 0:
        parser.error("--polish-pass-limit must be nonnegative")
    out_dir.mkdir(parents=True, exist_ok=True)

    binary_hashes = {"baseline": sha256(baseline), "candidate": sha256(candidate)}
    binaries = {"baseline": baseline, "candidate": candidate}
    runs = []
    order = 0
    # Two repetitions per case, with binary execution order reversed.
    for round_no, sequence in ((1, ("baseline", "candidate")),
                               (2, ("candidate", "baseline"))):
        for case_name in TARGETS:
            for tag in sequence:
                order += 1
                row = run_solver(tag, binaries[tag], binary_hashes[tag],
                                 cases[case_name], args.polish_pass_limit,
                                 order, out_dir)
                row["round"] = round_no
                runs.append(row)
                print(
                    f"run {order:02d}/24 round={round_no} tag={tag} case={case_name} "
                    f"rc={row['return_code']} timeout={row['timed_out']} "
                    f"cpu={row['solver_child_cpu_seconds']:.3f}s",
                    flush=True,
                )

    (out_dir / "runs.json").write_text(
        json.dumps(runs, indent=2) + "\n", encoding="utf-8")

    validations = []
    for case_name in TARGETS:
        for round_no in (1, 2):
            pair = [row for row in runs
                    if row["case"] == case_name and row["round"] == round_no]
            by_tag = {row["tag"]: row for row in pair}
            valid_runs = all(
                row["return_code"] == 0 and not row["timed_out"] and
                row["grader_return_code"] == 0 and row["score"] is not None
                for row in pair)
            stdout_equal = (len(by_tag) == 2 and
                            (out_dir / by_tag["baseline"]["stdout"]).read_bytes() ==
                            (out_dir / by_tag["candidate"]["stdout"]).read_bytes())
            baseline_stable = stable_engine_records(
                by_tag["baseline"]["local_engine_counts"]) if "baseline" in by_tag else None
            candidate_stable = stable_engine_records(
                by_tag["candidate"]["local_engine_counts"]) if "candidate" in by_tag else None
            engine_equal = baseline_stable == candidate_stable
            engine_records_present = (
                bool(by_tag.get("baseline", {}).get("local_engine_counts")) and
                bool(by_tag.get("candidate", {}).get("local_engine_counts")))
            validations.append({
                "case": case_name,
                "round": round_no,
                "baseline_order": by_tag.get("baseline", {}).get("order"),
                "candidate_order": by_tag.get("candidate", {}).get("order"),
                "all_runs_valid": valid_runs,
                "stdout_identical": stdout_equal,
                "local_engine_records_present": engine_records_present,
                "stable_local_engine_identical": engine_equal,
                "baseline_score": by_tag.get("baseline", {}).get("score"),
                "candidate_score": by_tag.get("candidate", {}).get("score"),
            })

    aggregates = {}
    for tag in ("baseline", "candidate"):
        tag_runs = [row for row in runs if row["tag"] == tag]
        scores = [row["score"] for row in tag_runs if row["score"] is not None]
        aggregates[tag] = {
            "mean_solver_child_cpu_seconds": statistics.mean(
                row["solver_child_cpu_seconds"] for row in tag_runs),
            "mean_score": statistics.mean(scores) if scores else None,
            "per_case": {
                case_name: {
                    "mean_solver_child_cpu_seconds": statistics.mean(
                        row["solver_child_cpu_seconds"] for row in tag_runs
                        if row["case"] == case_name),
                    "mean_score": (
                        statistics.mean(row["score"] for row in tag_runs
                                        if row["case"] == case_name and row["score"] is not None)
                        if any(row["case"] == case_name and row["score"] is not None
                               for row in tag_runs) else None),
                }
                for case_name in TARGETS
            },
        }
    all_runs_valid = all(
        row["return_code"] == 0 and not row["timed_out"] and
        row["grader_return_code"] == 0 and row["score"] is not None
        for row in runs)
    all_pairs_equal = all(
        row["stdout_identical"] and row["local_engine_records_present"] and
        row["stable_local_engine_identical"]
        for row in validations)
    report = {
        "baseline": str(baseline),
        "candidate": str(candidate),
        "binary_sha256": binary_hashes,
        "polish_pass_limit": args.polish_pass_limit,
        "case_order": TARGETS,
        "rounds": 2,
        "runs": len(runs),
        "all_runs_valid": all_runs_valid,
        "all_pairs_semantically_equal": all_pairs_equal,
        "pair_validations": validations,
        "aggregates": aggregates,
    }
    (out_dir / "validation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary_fields = [
        "order", "round", "tag", "case", "polish_pass_limit", "return_code",
        "timed_out", "grader_return_code", "score", "wall_seconds",
        "solver_child_cpu_seconds", "stdout_sha256", "stderr_sha256",
    ]
    with (out_dir / "summary.tsv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=summary_fields, delimiter="\t",
                                lineterminator="\n")
        writer.writeheader()
        for row in runs:
            formatted = dict(row)
            formatted["wall_seconds"] = f"{row['wall_seconds']:.6f}"
            formatted["solver_child_cpu_seconds"] = f"{row['solver_child_cpu_seconds']:.6f}"
            writer.writerow({field: formatted.get(field) for field in summary_fields})
    print(json.dumps(report, indent=2))
    return 0 if all_runs_valid and all_pairs_equal else 1


if __name__ == "__main__":
    raise SystemExit(main())
