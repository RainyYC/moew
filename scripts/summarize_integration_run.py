#!/usr/bin/env python3
"""Join existing full-50 integration timings with saved comparison tables.

This script only reads its input artifacts. It does not invoke the solver, grader,
or official runner.
"""
from __future__ import annotations

import csv
import json
import re
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUN_TXT = ROOT / "results/optimization_integration/full50/official-run-all.txt"
CHECKER_TSV = ROOT / "results/design_patterns/full50/summary.tsv"
OFFLINE_20327_TSV = ROOT / "results/optimization_integration/offline_20327.tsv"
OFFLINE_20224_TSV = ROOT / "results/optimization_integration/offline_20224.tsv"
OFFICIAL_REPORT = ROOT / "data/official/Problem/report_python.txt"
OUT_DIR = ROOT / "results/optimization_integration/full50"
SUMMARY_TSV = OUT_DIR / "summary.tsv"
VALIDATION_JSON = OUT_DIR / "validation.json"
EXPECTED_CASES = 50

RUN_ROW = re.compile(
    r"^\s*(?P<file>[^\s]+\.txt)\s+(?P<status>OK|TO|ERROR|INVALID)\s+"
    r"(?P<time>-?\d+|-)\s+(?P<cpu>[\d.]+|-)\s+(?P<wall>[\d.]+|-)\s*$"
)
SUMMARY_OK = re.compile(r"\bsummary:\s*OK=(\d+)\b")


def parse_runner_line(line: str) -> dict[str, Any] | None:
    """Parse one official-runner row, preserving statuses and optional metrics."""
    match = RUN_ROW.match(line)
    if not match:
        return None

    def optional_int(value: str) -> int | None:
        return None if value == "-" else int(value)

    def optional_float(value: str) -> float | None:
        return None if value == "-" else float(value)

    case = Path(match.group("file")).stem
    return {
        "case": case,
        "status": match.group("status"),
        "Time": optional_int(match.group("time")),
        "cpu_seconds": optional_float(match.group("cpu")),
        "wall_seconds": optional_float(match.group("wall")),
    }


def read_tsv(path: Path, required: set[str]) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        fields = set(reader.fieldnames or [])
        missing = required - fields
        if missing:
            raise ValueError(f"{path}: missing columns {sorted(missing)}")
        rows: dict[str, dict[str, str]] = {}
        for row in reader:
            case = (row.get("case") or "").strip()
            if not case:
                continue
            if case in rows:
                raise ValueError(f"{path}: duplicate case {case}")
            rows[case] = row
    return rows


def read_runner(path: Path) -> tuple[dict[str, dict[str, Any]], int | None]:
    rows: dict[str, dict[str, Any]] = {}
    summary_ok: int | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        row = parse_runner_line(line)
        if row is not None:
            case = row["case"]
            if case in rows:
                raise ValueError(f"{path}: duplicate case {case}")
            rows[case] = row
        count = SUMMARY_OK.search(line)
        if count:
            summary_ok = int(count.group(1))
    return rows, summary_ok


