#!/usr/bin/env python3
"""Run the actual solver once and preserve its output for the official runner.

This adapter never replays saved answers. The official timeout includes this
adapter, the solver process, and writing the diagnostic files.
"""
import json
import subprocess
import sys
import time
from pathlib import Path


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: capture_solver_run.py SOLVER OUTPUT_DIRECTORY CASE")
    solver, output, case = map(Path, sys.argv[1:])
    output.mkdir(parents=True, exist_ok=True)
    command = [str(solver.resolve()), str(case.resolve())]
    started = time.perf_counter()
    try:
        # Kill the actual child before the official 10 s timeout can kill this
        # adapter. A timeout is a failed run, never an accepted partial answer.
        run = subprocess.run(command, capture_output=True, timeout=9.75)
    except subprocess.TimeoutExpired as error:
        (output / f"{case.stem}.stderr").write_bytes(
            (error.stderr or b"") + b"\nsolver exceeded capture hard limit 9.75 s\n"
        )
        sys.stderr.write("solver exceeded capture hard limit 9.75 s\n")
        return 124
    elapsed = time.perf_counter() - started
    (output / f"{case.stem}.out").write_bytes(run.stdout)
    (output / f"{case.stem}.stderr").write_bytes(run.stderr)
    (output / f"{case.stem}.json").write_text(json.dumps({
        "command": command, "returncode": run.returncode,
        "solver_wall_seconds": elapsed, "replayed": False,
    }, indent=2) + "\n")
    sys.stdout.buffer.write(run.stdout)
    sys.stderr.buffer.write(run.stderr)
    return run.returncode


if __name__ == "__main__":
    sys.exit(main())
