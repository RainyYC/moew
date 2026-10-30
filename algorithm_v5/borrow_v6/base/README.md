# Algorithm v5 solver

Chinese solution report: [SOLUTION_REPORT.md](SOLUTION_REPORT.md). Per-case comparison with historical algorithms: [results/comparison_history.tsv](results/comparison_history.tsv).

Build with `./build.sh`; run a single instance as `./solver < input.txt > output.txt`.

`./run_acceptance.sh final` runs every official input under `../data/official/Problem/cases` with a 10-second process limit and checks each result using the supplied official grader. Inputs are retained in the original cases directory; solver outputs, stderr, checker stderr, and a TSV summary are retained under `results/final/`. The first serial-only pass is retained under `results/baseline/`.

The solver uses exact `__int128` arithmetic for durations, scheduling, and output timestamps. It searches legal `(V,P)` choices, uses a memory-constrained continuous partition DP, balances experts subject to exactly `E/P` experts per rank, and improves explicit-load MAPs with capacity-preserving pair swaps. Every memory-feasible P gets a full-microbatch max-feasible-V event-scheduling probe; the fastest two P values then receive richer priority, window, buffer, mirror, and cut-perturbation search. The event scheduler has three deterministic priority modes. `./solver --baseline` retains a simple full-forward-then-full-backward serial schedule for comparison.

Input contract confirmed from the problem statement and official checker: three fixed header lines followed by exactly `L` layer rows. Rows contain `T_l` alone or `T_l` and `E` expert loads. Shared expert duration follows the official checker as `T_l * F_s`.

The solver does not exhaustively enumerate every possible mirror depth or optimize all `2V` cuts; it tests a bounded set of mirror group counts and a few one-layer boundary moves. The DP estimates per-layer GEMM with `ceil(T/P)` before explicit MAP construction; the final operation durations use the selected MAP's actual slowest-rank load. The reported acceptance uses the official grader supplied with this fixed 50-case dataset.

Final acceptance (`./build.sh && ./run_acceptance.sh final`): 50/50 accepted by the official grader; solver wall time was 0.018–2.577 seconds per case, including output writing and excluding checker time. `Time` ranged from 1,792,964 to 106,581,594. Against the retained serial baseline, geometric-mean speedup was 15.30x, median 16.02x, min 4.25x, and max 32.87x; 50 cases improved, 0 tied, 0 regressed. Compared with the previous all-P-pruned snapshot in `results/pre_grid_fix/`, 21 cases improved, 29 tied, and none regressed (geometric-mean improvement 1.177x). There is no official optimum reference, so these comparisons are against solver snapshots only.

Search uses a fixed, bounded candidate set per input, including one mandatory full-microbatch probe for every memory-feasible P; there is no internal 7-second cutoff or adaptive deadline check. The acceptance runner enforces the required 10-second process limit, and every final run stayed below it.
