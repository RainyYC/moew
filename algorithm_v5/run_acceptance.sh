#!/usr/bin/env bash
set -u
cd "$(dirname "$0")"
mode="${1:-borrow_v6_default}"
borrow="${2:-ac}"
outdir="results/$mode"
mkdir -p "$outdir"
summary="$outdir/summary.tsv"
printf 'case\texit\tseconds\tchecker_time\n' > "$summary"
for input in ../data/official/Problem/cases/*.txt; do
  name="$(basename "$input" .txt)"
  output="$outdir/$name.out"
  err="$outdir/$name.stderr"
  start=$(date +%s%N)
  if [ "$mode" = baseline ]; then
    timeout 10 ./solver --baseline --borrow="$borrow" < "$input" > "$output" 2> "$err"
  else
    timeout 10 ./solver --borrow="$borrow" < "$input" > "$output" 2> "$err"
  fi
  rc=$?
  end=$(date +%s%N)
  sec=$(awk -v a="$start" -v b="$end" 'BEGIN{printf "%.3f",(b-a)/1000000000}')
  tim=""
  if [ "$rc" -eq 0 ]; then
    tim=$(python3 ../data/official/Problem/grader.py "$input" "$output" 2> "$outdir/$name.checker.stderr")
    grc=$?
    if [ "$grc" -ne 0 ]; then rc=$((100+grc)); fi
  fi
  printf '%s\t%s\t%s\t%s\n' "$name" "$rc" "$sec" "$tim" >> "$summary"
done
cat "$summary"
