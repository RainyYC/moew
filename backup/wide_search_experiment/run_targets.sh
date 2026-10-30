#!/usr/bin/env bash
set -uo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
out="$root/backup/wide_search_experiment/results"
summary="$out/targeted.tsv"
printf 'case\texit\twall_seconds\tbase_time\tchecker_time\textra_pv\n' > "$summary"
cases=(x04_lr_inter_p5 x10_lr_tight_p8 x11_lr_deep_p3 x12_lr_close_p10 x16_vl_trap4_ramp x17_vl_tight_block x18_vl_tight_small r24_p3_flat r20_p2_flat)
for name in "${cases[@]}"; do
  input="$root/data/official/Problem/cases/$name.txt"
  output="$out/$name.out"
  err="$out/$name.stderr"
  start=$(date +%s%N)
  timeout 10s "$root/backup/wide_search_experiment/solver" --extra-p=4 --extra-v=3 < "$input" > "$output" 2> "$err"
  rc=$?
  end=$(date +%s%N)
  wall=$(awk -v a="$start" -v b="$end" 'BEGIN{printf "%.3f",(b-a)/1000000000}')
  checker=""
  if [ "$rc" -eq 0 ]; then
    checker=$(python3 "$root/data/official/Problem/grader.py" "$input" "$output" 2> "$out/$name.checker.stderr")
    grc=$?
    if [ "$grc" -ne 0 ]; then rc=$((100+grc)); fi
  fi
  base=$(awk -F '\t' -v n="$name" '$1==n{print $4}' "$root/results/refactor_v8/summary.tsv")
  extra=$(awk '/^EXTRA_PV /{line=$0} END{print line}' "$err")
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$name" "$rc" "$wall" "${base:-NA}" "$checker" "${extra:-NO_EXTRA_LOG}" >> "$summary"
  if [ "$rc" -eq 124 ]; then
    printf 'timeout after %ss at %s; stopping remaining cases\n' 10 "$name" >&2
    break
  fi
  if [ "$rc" -ne 0 ]; then
    printf 'failure at %s (exit %s); stopping remaining cases\n' "$name" "$rc" >&2
    break
  fi
done
cat "$summary"
