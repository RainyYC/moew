# Algorithm v5 solver

The current default adds bounded window tuning and repeated-load placement grouping to the frozen v5 solver. See [BORROW_REPORT.md](BORROW_REPORT.md) for the experiment details and [SOLUTION_REPORT.md](SOLUTION_REPORT.md) for the frozen v5 design.

## Build and run

```sh
./build.sh
./solver < input.txt > output.txt
```

The default solver mode is `--borrow=ac`. Use `--borrow=none` to reproduce the frozen v5 result; `windows`, `placement`, `boost`, `boost_grid`, and `all` expose the individual experiments. `--baseline` selects the serial feasibility schedule.

Run the full official acceptance set with the default solver mode:

```sh
./run_acceptance.sh
```

This calls the official grader for all 50 files in `../data/official/Problem/cases`, enforces a 10-second process limit per case, and writes outputs plus a TSV summary to `results/borrow_v6_default/`. Pass a different first argument to `run_acceptance.sh` to choose another result directory; the optional second argument selects a borrow mode.

## Latest default result

The final default run passed 50/50 cases with the official grader. Solver wall time was 0.021–3.521 seconds per case, including output writing and excluding grader time. Official `Time` ranged from 1,792,964 to 106,581,594. Against the frozen v5 snapshot (`borrow_v6/base/summary.tsv`), mean Time fell from 20,621,198.36 to 20,614,692.44; 12 cases improved, 38 tied, and none regressed. The geometric-mean improvement was 1.00096×. No official optimum is known; this is a comparison with the frozen solver snapshot.

The main new gains are x17 window tuning (6,055,940 → 6,010,628), x20 window tuning (2,443,667 → 2,407,088), and r256_v8_c8a grouped placement (29,258,410 → 29,243,050).

## Implementation notes

Time, duration, MAP load, and DP arithmetic use signed `__int128`. Every memory-feasible P receives a full-microbatch max-feasible-V scheduling probe; the best candidates then receive the existing bounded priority, window, buffer, mirror, and cut search. A borrow candidate replaces the v5 incumbent only when its actual scheduled Time is strictly lower.

Fine-window tuning scans W=1..min(nmb,64) on the probe and final v5 layouts when nmb≤64; larger cases use a fixed neighborhood. Grouped placement applies only to layers with at most four distinct loads and supported P/capacity bounds; unsupported cases retain their original MAP. Forward-fill mode 3 remains experimental because its targeted grid produced no whole-case improvement.

Search uses a fixed candidate set and has no internal seven-second deadline. The acceptance runner applies the official 10-second per-case limit; the latest full run stayed below it.
