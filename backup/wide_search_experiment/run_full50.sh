#!/usr/bin/env bash
set -uo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
out="$root/backup/wide_search_experiment/results/final_full50"
mkdir -p "$out"
summary="$out/summary.tsv"
printf 'case\texit\twall_seconds\tbase_time\tchecker_time\textra_pv\n' > "$summary"
for input in "$root"/data/official/Problem/cases/*.txt; do
  name="$(basename "$input" .txt)"
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
  printf '%s exit=%s wall=%s base=%s checker=%s\n' "$name" "$rc" "$wall" "${base:-NA}" "$checker"
  if [ "$rc" -eq 124 ]; then
    printf 'timeout after %ss at %s; stopping final suite\n' 10 "$name" >&2
    exit 124
  fi
  if [ "$rc" -ne 0 ]; then
    printf 'failure at %s (exit %s); stopping final suite\n' "$name" "$rc" >&2
    exit "$rc"
  fi
done
