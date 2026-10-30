# Fixed-map layout cut study

## `r128_v8_c4`, P=16

The study starts with current `make_map(x, 16)` from `algorithm_v5/solver.cpp`, then applies the existing grouped-placement search independently to every layer. The cut enumerator uses the resulting exact per-layer durations and covers every legal `K=G` and `K=2G` folded layout for each `G <= min(L, R/P, 64)`, with every nonempty contiguous cut pattern.

All 15 layer maps have only 3 distinct expert-load values. The original `make_map` rank peaks are 228 for layers 0–6 and 274 for layers 7–14. Grouped placement finds feasible assignments at 200 and 240, exactly `ceil(T/16)` for those layers; this matches a valid per-layer lower bound, so the resulting peak is proven optimal. None of the searches reached the 250,000-node budget.

There are 18,100 legal `(G,K,cuts)` layouts. The necessary resident-memory check rejects 16,470; 1,630 pass it. For each feasible layout the study evaluates single-microbatch DAG critical path, per-group C/N work, per-group head/tail subset bound, and the per-group activation-area bound. The best full lower bound is 25,883,940 for `G=8`, `K=8`, cuts `2,4,6,8,10,12,14`:

| Bound | Time |
| --- | ---: |
| C/N resource work | 24,712,704 |
| DAG head/tail subset | 25,883,940 |
| Activation area | 1,470,900 |
| Single-microbatch critical path | 1,495,398 |
| Combined best-cut lower bound | 25,883,940 |

More strongly, the minimum of the pure C/N resource lower bound over every feasible cut layout is already 24,712,704. Since every layer's grouped map attains its arithmetic minimum for the expert-load peak, any other P=16 MAP can only increase C-engine work. Therefore every possible P=16 MAP and every legal folded cut layout has Time at least 24,712,704. This exceeds both saved v7 time (24,363,545) and current wave time (24,108,480). There is no need to run event/list/gapfill/wave for P=16 cuts.

`map_helper.cpp` invokes the existing C++ `make_map` directly. As a sanity check, its P=8 map matched every row of the saved v7 P=8 MAP for this case. `placement_helper.cpp` exercises the existing `grouped_placement::detail::Search` with the same type cap and node budget as `find_at_peak`, while exposing whether search exhausted its budget; `materialize()` produces the improved rows.

The earlier x16 report confused old-placement time with v7. Its saved v7 time is 4,073,166; comparing the P=16 global lower bound 3,869,184 gives 5.008% remaining theoretical headroom.

## Direct wave probes

The isolated wave solver was run with a forced P to compare actual schedules; it did not change the default solver or stored v7 results.

| Case / forced P | Selected layout | Saved v7 Time | Wave Time | Official grader |
| --- | --- | ---: | ---: | ---: |
| `x01_lr_block_p2`, P=1 | V=12, K=24 | 2,570,180 | 2,425,200 | 2,425,200 |
| `x16_vl_trap4_ramp`, P=16 | V=8, K=8 | 4,073,166 | 5,547,328 | 5,547,328 |

For x01, the forced P=1 schedule beats the all-P wave result of 2,473,530 by 48,330 (1.95%), and improves the saved v7 result by 144,980 (5.64%). P=16 did not help x16; its forced-P schedule is slower than the incumbent.

## `x16_vl_trap4_ramp`, P=16 cuts

The grouped-placement search left all 16 layer peaks at `make_map` values 258/310. Each layer has three expert-load types; the 6–7 binary-search checks per layer completed without hitting the 250,000-node budget. The minimum feasible P=16 folded-cut layout lower bound over 32,768 legal cut layouts is 4,461,504; 9,225 passed the necessary memory check and none had a bound below the saved v7 Time 4,073,166. The direct P=16 wave schedule was 5,547,328 and passed the official grader. This P is ruled out by the resource/head-tail lower bound for this case.

## `r128_v8_c4`, combined-P bound

The P=16 cut lower bound (25,883,940) is above the optimistic P=8 bound (24,081,174), so the combined lower bound across legal P remains 24,081,174. This leaves 1.159% below saved v7 Time 24,363,545 and 0.113% below the all-P wave Time 24,108,480.
