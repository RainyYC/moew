# Algorithm v5 solver

The default solver preserves the full v7 incumbent and enables the accepted scale v8 search automatically for `--borrow=ac --diff=auto`. Scale search adds a compact wave rank stage, a bounded alternate-P/layout search for small cases, and a fixed-layout local engine-order polish. Every stage keeps the incumbent unless it finds a lower Time.

## Build and run

```sh
./build.sh
./solver < input.txt > output.txt
```

`--scale=off` replays the v7 search. `--scale=on` explicitly enables the scale stages; `--scale=auto` enables them only with `borrow=ac` and `diff=auto`. `--borrow=none` and `--diff=off` retain their previous behavior. `--baseline` selects the serial feasibility schedule.

Run the official acceptance set:

```sh
./run_acceptance.sh
```

The runner takes five optional arguments in order: result directory, borrow mode, diff mode, case regular expression, and scale mode. The default run writes outputs and a TSV summary under `results/scale_v8_default/`. Use the fifth argument `off` to measure the v7 path.

## Accepted scale v8 results

All 50 official cases passed. Against v7, v8 improved 31 cases and tied 19, with no regressions. Mean Time fell from 20,589,370 to 20,407,224; geometric v7/v8 speedup was 1.01340×. Against old placement, 47 cases improved and 3 tied. The longest measured solver wall time was 8.811 seconds under the 10 second limit.

The full per-case comparison and frozen-bucket summaries are in [results/scale_v8_default](results/scale_v8_default/). The detailed methodology, lower-bound headroom, and bucket statistics are in [SCALE_REPORT.md](SCALE_REPORT.md).

Historical design and experiment notes remain available in [DIFF_REPORT.md](DIFF_REPORT.md), [BORROW_REPORT.md](BORROW_REPORT.md), and [SOLUTION_REPORT.md](SOLUTION_REPORT.md).

## Search notes

The v7 search keeps its original 8 second cutoff. Added scale work shares a 9 second process deadline, leaving time for output under the official 10 second limit. The extra-P branch is limited by `mb<=16`, `Nops<=8000`, and available time; it may change the mapping and cuts. The local engine search applies only to schedules with at most 8,000 operations and keeps the mapping and cuts fixed. Detailed rules and all 50 results are in the report.
