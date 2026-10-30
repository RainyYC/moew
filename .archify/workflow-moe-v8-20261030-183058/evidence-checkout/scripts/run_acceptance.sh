#!/usr/bin/env bash
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mode="${1:-run_latest}"
borrow="${2:-ac}"
diff="${3:-auto}"
case_filter="${4:-}"
scale="${5:-auto}"
solver="$ROOT/build/solver"
cases="$ROOT/data/official/Problem/cases"
grader="$ROOT/data/official/Problem/grader.py"
outdir="$ROOT/results/$mode"
mkdir -p "$outdir"
summary="$outdir/summary.tsv"
printf 'case\texit\twall_seconds\tchecker_time\n' > "$summary"
failed=0
matched=0
for input in "$cases"/*.txt; do
  name="$(basename "$input" .txt)"
  if [[ -n "$case_filter" && ! "$name" =~ $case_filter ]]; then continue; fi
  matched=$((matched+1))
  output="$outdir/$name.out"
  err="$outdir/$name.stderr"
  start=$(date +%s%N)
  if [ "$mode" = baseline ]; then
    timeout 10 "$solver" --baseline --borrow="$borrow" --diff="$diff" --scale="$scale" < "$input" > "$output" 2> "$err"
  else
    timeout 10 "$solver" --borrow="$borrow" --diff="$diff" --scale="$scale" < "$input" > "$output" 2> "$err"
  fi
  rc=$?
  end=$(date +%s%N)
  sec=$(awk -v a="$start" -v b="$end" 'BEGIN{printf "%.3f",(b-a)/1000000000}')
  tim=""
  if [ "$rc" -eq 0 ]; then
    tim=$(python3 "$grader" "$input" "$output" 2> "$outdir/$name.checker.stderr")
    grc=$?
    if [ "$grc" -ne 0 ]; then rc=$((100+grc)); fi
  fi
  if [ "$rc" -ne 0 ]; then failed=1; fi
  printf '%s\t%s\t%s\t%s\n' "$name" "$rc" "$sec" "$tim" >> "$summary"
done
cat "$summary"
if [ "$matched" -eq 0 ]; then
  echo "error: case_filter matched no official cases: $case_filter" >&2
  exit 2
fi
exit "$failed"
