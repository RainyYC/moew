#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/build"
g++ -std=c++17 -O2 -pipe -Wall -Wextra "$ROOT/src/solver.cpp" -o "$ROOT/build/solver"
