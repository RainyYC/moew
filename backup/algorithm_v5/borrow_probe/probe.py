#!/usr/bin/env python3
"""Bounded diagnostic: left-shift final schedules while preserving engine order."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from solver.casein import parse_case  # noqa: E402
from solver import formula, sched  # noqa: E402

OUTDIR = ROOT / "algorithm_v5" / "borrow_probe"
OUTDIR.mkdir(parents=True, exist_ok=True)
CASES = sorted(p.stem for p in (ROOT / "algorithm_v5/results/final").glob("*.out"))


def parse_output(case, text):
    rows = [line.split() for line in text.splitlines() if line.strip()]
    V, P = map(int, rows[0])
    assert rows[1][0] == "PSI" and rows[3][0] == "MAP"
    psi_row = list(map(int, rows[2]))
    K, psi = psi_row[0], psi_row[1:]
    map_rows = [list(map(int, rows[4 + l])) for l in range(case.L)]
    assert rows[4 + case.L][0] == "SCHEDULE"
    plan = formula.build_plan(case, V, P, 1, psi, map_rows)
    starts = [-1] * case.n_ops
    for parts in rows[5 + case.L:]:
        t = int(parts[0])
        for token in parts[1:]:
            mb, layer, opname = token.split(":")
            oi = formula.OP_INDEX[opname]
            idx = int(mb) * case.L * 10 + int(layer) * 10 + oi
            assert starts[idx] == -1, f"duplicate op {token}"
            starts[idx] = t
    assert all(t >= 0 for t in starts), f"missing {starts.count(-1)} operations"
    ends = []
    for idx, start in enumerate(starts):
        layer = (idx % (case.L * 10)) // 10
        op = idx % 10
        ends.append(start + plan.durations[layer][op])
    base_time = max(ends, default=0)
    return V, P, K, psi, map_rows, plan, starts, ends, base_time


def main():
    report = []
    for name in CASES:
        case = parse_case(ROOT / "data/official/Problem/cases" / f"{name}.txt")
        base_text = (ROOT / "algorithm_v5/results/final" / f"{name}.out").read_text()
        V, P, K, psi, map_rows, plan, starts, ends, base_time = parse_output(case, base_text)
        original = sched.Schedule(base_time, starts, ends, case.nmb, (True, False, False, False))
        seqs = sched.engine_sequences(case, plan, original)
        state = sched.evaluate_sequences(case, plan, seqs)
        if state is None:
            report.append({"case": name, "V": V, "P": P, "K": K, "before": base_time,
                           "after": None, "status": "cycle"})
            continue
        after, new_start, new_end = state
        candidate = sched.Schedule(after, new_start, new_end, case.nmb, original.variant)
        mem_ok, groups = sched.memory_usage(case, plan, new_start, new_end)
        record = {"case": name, "V": V, "P": P, "K": K, "before": base_time,
                  "after": after, "delta": after-base_time, "local_memory_ok": mem_ok,
                  "peak_act": [g.peak_act for g in groups],
                  "peak_comm": [g.peak_comm for g in groups], "official_legal": None}
        if after < base_time:
            outpath = OUTDIR / f"{name}.out"
            outpath.write_text(sched.render_output(case, plan, candidate, map_rows))
            record["candidate"] = str(outpath.relative_to(ROOT))
        report.append(record)
    (OUTDIR / "probe.json").write_text(json.dumps(report, indent=2) + "\n")
    for row in report:
        print(json.dumps(row, sort_keys=True))


if __name__ == "__main__":
    main()