def read_numeric_map(rows: dict[str, dict[str, str]], column: str, label: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for case, row in rows.items():
        value = (row.get(column) or "").strip()
        if not value:
            raise ValueError(f"{label}: missing {column} for {case}")
        result[case] = int(value)
    return result


def counts_against(current: dict[str, int], comparison: dict[str, int]) -> dict[str, Any]:
    drops = {case: comparison[case] - value for case, value in current.items()}
    improved = sum(drop > 0 for drop in drops.values())
    tied = sum(drop == 0 for drop in drops.values())
    regressed = sum(drop < 0 for drop in drops.values())
    return {
        "comparison_mean_Time": sum(comparison.values()) / len(comparison),
        "total_drop": sum(drops.values()),
        "improved": improved,
        "tied": tied,
        "regressed": regressed,
        "mean_case_drop": statistics.mean(drops.values()),
        "max_case_drop": max(drops.values()),
        "min_case_drop": min(drops.values()),
    }


def main() -> int:
    run_rows, runner_summary_ok = read_runner(RUN_TXT)
    checker_rows = read_tsv(CHECKER_TSV, {"case", "checker_time"})
    offline_20327_rows = read_tsv(OFFLINE_20327_TSV, {"case", "best_Time"})
    offline_20224_rows = read_tsv(OFFLINE_20224_TSV, {"case", "best_Time"})
    official_rows, official_summary_ok = read_runner(OFFICIAL_REPORT)

    sources = {
        "official-run-all": set(run_rows),
        "design-patterns checker": set(checker_rows),
        "offline_20327": set(offline_20327_rows),
        "offline_20224": set(offline_20224_rows),
        "official report": set(official_rows),
    }
    all_cases = set.union(*sources.values()) if sources else set()
    mismatches = {
        name: {"missing": sorted(all_cases - cases), "extra": sorted(cases - all_cases)}
        for name, cases in sources.items()
        if cases != all_cases
    }
    case_names = sorted(all_cases)
    checker_time = read_numeric_map(checker_rows, "checker_time", "checker summary")
    offline_20327 = read_numeric_map(offline_20327_rows, "best_Time", "offline_20327")
    offline_20224 = read_numeric_map(offline_20224_rows, "best_Time", "offline_20224")
    official_time = {case: row["Time"] for case, row in official_rows.items()}

    case_rows: list[dict[str, Any]] = []
    for case in case_names:
        run = run_rows.get(case, {})
        time = run.get("Time")
        checker = checker_time.get(case)
        old_20327 = offline_20327.get(case)
        old_20224 = offline_20224.get(case)
        official = official_time.get(case)
        case_rows.append(
            {
                "case": case,
                "status": run.get("status", "MISSING"),
                "Time": time,
                "cpu_seconds": run.get("cpu_seconds"),
                "wall_seconds": run.get("wall_seconds"),
                "checker_time": checker,
                "online_baseline_Time": checker,
                "delta_vs_online_baseline": time - checker if time is not None and checker is not None else None,
                "delta_vs_checker": time - checker if time is not None and checker is not None else None,
                "offline_20327_best_Time": old_20327,
                "drop_vs_offline_20327": old_20327 - time if time is not None and old_20327 is not None else None,
                "offline_20224_best_Time": old_20224,
                "drop_vs_offline_20224": old_20224 - time if time is not None and old_20224 is not None else None,
                "official_Time": official,
                "official_drop": official - time if time is not None and official is not None else None,
                "official_drop_pct":
                    100.0 * (official - time) / official
                    if time is not None and official is not None and official > 0
                    else None,
            }
        )

    complete = len(case_rows) == EXPECTED_CASES and all(
        row["Time"] is not None
        and row["checker_time"] is not None
        and row["offline_20327_best_Time"] is not None
        and row["offline_20224_best_Time"] is not None
        and row["official_Time"] is not None
        for row in case_rows
    )
    all_ok = complete and all(row["status"] == "OK" for row in case_rows)
    success = all_ok and runner_summary_ok == EXPECTED_CASES
    official_report_all_ok = len(official_rows) == EXPECTED_CASES and all(
        row["status"] == "OK" and row["Time"] is not None for row in official_rows.values()
    )

    times = [row["Time"] for row in case_rows if row["Time"] is not None]
    cpu = [row["cpu_seconds"] for row in case_rows if row["cpu_seconds"] is not None]
    wall = [row["wall_seconds"] for row in case_rows if row["wall_seconds"] is not None]
    official_drops = [row["official_drop"] for row in case_rows if row["official_drop"] is not None]
    official_drop_pcts = [row["official_drop_pct"] for row in case_rows if row["official_drop_pct"] is not None]
    official_times = [value for value in official_time.values() if value is not None]
    current_by_case = {row["case"]: row["Time"] for row in case_rows if row["Time"] is not None}
    status_counts = Counter(row["status"] for row in case_rows)
    status_counts.setdefault("OK", 0)
    status_counts.setdefault("TO", 0)
    status_counts.setdefault("ERROR", 0)
    status_counts.setdefault("INVALID", 0)
    status_counts.setdefault("MISSING", 0)

    aggregates: dict[str, Any] = {
        "case_count": len(case_rows),
        "status_counts": dict(sorted(status_counts.items())),
        "Time_sum": sum(times),
        "Time_mean": statistics.mean(times) if times else None,
        "Time_min": min(times) if times else None,
        "Time_max": max(times) if times else None,
        "Time_median": statistics.median(times) if times else None,
        "mean_cpu_seconds": statistics.mean(cpu) if cpu else None,
        "mean_wall_seconds": statistics.mean(wall) if wall else None,
        "max_wall_seconds": max(wall) if wall else None,
        "max_wall_cases": [row["case"] for row in case_rows if wall and row["wall_seconds"] == max(wall)],
        "official_Time_sum": sum(official_times),
        "official_Time_mean": statistics.mean(official_times) if official_times else None,
        "total_official_drop": sum(official_drops),
        "mean_official_drop": statistics.mean(official_drops) if official_drops else None,
        "mean_per_case_official_drop_pct": statistics.mean(official_drop_pcts) if official_drop_pcts else None,
        "official_mean_drop_pct":
            100.0 * sum(official_drops) / sum(official_times)
            if official_times and sum(official_times) > 0 and len(official_drops) == len(official_times)
            else None,
        "vs_offline_20327": counts_against(current_by_case, offline_20327)
        if set(current_by_case) == set(offline_20327) else None,
        "vs_offline_20224": counts_against(current_by_case, offline_20224)
        if set(current_by_case) == set(offline_20224) else None,
        "vs_online_baseline": counts_against(current_by_case, checker_time)
        if set(current_by_case) == set(checker_time) else None,
    }
    validation = {
        "success": success,
        "expected_cases": EXPECTED_CASES,
        "official_run_all_summary_OK": runner_summary_ok,
        "all_cases_OK": all_ok,
        "official_report_all_OK": official_report_all_ok,
        "official_report_summary_OK": official_summary_ok,
        "all_sources_case_sets_match": not mismatches,
        "case_set_mismatches": mismatches,
        "aggregate": aggregates,
        "sources": {
            "official_run_all": str(RUN_TXT.relative_to(ROOT)),
            "online_baseline": str(CHECKER_TSV.relative_to(ROOT)),
            "checker_summary": str(CHECKER_TSV.relative_to(ROOT)),
            "offline_20327": str(OFFLINE_20327_TSV.relative_to(ROOT)),
            "offline_20224": str(OFFLINE_20224_TSV.relative_to(ROOT)),
            "official_report": str(OFFICIAL_REPORT.relative_to(ROOT)),
        },
        "note": "Read-only summary; does not invoke solver, grader, or official runner.",
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fields = [
        "case", "status", "Time", "cpu_seconds", "wall_seconds", "online_baseline_Time",
        "delta_vs_online_baseline", "checker_time", "delta_vs_checker",
        "offline_20327_best_Time", "drop_vs_offline_20327", "offline_20224_best_Time",
        "drop_vs_offline_20224", "official_Time", "official_drop", "official_drop_pct",
    ]
    with SUMMARY_TSV.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(case_rows)
    VALIDATION_JSON.write_text(json.dumps(validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {SUMMARY_TSV.relative_to(ROOT)} and {VALIDATION_JSON.relative_to(ROOT)}")
    print(f"cases={len(case_rows)} all_OK={all_ok} runner_summary_OK={runner_summary_ok} success={success}")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
