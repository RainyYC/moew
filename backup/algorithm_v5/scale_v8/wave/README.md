# Wave rank experiment

This is an isolated copy of the current `algorithm_v5/solver.cpp` v7 solver and its headers. The default solver is unchanged. Build with `./build.sh`; pass `--wave` to run the extra wave rank sweep after the existing v7 schedule search.

The sweep keeps the v7 result as incumbent, checks memory peaks before accepting a schedule, and only replaces it when the actual makespan is lower. It reads the case from stdin and emits a normal standalone answer on stdout. `results/summary.tsv` records selected official-case improvements, including checker status and the winning rank parameters.

The compact sweep tries nine full-window ranks: three duration pitches (1/4, 1/2, and 1 times the busiest engine work for one mb) with a single-mb earliest-start or earliest-finish head; the discrete `(2*mb + forward/reverse layer)` rank; and shortest/longest DW duration tie orders for the 1/2-pitch earliest-finish rank. It then tries `{G, 2G, mb/2}` on the best two full-window ranks. Earliest-start and earliest-finish values come from the original per-mb DAG with no engine contention. The summary's `ES` and `EFT` labels refer to these distinct DAG values.
