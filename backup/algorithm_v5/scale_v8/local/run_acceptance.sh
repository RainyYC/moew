#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mode="${1:-on}"
filter="${2:-}"
mkdir -p results/run
for input in ../../../data/official/Problem/cases/*.txt; do
  name="$(basename "$input" .txt)"
  if [[ -n "$filter" && ! "$name" =~ $filter ]]; then continue; fi
  output="results/run/$name.$mode.out"
  stderr="results/run/$name.$mode.stderr"
  timeout 10 ./solver "--local=$mode" < "$input" > "$output" 2> "$stderr"
  python3 ../../../data/official/Problem/grader.py "$input" "$output" > "results/run/$name.$mode.time" 2> "results/run/$name.$mode.checker.stderr"
done
