# Budget search experiment

The full 50 case comparison passed: 29 improved, 21 tied, 0 regressed, 0 failed, and 0 timed out. Mean `Time` fell from 20,407,224.34 to 20,368,250.60 (mean reduction 0.1909801125%; mean per case percentage improvement 0.2061092585%). Mean wall time was 9.22092663 s; maximum was 9.23372227 s.

Largest per case percentage improvements:

| Case | Improvement | Time reduction |
| --- | ---: | ---: |
| `x12_lr_close_p10` | 1.585091% | 450,654 |
| `x01_lr_block_p2` | 1.304922% | 31,600 |
| `x20_vl_flat_control` | 1.295910% | 29,216 |
| `x14_lr_twochunk_p15` | 0.749094% | 613,788 |
| `x10_lr_tight_p8` | 0.685918% | 130,558 |

The `r128_v4_c4a` score remained 22,702,165 while the solver ran for 9.230 s. The full comparison used `scripts/compare_budget_search.py` and the same official grader, `data/official/Problem/grader.py`, against `results/runner_input_fix/summary.tsv`. A separate `run_all.py` smoke check passed on three representative cases only. See `full50/command.json` for the full run and smoke commands, and `full50/summary.tsv` for all case comparisons.

Reproduce the full comparison after building with `scripts/build.sh`:

```sh
python3 scripts/compare_budget_search.py build/solver results/budget_search/recheck
```

The local `probe_a_partial/` directory is an interrupted exploratory run, not the final acceptance record.
