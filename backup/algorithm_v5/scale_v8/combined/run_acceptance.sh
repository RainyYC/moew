#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
ROOT=$(cd ../../.. && pwd)
PKG="$ROOT/work-oracle-opt/data/official/Problem"
mode="${1:-scale_v8_default}"
borrow="${2:-ac}"
diff="${3:-auto}"
case_filter="${4:-}"
scale="${5:-auto}"
OUT="$ROOT/algorithm_v5/results/$mode"
mkdir -p "$OUT"
printf 'case\texit\twall_seconds\tv8_time\n' > "$OUT/summary.tsv"
for input in "$PKG"/cases/*.txt; do
  name=$(basename "$input" .txt)
  if [ -n "$case_filter" ] && [[ ! "$name" =~ $case_filter ]]; then continue; fi
  output="$OUT/$name.out"
  err="$OUT/$name.stderr"
  start=$(date +%s%N)
  set +e
  if [ "$mode" = baseline ]; then
    timeout 10 ./solver --baseline --borrow="$borrow" --diff="$diff" --scale="$scale" < "$input" > "$output" 2> "$err"
  else
    timeout 10 ./solver --borrow="$borrow" --diff="$diff" --scale="$scale" < "$input" > "$output" 2> "$err"
  fi
  rc=$?
  set -e
  end=$(date +%s%N)
  seconds=$(awk -v a="$start" -v b="$end" 'BEGIN{printf "%.3f",(b-a)/1000000000}')
  score=
  if [ "$rc" -eq 0 ]; then
    set +e
    score=$(python3 "$PKG/grader.py" "$input" "$output" 2> "$OUT/$name.checker.stderr")
    grc=$?
    set -e
    if [ "$grc" -ne 0 ]; then rc=$((100+grc)); fi
  fi
  printf '%s\t%s\t%s\t%s\n' "$name" "$rc" "$seconds" "$score" >> "$OUT/summary.tsv"
  printf '%s\t%s\t%s\t%s\n' "$name" "$rc" "$seconds" "$score"
done
