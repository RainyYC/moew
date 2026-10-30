# v7 scale profile

`profile_cases.py` reads the saved v7 `.out` files and timing table. It does not invoke a solver. It imports `data/official/Problem/grader.py` for the official instance, mapping, DAG, and duration definitions.

Outputs:

- `cases.tsv`: per-case parameters, saved time comparisons, official Python baseline, fixed-layout lower bounds, optimistic global lower bounds, DAG head/tail bounds, resource balance, and memory peak ratio.
- `global_p.tsv`: per-case/per-legal-P optimistic bound components and memory feasibility.
- `buckets.tsv`: old-placement improvement summaries for Time and operation-count buckets.

`fixed_LB` is the maximum of the single-microbatch DAG critical path, fixed-layout per-card-group C/N work, and the head/tail subset bound. The latter only sums positive-duration operations assigned to one shared engine in a group, and skips empty selected sets.

`global_LB` is deliberately optimistic: it enumerates legal `P`, uses `max(ceil(T/P), max expert load)` for a lower bound on per-rank GEMM load, and permits up to `min(L, R/P, 64)` groups. It includes total C/N work divided by that group count, the pigeonhole bound from at least `ceil(L/Gmax)` layers in one group, per-layer C/N work, DAG critical path, per-layer head/tail bounds, and a per-layer activation-memory area bound. The memory-area bound caps activations using only that layer's expert residency and one minimum communication buffer, then divides the `mb * (D_l + 1)` activation-area demand by this optimistic capacity. Its separate feasibility filter assumes only one activation per nonempty group and ignores communication buffers. Therefore it is a global lower bound, not a solved optimal layout. The script asserts `global_LB <= fixed_LB <= saved Time` and that the current-P bound is no larger than saved Time for every case.

The reported headroom `(Time - LB) / Time` is the largest reduction that a stronger schedule could still possibly achieve under that lower bound; it is not an expected gain.
