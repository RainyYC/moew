# Wide P/V search experiment

This directory is an isolated experiment copy of the refactored single-file v8 solver. It does not change `src/solver.cpp`, the README, or frozen v8 materials.

## Interface

- `--extra-p=K` selects up to K partitions in the original `probe_time` order. Default: `0` (disabled).
- `--extra-v=V` evaluates up to V feasible, lowest-score V layouts per selected P. Default: `0` (disabled).
- Use `--extra-p=4 --extra-v=3` for the current experiment setting. Both values must be positive. `--baseline` suppresses this stage.
- The added phase starts only after the complete existing v8 path, including v7, scale/wave and local polishing, and shares the original `main_start + 9s` deadline. It reuses each P's MAP, rebuilds its feasible V cuts DP, evaluates each new layout with rich scheduling, and gives the first newly evaluated V for each P deep mirror/cut evaluation. It retains the two best event-evaluated new layouts for compact-wave checks when the deadline allows.
- The P-level resource lower bound is layout-independent. It can prune a P only when it cannot beat the current incumbent; there is no fixed-cut lower-bound pruning.
- `--scale=off` leaves the explicit extra event evaluation enabled, while disabling compact-wave follow-up through the existing `do_wave` switch. With no `--extra-p`/`--extra-v`, the added phase returns immediately.

Each enabled run prints one `EXTRA_PV` line with requested and actual P/V counts, P/V lists, pruning counts, old/new Time, wave attempts, and extra wall time. Compact-wave follow-ups use the same extracted `run_compact_wave_anchor` helper as the existing v8 phase.

## Targeted run

`results/targeted.tsv` records the requested 9-case set (`x04`, `x10`, `x11`, `x12`, `x16`, `x17`, `x18`, `r24_p3_flat`, `r20_p2_flat`) using a 10-second timeout and the official grader. No solver benchmarks are part of compilation.

The final fixed-version 50-case experiment and limitations are documented in [`REPORT.md`](REPORT.md); only `results/final_full50/summary.tsv` supports its conclusion. Earlier pilot logs remain separate and are not included.
