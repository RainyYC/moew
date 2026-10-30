#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冻结实验口径的 manifest 生成器（frontier 团队 t1 交付物）。

只读：读取两个 worktree 的 git 状态、源码/判题器/用例哈希与机器环境，写出一个
JSON manifest。**不改任何源码、不运行求解器、不写 worktree 之外的东西**（除非
``--out`` 显式指向别处）。重复运行应得到除时间戳/负载外完全相同的内容。

用法::

    python3 tools/frontier_manifest.py \
        --sgs /home/rainy/hackathon/work-frontier-sgs \
        --baseline /home/rainy/hackathon/work-frontier-baseline \
        --battery /home/rainy/hackathon/data/battery/bigcases/battery \
        --out runs/frontier/manifest.json

约定：
* ``frozen_base_sha`` 是协议冻结提交（默认 c558d9b 的完整 SHA），从 ``--sgs`` 的
  分支基点核对；本进程不写 git。
* 代码哈希覆盖 ``src/solver/*.py``、``src/judge/core/*.py``、官方 ``grader.py`` /
  ``run_all.py`` / ``sample_solution.py`` 与 ``Makefile``。
* 用例哈希按「排序后的 (相对路径, 字节)」聚合；同时给出逐文件 sha256，便于定位。
* 若两个 worktree 在冻结文件上不一致，``worktrees_identical`` 为 false 并列出差异。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

FROZEN_BASE_SHA = "c558d9be025b4825ce00fdb8ff343da6392272b8"

SOLVER_FILES = (
    "src/solver/__init__.py",
    "src/solver/casein.py",
    "src/solver/exact.py",
    "src/solver/formula.py",
    "src/solver/judgedbridge.py",
    "src/solver/place.py",
    "src/solver/psi.py",
    "src/solver/sched.py",
    "src/solver/solve.py",
    "src/solver/solve_all.py",
)

JUDGE_FILES = (
    "src/judge/core/__init__.py",
    "src/judge/core/acceptance.py",
    "src/judge/core/evaluate.py",
    "src/judge/core/memory.py",
    "src/judge/core/model.py",
    "src/judge/core/parse.py",
    "src/judge/core/sim.py",
)

OFFICIAL_FILES = (
    "data/official/Problem/grader.py",
    "data/official/Problem/run_all.py",
    "data/official/Problem/sample_solution.py",
    "Makefile",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_set(root: Path, paths: list[Path], names: list[str] | None = None) -> dict:
    """聚合哈希：排序后的「相对名 \\0 内容 \\0」逐个喂给 sha256。"""
    ordered = sorted(paths, key=lambda p: str(p))
    digest = hashlib.sha256()
    files: dict[str, str] = {}
    for index, path in enumerate(ordered):
        name = names[index] if names is not None else str(path)
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
        files[name] = sha256_file(path)
    return {"count": len(ordered), "aggregate_sha256": digest.hexdigest(), "files": files}


def hash_named(root: Path, names: tuple[str, ...]) -> dict:
    files = {}
    missing = []
    for name in names:
        path = root / name
        if not path.is_file():
            missing.append(name)
            continue
        files[name] = sha256_file(path)
    return {"files": files, "missing": missing}


def rel_names(root: Path, paths: list[Path]) -> list[str]:
    return [str(p.relative_to(root)) for p in paths]


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip()


def worktree_state(root: Path) -> dict:
    porcelain = git(root, "status", "--porcelain=v1")
    return {
        "path": str(root),
        "head_sha": git(root, "rev-parse", "HEAD"),
        "head_short": git(root, "rev-parse", "--short=12", "HEAD"),
        "branch": git(root, "rev-parse", "--abbrev-ref", "HEAD"),
        "describe": git(root, "describe", "--always", "--dirty"),
        "dirty": bool(porcelain),
        "status_porcelain": porcelain.splitlines(),
    }


def diff_files(left: Path, right: Path, names: tuple[str, ...]) -> list[str]:
    different = []
    for name in names:
        a, b = left / name, right / name
        if not a.is_file() or not b.is_file() or sha256_file(a) != sha256_file(b):
            different.append(name)
    return different


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sgs", required=True, help="frontier 实验 worktree")
    parser.add_argument("--baseline", required=True, help="冻结基线 worktree")
    parser.add_argument(
        "--battery",
        default="/home/rainy/hackathon/data/battery/bigcases/battery",
        help="battery 用例目录（主工作树内，未入库，只读）",
    )
    parser.add_argument("--out", required=True, help="manifest.json 输出路径")
    parser.add_argument(
        "--frozen-base", default=FROZEN_BASE_SHA, help="冻结提交完整 SHA"
    )
    args = parser.parse_args(argv)

    sgs = Path(args.sgs).resolve()
    baseline = Path(args.baseline).resolve()
    battery = Path(args.battery)
    out = Path(args.out).resolve()

    if not (sgs / "src/solver/formula.py").is_file():
        print(f"不是 frontier worktree：{sgs}", file=sys.stderr)
        return 2
    if not (baseline / "src/solver/formula.py").is_file():
        print(f"不是 baseline worktree：{baseline}", file=sys.stderr)
        return 2

    try:
        load = [round(value, 2) for value in os.getloadavg()]
    except OSError:  # pragma: no cover - 非 POSIX 平台
        load = []

    samples = sorted((sgs / "cases").glob("*.in"))
    samples_7 = [p for p in samples if p.name != "big1.in"]
    official_cases = sorted((sgs / "data/official/Problem/cases").glob("*.txt"))
    battery_cases = sorted(battery.glob("*.in")) if battery.is_dir() else []

    manifest = {
        "schema": "frontier-freeze-manifest/1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "generated_by": "tools/frontier_manifest.py",
        "frozen_base": {
            "sha": args.frozen_base,
            "note": "两个 worktree 的共同起点；协议只允许在 opt-frontier-sgs 上提交",
        },
        "worktrees": {
            "sgs": worktree_state(sgs),
            "baseline": worktree_state(baseline),
            "identical_frozen_files": not diff_files(
                sgs, baseline, SOLVER_FILES + JUDGE_FILES + OFFICIAL_FILES
            ),
            "differing_frozen_files": diff_files(
                sgs, baseline, SOLVER_FILES + JUDGE_FILES + OFFICIAL_FILES
            ),
        },
        "environment": {
            "python_version": sys.version.split()[0],
            "python_executable": sys.executable,
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "loadavg_at_generation": load,
            "note": "12 核共享机器；其他团队/成员可能同时占用 CPU，正式测时必须记录负载",
        },
        "hashes": {
            "solver": hash_named(sgs, SOLVER_FILES),
            "judge_core": hash_named(sgs, JUDGE_FILES),
            "official_and_make": hash_named(sgs, OFFICIAL_FILES),
            "baseline_copy": {
                "solver": hash_named(baseline, SOLVER_FILES),
                "judge_core": hash_named(baseline, JUDGE_FILES),
                "official_and_make": hash_named(baseline, OFFICIAL_FILES),
            },
        },
        "cases": {
            "official50": {
                "dir": str(sgs / "data/official/Problem/cases"),
                **hash_set(
                    sgs / "data/official/Problem/cases",
                    official_cases,
                    rel_names(sgs / "data/official/Problem/cases", official_cases),
                ),
            },
            "samples7": {
                "dir": str(sgs / "cases"),
                "note": "ex1..ex6 + mini（big1.in 另计）",
                **hash_set(sgs / "cases", samples_7, rel_names(sgs / "cases", samples_7)),
            },
            "battery13": {
                "dir": str(battery),
                "note": "主工作树未入库用例，只读引用；不要在 worktree 内复制 236MB",
                **hash_set(battery, battery_cases, [p.name for p in battery_cases]),
            },
        },
        "semantics_frozen": {
            "memory": "per card group: Mexp + U*peak_comm + Uact*peak_act; 两个峰值各自独立取峰",
            "comm_peak": "[start,end] 闭；同刻先开后关（结束瞬间算两块）；官方 grader 跳过零时长通信",
            "activation_peak": "[comb.end, s_bwd.start] 双闭；同刻先到后走",
            "engine": "非零时长 [t,t+d) 半开、同刻先释放后占用；零时长不占引擎",
            "k2v": "K=2V 镜像配对：一个卡组的两块共用同一对引擎与同一份内存核算",
        },
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"written {out} ({out.stat().st_size} bytes)", file=sys.stderr)
    print(
        "identical_frozen_files="
        f"{manifest['worktrees']['identical_frozen_files']} "
        f"differing={manifest['worktrees']['differing_frozen_files']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
