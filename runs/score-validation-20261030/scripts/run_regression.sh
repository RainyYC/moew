#!/usr/bin/env bash
# 相关回归：求解器自检 + 判题器/独立复核器 + lb_chain 工具。只读。
set -u
cd /home/rainy/hackathon
export PYTHONDONTWRITEBYTECODE=1
run() { echo "=== $* ==="; "$@" 2>&1; echo "=== exit=$? ==="; }
run python3 -m solver.selftests
run python3 -m solver.selftests.test_tight_window
run python3 -m judge --help
run python3 tools/independent_check.py
run python3 tools/independent_check.py --cases ex1 ex2 ex3 ex4 ex5 ex6 mini
