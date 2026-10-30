# Refactor v8 validation

Official serial acceptance passed all 50 cases. Every `Time` and every output file matches `results/scale_v8_default/` case by case. Mean `Time` is 20,407,224.34. The largest recorded wall time is 9.008 seconds for `r256_v8_c4`, below the 10-second limit.

During recovery after interruption, `x17_vl_tight_block`, `x19_vl_trap4_fs4`, and `x20_vl_flat_control` were briefly rerun while the original runner was still finishing. `summary.tsv` retains the first runner record for each case. Wall times are therefore used only to check the 10-second constraint, not as a strict isolated performance comparison. No solver rerun was needed for this comparison record.
