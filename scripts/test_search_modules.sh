#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT
CXX_BIN="${CXX:-g++}"
COMMON_SOURCES=(
    "$ROOT/src/io/input.cpp"
    "$ROOT/src/io/numeric.cpp"
    "$ROOT/src/placement/expert_mapping.cpp"
    "$ROOT/src/search/local_engine_polish.cpp"
    "$ROOT/src/scheduling/event_scheduler.cpp"
    "$ROOT/src/scheduling/list_scheduler.cpp"
    "$ROOT/src/search/schedule_validation.cpp"
)

"$CXX_BIN" -std=c++17 -O2 -Wall -Wextra -I"$ROOT/src" \
    "$ROOT/tests/layout_bound_search_test.cpp" "${COMMON_SOURCES[@]}" \
    -o "$BUILD_DIR/layout_bound_search_test"
"$BUILD_DIR/layout_bound_search_test"

"$CXX_BIN" -std=c++17 -O2 -Wall -Wextra -I"$ROOT/src" \
    "$ROOT/tests/priority_schedule_modules_test.cpp" \
    "$ROOT/src/search/priority_search.cpp" "${COMMON_SOURCES[@]}" \
    -o "$BUILD_DIR/priority_schedule_modules_test"
"$BUILD_DIR/priority_schedule_modules_test"
