# Search neighborhood pilots

These are four-case pilots against the current `results/budget_search/full50/summary.tsv` baseline. All four candidates passed validation on all four sampled cases, with no timeouts. This is a narrow diagnostic sample; it does not establish a full-set improvement or justify promotion.

## Results

Positive improvement means the candidate reduced checker time. Times are in the solver's time units.

| Pilot | Mode | Valid | Improved / tied / regressed | Mean checker time | Mean baseline time | Mean absolute improvement | Mean point-relative improvement |
|---|---|---:|---:|---:|---:|---:|---:|
| A | multi-critical | 4/4 | 1 / 2 / 1 | 16,648,629.75 | 16,648,276.75 | -353.00 | +0.0358% |
| A | hybrid | 4/4 | 1 / 2 / 1 | 16,660,914.25 | 16,648,276.75 | -12,637.50 | -0.0116% |
| B | joint-resource | 4/4 | 1 / 2 / 1 | 16,661,126.75 | 16,648,276.75 | -12,850.00 | -0.0423% |
| C | escape search | 4/4 | 1 / 3 / 0 | 16,645,091.25 | 16,648,276.75 | +3,185.50 | +0.0169% |

| Case | Baseline | A multi | A hybrid | B joint | C escape |
|---|---:|---:|---:|---:|---:|
| `r16_p4_trap` | 17,319,480 | 17,319,480 | 17,319,480 | 17,319,480 | 17,319,480 |
| `x01_lr_block_p2` | 2,390,000 | 2,390,000 | 2,390,000 | 2,390,000 | 2,390,000 |
| `x10_lr_tight_p8` | 18,903,491 | 18,817,144 | 18,825,305 | 18,895,011 | 18,890,749 |
| `x12_lr_close_p10` | 27,980,136 | 28,067,895 | 28,108,872 | 28,040,016 | 27,980,136 |

The A and B pilots each improved `x10_lr_tight_p8` but regressed `x12_lr_close_p10`. C reduced `x10_lr_tight_p8` by 12,742 (0.0674%) and tied the baseline on the other three cases. The per-case validation summaries and solver logs are in `multi_pilot/`, `hybrid_pilot/`, `joint_pilot/`, and `escape_pilot/`.

## C static review

- Escape perturbation is opt-in at the `polish` call site and is never enabled by the prefix or variant-zero call. The command-line default is `--escape-mode=on`; `--escape-mode=off` disables episodes.
- Episodes trigger after 16 consecutive normal extension passes without a strict makespan improvement. Each episode runs three deterministic passes; its variant sequence is separate from the normal pass counter.
- The perturbation changes one resource sequence by one or two deterministic swaps. Its candidate goes through the full DAG retimer and memory legality check. Only this candidate may use the bounded `global_time * 1003 / 1000` time cap; regular candidates retain the original strict `(Time, sum_end)` acceptance rule.
- Exploration uses a working copy. Global state changes only when `(Time, sum_end)` improves lexicographically, so an episode cannot replace the global schedule with a worse one. The `escape_global_improvements` log counter can include equal-Time, lower-`sum_end` updates; it must not be reported as a count of Time reductions.
- Pilot logs show escape attempts on `r16_p4_trap`, `x01_lr_block_p2`, and `x10_lr_tight_p8`; `x12_lr_close_p10` reached its best result through normal passes and made zero escape attempts. That result is evidence the stagnation trigger stayed dormant while normal passes continued improving, not evidence that escape episodes improve that case.

No pilot establishes a reliable full-set gain. Keep these as experiments and evaluate on the complete benchmark set before considering broader use.
