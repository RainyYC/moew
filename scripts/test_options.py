#!/usr/bin/env python3
"""Quick command-line parser checks; expects the already-built solver path."""
import subprocess
import sys


solver = sys.argv[1] if len(sys.argv) > 1 else "build/solver"


def run(*args):
    return subprocess.run([solver, *args], input="", text=True, capture_output=True)


help_result = run("--help")
assert help_result.returncode == 0, help_result.stderr
assert "Usage:" in help_result.stdout, help_result.stdout
assert run("-h").returncode == 0

for bad in ("--force-p=2junk", "--force-p=-1", "--polish-pass-limit=1x",
            "--mode=unknown", "--borrow=ac", "--budget-ms=9200"):
    result = run(bad)
    assert result.returncode == 2, (bad, result.returncode, result.stderr)
    assert result.stderr.strip(), (bad, result.stderr)

duplicate = run("first.txt", "second.txt")
assert duplicate.returncode == 2 and "multiple input paths" in duplicate.stderr
stdin_duplicate = run("-", "input.txt")
assert stdin_duplicate.returncode == 2 and "multiple input paths" in stdin_duplicate.stderr

print("command-line parser checks passed")
