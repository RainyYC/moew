# Lower-bound and baseline audit

This audit reads the saved per-case profile, comparison history, and fixed-P16 layout result only. It does not invoke the solver or re-enumerate layouts.

## Bound safety

- Fixed and global head/tail bounds use the official grader DAG. A nonempty selected set contains operations whose DAG earliest start is at least `R` and whose tail after end is at least `Q`. In any legal schedule, all selected positive-duration operations for the same engine and card group lie in the interval `[R, Time-Q]`; the shared engine must serialize their total work. Empty selected sets are skipped, avoiding the invalid `R+Q` bound.
- The global rank-load estimate `max(ceil(T/P), max expert load)` is a lower bound on the actual maximum load of any rank. All operation durations are monotone in this load, so computing the DAG and resource bounds from these optimistic durations remains safe.
- `Gmax=min(L,R/P,64)` is an upper bound on legal groups. Total work divided by `Gmax`, per-layer work, and the `ceil(L/Gmax)` pigeonhole work bound are all optimistic lower bounds.
- The memory feasibility filter counts one activation per nonempty group and ignores communication buffers; this only overestimates feasible capacity. The activation-area bound uses a single layer's expert residency plus the minimum required communication buffer, so its activation capacity is also optimistic. The interval contains at least `D_l+1` integer points per microbatch, while its end is bounded by the DAG tail after `s_bwd`; dividing total activation area by the optimistic capacity gives a safe makespan lower bound.
- The saved per-case assertion `global_LB <= fixed_LB <= Time` passed for all 50 cases, and current-P lower bounds are also no larger than their saved Times. The refined r128 P=16 bound comes from exhaustive legal cut enumeration under componentwise optimal per-layer expert maps; the combined-P bound remains the minimum across P.

## Baseline and maximum possible improvement

`old_placement_time` matches `results/comparison_history.tsv`'s `placement_fillboost_time` for all 50 cases. Actual old-to-v7 reduction is `(old_placement_time - v7 Time) / old_placement_time`.

Theoretical maximum improvement against the old placement baseline is `(old_placement_time - global_LB) / old_placement_time`. With the original global bounds, the requested counts are confirmed: 21/50 at most 5%, 13/50 at most 2%, and 8/50 at most 1%. The actual old-to-v7 reductions have different counts: 27/50, 19/50, and 13/50 at those thresholds.

After replacing r128 P=16's 21,376,608 optimistic P bound with the exhaustive cut lower bound 25,883,940, r128's combined global bound becomes P=8's 24,081,174. The refined maximum-improvement counts therefore become 22/50 at most 5%, 14/50 at most 2%, and 8/50 at most 1%. The r128 case moves into the <=2% bucket; other cases are unchanged.

## Time buckets

These are based on the saved v7 `Time` field. Mean/median/worst report actual old-to-v7 reduction; theoretical gain columns use the refined global lower bound and the old placement denominator.

| Time bucket | n | Actual reduction mean / median / worst | Geometric old/v7 speedup | Max possible gain vs old, mean / median / worst | Max gain vs old <=5% / <=2% / <=1% |
| --- | ---: | ---: | ---: | ---: | ---: |
| <5M | 8 | 5.64% / 2.67% / 0.00% | 1.062x | 11.66% / 8.06% / 1.25% | 3 / 2 / 0 |
| 5–10M | 11 | 4.15% / 1.26% / 0.00% | 1.045x | 10.38% / 3.17% / 0.34% | 7 / 3 / 2 |
| 10–30M | 22 | 8.49% / 9.46% / 0.00% | 1.095x | 22.08% / 28.47% / 0.36% | 5 / 3 / 2 |
| >=30M | 9 | 2.61% / 1.65% / 0.00% | 1.028x | 5.72% / 1.74% / 0.14% | 7 / 6 / 4 |
