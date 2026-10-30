#!/usr/bin/env python3
"""官方 50 例的**并行**评测器（等价于官方 ``run_all.py``，但用例级并行）。

官方 ``run_all.py`` 是串行跑的：50 例 × 每例最多 7.6 s ≈ 6–7 分钟。用例之间完全独立，
所以按用例并行能把墙钟压到 1 分钟左右，便于反复迭代。

用法::

    python3 tools/run_official.py                  # 全部 50 例，并行 8 路
    python3 tools/run_official.py --jobs 6         # 指定并行度
    python3 tools/run_official.py --subset fast    # 12 例的快速子集（约 1 分钟）
    python3 tools/run_official.py --subset fast --jobs 4
    python3 tools/run_official.py --cases x13_lr_twochunk_p8 r16_p4_trap

**注意**：并行会争抢 CPU，`CPU(s)` 列只在 ``--jobs 1`` 时与官方口径一致；墙钟同理。
判分结果（`TIME`）与串行逐位相同——那才是评分依据。
"""
from __future__ import annotations

import argparse
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "data/official/Problem"
CASES = PKG / "cases"
REPORT = PKG / "report_python.txt"

#: 快速子集：12 例，覆盖 计算主导 / 通信主导 / 填充 / 偏斜 / 紧内存 / twochunk / 对称形态，
#: 且历史表现各异（有的我们赢很多、有的只赢 1%）。用于改代码后的冒烟回归。
FAST = (
    "r16_p4_trap", "r24_p4_block", "r32_p8_ramp", "r64_v2_c2",
    "r64_v8_c8d", "r128_v8_c8a", "r256_v4_c4",
    "x03_lr_trap_p3", "x05_lr_tight_p6", "x13_lr_twochunk_p8",
    "x18_vl_tight_small", "x19_vl_trap4_fs4",
)


def load_baseline() -> dict[str, int]:
    out: dict[str, int] = {}
    if not REPORT.exists():
        return out
    for line in REPORT.read_text().splitlines():
        m = re.match(r"(\S+\.txt)\s+OK\s+(\d+)", line.strip())
        if m:
            out[m.group(1)[:-4]] = int(m.group(2))
    return out


def run_case(name: str, solver: str, keep_dir: Path | None) -> dict:
    case = CASES / f"{name}.txt"
    out = (keep_dir / f"{name}.out") if keep_dir else Path(tempfile.mkstemp(suffix=".out")[1])
    started = time.monotonic()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    proc = subprocess.run(
        [sys.executable, solver, str(case), str(out)],
        capture_output=True, text=True, timeout=30, env=env,
    )
    wall = time.monotonic() - started
    if proc.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        return {"case": name, "time": None, "wall": wall,
                "error": (proc.stderr or "no output").strip().splitlines()[-1:] or ["?"]}
    grade = subprocess.run(
        [sys.executable, "grader.py", str(case), str(out)],
        cwd=PKG, capture_output=True, text=True, timeout=60,
    )
    first = (grade.stdout or "").strip().splitlines()
    value = int(first[0]) if first and first[0].strip().isdigit() else None
    return {"case": name, "time": value, "wall": wall,
            "error": None if value is not None else [(grade.stdout or grade.stderr).strip()[:120]]}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=min(8, (os.cpu_count() or 4)))
    ap.add_argument("--subset", choices=("all", "fast"), default="all")
    ap.add_argument("--cases", nargs="*", default=None)
    ap.add_argument("--solver", default=str(ROOT / "src/solver/solve_all.py"))
    ap.add_argument("--keep", default=None, help="把输出留在这个目录（便于复核）")
    args = ap.parse_args(argv)

    if args.cases:
        names = args.cases
    elif args.subset == "fast":
        names = list(FAST)
    else:
        names = sorted(p.stem for p in CASES.glob("*.txt"))

    if args.keep:
        keep = Path(args.keep); keep.mkdir(parents=True, exist_ok=True)
    else:
        keep = None

    baseline = load_baseline()
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        rows = list(pool.map(lambda n: run_case(n, args.solver, keep), names))
    elapsed = time.monotonic() - started

    bad = [r for r in rows if r["time"] is None]
    ok = [r for r in rows if r["time"] is not None]
    print(f"{'case':26s} {'TIME':>13s} {'baseline':>13s} {'改善':>8s} {'wall':>6s}")
    for r in sorted(rows, key=lambda r: r["case"]):
        base = baseline.get(r["case"])
        if r["time"] is None:
            print(f"{r['case']:26s} {'INVALID':>13s} {base or 0:>13,} {'':>8s} {r['wall']:5.2f}s  {r['error']}")
        else:
            gain = f"{1 - r['time'] / base:+.1%}" if base else "-"
            print(f"{r['case']:26s} {r['time']:>13,} {base or 0:>13,} {gain:>8s} {r['wall']:5.2f}s")

    if ok:
        mean = statistics.mean(r["time"] for r in ok)
        if baseline:
            base_mean = statistics.mean(baseline[r["case"]] for r in ok if r["case"] in baseline)
            geo = statistics.geometric_mean([r["time"] / baseline[r["case"]]
                                             for r in ok if r["case"] in baseline])
            print(f"\n均值 TIME {mean:,.0f}（官方样例解 {base_mean:,.0f}，"
                  f"{1 - mean / base_mean:+.1%}）  几何平均 {geo:.4f}")
        else:
            print(f"\n均值 TIME {mean:,.0f}")
    print(f"合法 {len(ok)}/{len(rows)}   墙钟 {elapsed:.1f}s（jobs={args.jobs}，并行会抬高单例 wall）")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
