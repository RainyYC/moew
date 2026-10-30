#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""frontier 团队的**串行**公平对照工具（t3 交付物）。

它只做一件事：按同一份协议跑一批用例，把求解器、官方 grader、本地 judge 的原始证据
完整落盘，并输出可机读 / 可人读的汇总。**不 import 任何 solver/judge 模块**——所有
交互都走子进程，避免把被测代码混进测量进程。

协议要点（详见 `docs/reports/frontier-protocol.md`）：

* 一次只跑一个求解进程（串行），逐例独立进程；求解子进程硬超时默认 10 s；
* 求解 wall / CPU 与判题 wall / CPU **分开测量**，判题耗时不计入求解预算；
* 每例的显式预算按 `auto_budget(n_ops)`（≤20k→7.6s、≤200k→7.2s、>200k→6.2s），
  或用 `--budget` 统一覆盖；预算写进 meta/record，A/B 两边必须一致；
* 求解器环境显式 `PYTHONPATH=<worktree>/src`，防止串用另一版本；baseline worktree
  额外 `PYTHONDONTWRITEBYTECODE=1`，保持其 git status 干净；
* 官方 grader 判成绩，本地 judge 作更严格的第二道闸；零时长通信的已知口径差异
  （官方忽略、本地保守计入）单列，不算作任一边的 bug；
* **输入资格三态**：`True`=官方解析通过；`False`=官方解析器明确拒绝（只有这种记
  `INPUT_REJECT`/N/A）；`None`=探针本身失败（`UNVERIFIED`，必须让正式 CLI 失败）；
* 非法 / 超时 / 非零退出 / 缺输出 / 本地判非法（`LOCAL_FAIL`）/ 双判 `Time` 不一致
  （`TIME_MISMATCH`）**一律不计严格通过**；
* **官方成绩统计与严格双判验证分开**：`summary.json` 里 `official_valid`/`official_ok_rate`
  是成绩，`strict_ok`/`strict_failures`/`strict_pass` 是验收；缺省 CLI 只在
  `strict_pass=True` 时退出 0（fail-closed），不会因"官方 TIME 合法"而忽略本地失败或
  未验证输入；
* `--selftest` 用假 solver / 假 grader / 假本地 judge 覆盖原有 4 条失败路径，以及
  unknown 探针、官方明确拒绝、官方合法但本地失败、双判 Time 不一致，并用**真实 CLI
  退出码**验证 fail-closed。

用法::

    # 冻结基线（官方 50 例）
    python3 tools/frontier_bench.py --label baseline-official50 --set official50 \
        --solver /home/rainy/hackathon/work-frontier-baseline/src/solver/solve_all.py \
        --worktree /home/rainy/hackathon/work-frontier-baseline \
        --out runs/frontier/baseline/baseline-official50

    # 六样例 + mini / battery / 覆盖子集
    python3 tools/frontier_bench.py --label baseline-samples7 --set samples7 ...
    python3 tools/frontier_bench.py --label baseline-battery13 --set battery13 ...
    python3 tools/frontier_bench.py --label baseline-fast12 --set fast12 ...

    # 生成留出集（固定 seed + 前置过滤，失败不挑样本）
    python3 tools/frontier_bench.py --gen-heldout --seed 424242 --count 8 \
        --out runs/frontier/cases/heldout-seed424242

    # 自测
    python3 tools/frontier_bench.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import re
import resource
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # work-frontier-sgs
DEFAULT_WORKTREE = ROOT
DEFAULT_SOLVER = ROOT / "src/solver/solve_all.py"
OFFICIAL_DIR = ROOT / "data/official/Problem"
DEFAULT_GRADER = OFFICIAL_DIR / "grader.py"
DEFAULT_CASES = OFFICIAL_DIR / "cases"
BATTERY_DIR = Path("/home/rainy/hackathon/data/battery/bigcases/battery")
SAMPLES_DIR = ROOT / "cases"

#: 预注册的覆盖子集（与 tools/run_official.py --subset fast 一致；在任何结果之前固定）。
FAST12 = (
    "r16_p4_trap", "r24_p4_block", "r32_p8_ramp", "r64_v2_c2",
    "r64_v8_c8d", "r128_v8_c8a", "r256_v4_c4",
    "x03_lr_trap_p3", "x05_lr_tight_p6", "x13_lr_twochunk_p8",
    "x18_vl_tight_small", "x19_vl_trap4_fs4",
)

#: 与 src/solver/solve_all.py 的 BUDGET_BY_OPS 一致（阈值, 预算秒），从大到小。
BUDGET_BY_OPS = ((200_000, 6.2), (20_000, 7.2), (0, 7.6))

SOLVER_FILES = (
    "src/solver/__init__.py", "src/solver/casein.py", "src/solver/exact.py",
    "src/solver/formula.py", "src/solver/judgedbridge.py", "src/solver/place.py",
    "src/solver/psi.py", "src/solver/sched.py", "src/solver/solve.py",
    "src/solver/solve_all.py",
)
JUDGE_FILES = (
    "src/judge/core/__init__.py", "src/judge/core/acceptance.py",
    "src/judge/core/evaluate.py", "src/judge/core/memory.py",
    "src/judge/core/model.py", "src/judge/core/parse.py", "src/judge/core/sim.py",
)

CONFIG_RE = re.compile(
    r"\[solve\] (?P<name>.+?): V=(?P<V>\d+) P=(?P<P>\d+) "
    r"psi=\[(?P<psi>[^\]]*)\] K=(?P<K>\d+) Time=(?P<time>\d+) "
    r"\(lb=(?P<lb>\d+)\) solve=(?P<solve>[0-9.]+)s"
)


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_set(root: Path, names) -> dict:
    digest = hashlib.sha256()
    files: dict[str, str] = {}
    for name in names:
        path = root / name
        if not path.is_file():
            files[name] = "MISSING"
            continue
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
        files[name] = sha256_file(path)
    return {"aggregate_sha256": digest.hexdigest(), "files": files}


def case_set_hash(paths) -> dict:
    digest = hashlib.sha256()
    files = {}
    for path in sorted(paths, key=lambda p: p.name):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
        files[path.name] = sha256_file(path)
    return {"count": len(files), "aggregate_sha256": digest.hexdigest(), "files": files}


def child_cpu() -> float | None:
    try:
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    except (AttributeError, OSError):  # pragma: no cover - 非 POSIX
        return None
    return usage.ru_utime + usage.ru_stime


def loadavg() -> list[float]:
    try:
        return [round(value, 2) for value in os.getloadavg()]
    except OSError:  # pragma: no cover
        return []


def auto_budget(n_ops: int) -> float:
    for threshold, budget in BUDGET_BY_OPS:
        if n_ops > threshold:
            return budget
    return BUDGET_BY_OPS[-1][1]


def parse_case_header(path: Path) -> dict:
    """只读前 3 行；用于算 op 数与零时长通信可疑性，不复制输入。"""
    with path.open("r", encoding="utf-8") as handle:
        line1 = handle.readline().split()
        line2 = handle.readline().split()
        line3 = handle.readline().split()
    if len(line1) < 5 or len(line2) < 13 or len(line3) < 2:
        raise ValueError(f"输入头格式异常：{path}")
    (N, S, M, Bin, Bout) = (int(x) for x in line1[:5])
    (L, E, Z, Zs, U, Uact, k, nmb, Fs, Fio, Fin, ax, bx) = (int(x) for x in line2[:13])
    d, b = int(line3[0]), int(line3[1])
    return {
        "N": N, "S": S, "M": M, "Bin": Bin, "Bout": Bout,
        "L": L, "E": E, "Z": Z, "Zs": Zs, "U": U, "Uact": Uact, "k": k,
        "nmb": nmb, "Fs": Fs, "Fio": Fio, "Fin": Fin, "ax": ax, "bx": bx,
        "d": d, "b": b, "H": (d * b) // k if k else 0,
        "n_ops": L * nmb * 10,
    }


def zero_len_comm_suspect(header: dict, grid: dict | None) -> bool:
    """P=1 / H=0 / Fio=0 时通信时长为 0，本地与官方 Movl 口径会出现已知差异。"""
    if header["H"] == 0 or header["Fio"] == 0:
        return True
    if grid and int(grid.get("P", 1)) == 1:
        return True
    return False


def run_proc(command, *, cwd, env, timeout) -> dict:
    before = child_cpu()
    started = time.perf_counter()
    timed_out = False
    stdout = stderr = ""
    exit_code = None
    try:
        proc = subprocess.run(
            command, cwd=str(cwd), env=env, capture_output=True, text=True,
            timeout=timeout,
        )
        stdout, stderr, exit_code = proc.stdout or "", proc.stderr or "", proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", "replace")
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace")
        exit_code = None
    wall = time.perf_counter() - started
    after = child_cpu()
    cpu = None
    if before is not None and after is not None:
        cpu = max(0.0, after - before)
        # 子进程可能包含被 timeout 杀掉的孙进程；仍按累计差值报告
    return {
        "command": command, "exit": exit_code, "timed_out": timed_out,
        "wall_s": round(wall, 4), "cpu_s": None if cpu is None else round(cpu, 4),
        "stdout": stdout, "stderr": stderr,
    }


def last_digit_line(text: str) -> int | None:
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.isdigit():
            return int(line)
    return None


# --------------------------------------------------------------------------- #
# 三个被测入口
# --------------------------------------------------------------------------- #
def run_solver(solver, worktree, case, out_path, budget, timeout) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(worktree / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("SOLVER_DEBUG_LOG", None)
    command = [sys.executable, str(solver), str(case), str(out_path),
               "--budget", f"{budget:g}"]
    result = run_proc(command, cwd=worktree, env=env, timeout=timeout)
    result["budget_s"] = budget
    return result


def run_official_grader(case, out_path, grader, timeout=60.0) -> dict:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    command = [sys.executable, str(grader), str(case), str(out_path)]
    result = run_proc(command, cwd=grader.parent, env=env, timeout=timeout)
    result["time"] = last_digit_line(result["stdout"]) if result["exit"] == 0 else None
    return result


def run_local_judge(case, out_path, worktree, timeout=120.0) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(worktree / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [sys.executable, "-m", "judge", "eval", str(case), str(out_path), "--json"]
    result = run_proc(command, cwd=worktree, env=env, timeout=timeout)
    payload = None
    text = result["stdout"].strip()
    if text:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            first, last = text.find("{"), text.rfind("}")
            if first >= 0 and last > first:
                try:
                    payload = json.loads(text[first:last + 1])
                except json.JSONDecodeError:
                    payload = None
    result["payload"] = payload
    return result


def probe_official_input(case, grader) -> dict:
    """用**官方输入解析器**独立判定该用例的输入资格，三态语义：

    * ``eligible=True``：官方 ``parse_instance`` 正常返回；
    * ``eligible=False``：官方**明确拒绝**该输入（只捕获官方自己的 ``grader.Invalid``）；
    * ``eligible=None``：探针本身失败（import 失败、超时、未知异常），资格**未验证**。

    只 import grader 并调用它的 ``parse_instance``：不跑模拟、不读任何 solver 输出、
    不依赖报错字符串。只有 ``False`` 允许记 N/A；``None`` 必须让严格验证失败。
    """
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    code = (
        "import sys, grader\n"
        "text = open(sys.argv[1], encoding='utf-8').read()\n"
        "try:\n"
        "    grader.parse_instance(text)\n"
        "except grader.Invalid as exc:\n"
        "    print('INELIGIBLE: ' + str(exc), file=sys.stderr)\n"
        "    sys.exit(3)\n"
        "except Exception as exc:\n"
        "    print('PROBE-FAILED: ' + repr(exc), file=sys.stderr)\n"
        "    sys.exit(4)\n"
        "print('ELIGIBLE')\n"
    )
    result = run_proc(
        [sys.executable, "-c", code, str(case)],
        cwd=grader.parent, env=env, timeout=30.0,
    )
    eligible = None
    if result["exit"] == 0 and "ELIGIBLE" in result["stdout"]:
        eligible = True
        detail = "eligible"
    elif result["exit"] == 3:
        eligible = False
        detail = "official_reject"
    else:
        eligible = None
        detail = "probe_failed"
    return {
        "eligible": eligible,
        "detail": detail,
        "exit": result["exit"],
        "timed_out": result["timed_out"],
        "wall_s": result["wall_s"],
        "stdout": result["stdout"].strip()[-300:],
        "stderr": result["stderr"].strip()[-500:],
    }


# --------------------------------------------------------------------------- #
# 单例执行与证据落盘
# --------------------------------------------------------------------------- #
def run_one(trial, case: Path, *, solver, worktree, grader, run_dir,
            budget_mode, budget_override, timeout, case_set, repeat_index,
            extra_env=None) -> dict:
    name = case.stem
    header = parse_case_header(case)
    n_ops = header["n_ops"]
    budget = budget_override if budget_override is not None else auto_budget(n_ops)
    out_path = run_dir / f"{name}.out"
    out_path.unlink(missing_ok=True)

    record = {
        "case": name, "input": str(case), "input_sha256": sha256_file(case),
        "case_set": case_set, "n_ops": n_ops, "budget_s": budget,
        "timeout_s": timeout, "repeat_index": repeat_index,
        "header": header, "loadavg_before": loadavg(),
        "official_input": probe_official_input(case, grader),
    }
    official_eligible = record["official_input"]["eligible"]

    solver_result = run_solver(solver, worktree, case, out_path, budget, timeout)
    if extra_env:
        # selftest 用的假 solver 需要额外环境变量：重跑一次（只用于自测）
        env = dict(os.environ)
        env["PYTHONPATH"] = str(worktree / "src")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env.update(extra_env)
        solver_result = run_proc(
            solver_result["command"], cwd=worktree, env=env, timeout=timeout
        )
        solver_result["budget_s"] = budget
    record["solver"] = {
        key: solver_result[key]
        for key in ("command", "exit", "timed_out", "wall_s", "cpu_s", "budget_s")
    }
    (run_dir / f"{name}.stderr").write_text(solver_result["stderr"], encoding="utf-8")

    out_bytes = out_path.read_bytes() if out_path.is_file() else b""
    stdout_bytes = solver_result["stdout"].encode("utf-8")
    record["solver"]["out_exists"] = bool(out_bytes)
    record["solver"]["out_bytes"] = len(out_bytes)
    record["solver"]["out_sha256"] = hashlib.sha256(out_bytes).hexdigest() if out_bytes else None
    record["solver"]["stdout_saved"] = stdout_bytes != out_bytes and bool(stdout_bytes)
    if record["solver"]["stdout_saved"]:
        (run_dir / f"{name}.stdout").write_text(solver_result["stdout"], encoding="utf-8")
    else:
        (run_dir / f"{name}.stdout").write_text(
            "# (与 .out 逐字节相同或为空，未重复保存；见 record.json)\n",
            encoding="utf-8",
        )

    # 配置来自 solver stderr 的摘要行（单例模式不打印 window/variant）
    match = CONFIG_RE.search(solver_result["stderr"])
    config = None
    if match:
        psi_text = match.group("psi").strip()
        config = {
            "V": int(match.group("V")), "P": int(match.group("P")), "K": int(match.group("K")),
            "psi": [int(x) for x in psi_text.split(",") if x.strip()] if psi_text else [],
            "solver_time": int(match.group("time")), "lb": int(match.group("lb")),
            "solve_s": float(match.group("solve")),
        }
    record["config"] = config
    if config is None and out_bytes:
        first = out_bytes.decode("utf-8", "replace").splitlines()[:1]
        if first and len(first[0].split()) == 2 and all(x.isdigit() for x in first[0].split()):
            V, P = (int(x) for x in first[0].split())
            record["config"] = {"V": V, "P": P, "source": "output_header"}
    record["zero_len_comm_suspect"] = zero_len_comm_suspect(header, record["config"])

    status = "OK"
    flags: list[str] = []
    official = None
    local = None
    if solver_result["timed_out"]:
        status = "TO"
        flags.append("solver_timeout")
    elif solver_result["exit"] != 0:
        status = "ERROR"
        flags.append(f"solver_exit_{solver_result['exit']}")
    elif not out_bytes:
        status = "ERROR"
        flags.append("missing_output")

    if status in ("OK", "LOCAL_FAIL"):
        official = run_official_grader(case, out_path, grader)
        record["official"] = {
            "exit": official["exit"], "timed_out": official["timed_out"],
            "wall_s": official["wall_s"], "cpu_s": official["cpu_s"],
            "time": official["time"], "stdout": official["stdout"].strip(),
            "stderr": official["stderr"].strip()[-500:],
        }
        (run_dir / f"{name}.grader.out").write_text(official["stdout"], encoding="utf-8")
        (run_dir / f"{name}.grader.err").write_text(official["stderr"], encoding="utf-8")
        if official["timed_out"]:
            status = "INVALID"
            flags.append("grader_timeout")
        elif official["time"] is None:
            status = "INVALID"
            flags.append("grader_reject")
        # 官方判非法时仍跑本地 judge：用于区分「输入被官方拒绝」与「输出非法」，
        # 也用于定位本地/官方的已知口径差异；官方判定仍然是成绩权威。
        local = run_local_judge(case, out_path, worktree)
        payload = local.get("payload") or {}
        record["local"] = {
            "exit": local["exit"], "timed_out": local["timed_out"],
            "wall_s": local["wall_s"], "cpu_s": local["cpu_s"],
            "ok": bool(payload.get("ok")), "time": payload.get("time"),
            "lb": payload.get("lb"), "groups": payload.get("groups"),
            "errors": payload.get("errors") or [],
        }
        (run_dir / f"{name}.judge.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if local["timed_out"] or payload is None:
            if status == "OK":
                status = "LOCAL_FAIL"
                flags.append("judge_unavailable")
        elif not payload.get("ok"):
            if status == "OK":
                status = "LOCAL_FAIL"
                flags.append("local_reject")
        elif status == "INVALID":
            flags.append("local_accepts_official_reject")
        elif payload.get("time") != official["time"]:
            status = "TIME_MISMATCH"
            flags.append("time_mismatch")

    if record.get("zero_len_comm_suspect"):
        flags.append("zero_len_comm_suspect")
    if official_eligible is False:
        # 输入被官方解析拒绝：该例整体记 N/A。solver 行为仍记录在 solver/local 字段与
        # flags 里，但不计 solver 失败、也不计官方成功（题面保证输入合法，这类夹具是
        # 本地派生/自造件）。
        status = "INPUT_REJECT"
        flags.append("official_input_invalid")
        if record.get("local") and record["local"].get("ok"):
            flags.append("local_accepts_official_reject")
    elif official_eligible is None:
        # 资格探针失败：该例的官方资格未验证，绝不能当 N/A。保留 solver 观测 flags，
        # 但整体状态记为 UNVERIFIED，严格验证与正式 CLI 都必须失败。
        status = "UNVERIFIED"
        flags.append("input_probe_unavailable")
    record["official_eligible"] = official_eligible
    record["status"] = status
    record["flags"] = sorted(set(flags))
    record["loadavg_after"] = loadavg()
    return record


# --------------------------------------------------------------------------- #
# 用例集合
# --------------------------------------------------------------------------- #
def resolve_cases(case_set: str, cases_dir: Path | None, names) -> list[Path]:
    if names:
        paths = [Path(name) for name in names]
        return sorted((p if p.is_absolute() else Path.cwd() / p) for p in paths)
    if case_set == "official50":
        return sorted((cases_dir or DEFAULT_CASES).glob("*.txt"))
    if case_set == "fast12":
        base = cases_dir or DEFAULT_CASES
        return [base / f"{name}.txt" for name in FAST12]
    if case_set == "samples7":
        base = cases_dir or SAMPLES_DIR
        return [base / f"{name}.in" for name in
                ("ex1", "ex2", "ex3", "ex4", "ex5", "ex6", "mini")]
    if case_set == "battery13":
        base = cases_dir or BATTERY_DIR
        return sorted(base.glob("*.in"))
    if case_set == "custom":
        if not cases_dir:
            raise SystemExit("--set custom 需要 --cases-dir")
        return sorted(cases_dir.glob("*.in")) + sorted(cases_dir.glob("*.txt"))
    raise SystemExit(f"未知集合 {case_set}")


# --------------------------------------------------------------------------- #
# 汇总
# --------------------------------------------------------------------------- #
def summarize(records: list[dict], label: str, meta: dict) -> dict:
    by_status: dict[str, int] = {}
    for record in records:
        by_status[record["status"]] = by_status.get(record["status"], 0) + 1

    official_times = [r["official"]["time"] for r in records
                      if r.get("official") and r["official"]["time"] is not None]
    walls = [r["solver"]["wall_s"] for r in records]
    cpus = [r["solver"]["cpu_s"] for r in records if r["solver"]["cpu_s"] is not None]
    judge_walls = [r["official"]["wall_s"] for r in records if r.get("official")]
    local_walls = [r["local"]["wall_s"] for r in records if r.get("local")]

    def stats(values):
        if not values:
            return None
        return {
            "count": len(values), "sum": sum(values),
            "mean": statistics.fmean(values), "median": statistics.median(values),
            "min": min(values), "max": max(values),
        }

    eligible_records = [r for r in records if r.get("official_eligible") is True]
    rejected_records = [r for r in records if r.get("official_eligible") is False]
    unknown_records = [r for r in records if r.get("official_eligible") is None]
    eligible_times = [r["official"]["time"] for r in eligible_records
                      if r.get("official") and r["official"]["time"] is not None]
    strict_failures = [
        {"case": r["case"], "status": r["status"], "flags": r["flags"]}
        for r in eligible_records if r["status"] != "OK"
    ]
    strict_pass = bool(eligible_records) and not strict_failures and not unknown_records
    return {
        "label": label, "meta": meta, "cases": len(records),
        "by_status": by_status,
        "eligible": len(eligible_records),
        "officially_rejected": [r["case"] for r in rejected_records],
        "input_unknown": [r["case"] for r in unknown_records],
        "ineligible": [r["case"] for r in rejected_records],  # 兼容旧字段：只含官方明确拒绝
        "rejected_detail": [
            {"case": r["case"], "official_input": r.get("official_input"),
             "status": r["status"], "local_ok": (r.get("local") or {}).get("ok")}
            for r in rejected_records
        ],
        "unknown_detail": [
            {"case": r["case"], "official_input": r.get("official_input"),
             "status": r["status"], "flags": r["flags"]}
            for r in unknown_records
        ],
        # —— 官方成绩统计：只统计官方输入合格的用例，INPUT_REJECT 不计入分母 ——
        "valid_official": len(official_times),
        "official_valid": len(eligible_times),
        "official_ok_rate": (len(eligible_times) / len(eligible_records)) if eligible_records else None,
        "official_score_complete": bool(eligible_records) and len(eligible_times) == len(eligible_records),
        # —— 严格双判验证：官方合格用例必须全部 status=OK（官方合法 + 本地合法 + Time 一致） ——
        "strict_ok": by_status.get("OK", 0),
        "strict_failures": strict_failures,
        "strict_pass": strict_pass,
        "official_time_stats": stats(official_times),
        "solver_wall_stats": stats(walls),
        "solver_cpu_stats": stats(cpus),
        "official_grader_wall_stats": stats(judge_walls),
        "local_judge_wall_stats": stats(local_walls),
        "flags": {
            flag: sum(1 for r in records if flag in r.get("flags", []))
            for flag in sorted({flag for r in records for flag in r.get("flags", [])})
        },
        "records": records,
    }


def render_markdown(summary: dict) -> str:
    lines = [f"# {summary['label']}", "",
             f"- cases: {summary['cases']}  status: {summary['by_status']}",
             f"- eligible(official input): {summary['eligible']}  "
             f"officially rejected (N/A): {summary['officially_rejected'] or '-'}  "
             f"input unknown (fail): {summary['input_unknown'] or '-'}",
             f"- official score: valid {summary['official_valid']}/{summary['eligible']} "
             f"(complete={summary['official_score_complete']})",
             f"- strict dual-judge: {summary['strict_ok']}/{summary['eligible']} OK, "
             f"strict_pass={summary['strict_pass']}"]
    if summary["strict_failures"]:
        lines.append(f"- strict failures: {summary['strict_failures']}")
    meta = summary["meta"]
    lines.append(f"- solver worktree: `{meta['worktree']}` @ `{meta['git']['sha']}`"
                 f" (dirty={meta['git']['dirty']})")
    lines.append(f"- solver: `{meta['solver']}`  budget: {meta['budget']}")
    lines.append(f"- loadavg start={meta['loadavg_start']} end={meta['loadavg_end']}")
    lines.append("")
    lines.append("| case | status | TIME(official) | local | wall(s) | CPU(s) | flags |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for record in summary["records"]:
        official = record.get("official") or {}
        local = record.get("local") or {}
        local_text = "ok" if local.get("ok") else ("-" if not local else "FAIL")
        lines.append(
            f"| {record['case']} | {record['status']} | {official.get('time', '-')} | "
            f"{local_text} | {record['solver']['wall_s']:.3f} | "
            f"{record['solver']['cpu_s'] if record['solver']['cpu_s'] is not None else '-'} | "
            f"{','.join(record.get('flags', [])) or '-'} |"
        )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# 留出集生成（固定 seed + 前置过滤；不看求解结果挑样本）
# --------------------------------------------------------------------------- #
def necessary_feasible(text: str) -> tuple[bool, dict]:
    """输入层面的**本地保守必要筛选**，外加一个独立的官方不可行严格证书。

    语义（不要混用）：

    * ``reason="official_infeasible_activation"``：``Uact > M``。任何合法调度在任一时刻
      都至少有一份激活 ``(mb, ℓ)`` 存活（``comb`` 结束到 ``s_bwd`` 开始是闭区间，至少
      包含一个时刻），因此仅这一份就超过内存上限——与网格、通信、放置都无关，是**官方
      口径下的严格不可行证书**。
    * ``reason="local_necessary_failed"``：对某个 (V,P) 连
      ``ceil(L/V)·((E/P)Z+Zs) + U + Uact <= M`` 都不满足。这是**本地保守口径**的必要
      条件（把零时长通信也算一块缓冲）。它不满足**不等于官方不可行**：官方 grader 忽略
      零时长通信，可能在 P=1/H=0/Fio=0 时给出更小的 Movl。因此这类 False 只能表述为
      "未通过本地必要筛选"，不能冒称官方不可行。
    * ``reason="local_necessary_passed"``：找到一组满足本地必要条件的 (V,P)。这**不是**
      充分可行保证（只是输入层面的必要条件）。

    V 上限按题面 §6 取 64（同时不超过 L 与 R//P）。
    """
    lines = text.strip().splitlines()
    line1, line2, line3 = lines[0].split(), lines[1].split(), lines[2].split()
    N, S, M = int(line1[0]), int(line1[1]), int(line1[2])
    (L, E, Z, Zs, U, Uact, k, nmb, Fs, Fio, Fin) = (int(x) for x in line2[:11])
    d, b = int(line3[0]), int(line3[1])
    R = N * S
    if Uact > M:
        return False, {
            "reason": "official_infeasible_activation",
            "certificate": f"Uact={Uact} > M={M}",
            "note": "任一合法调度至少一份激活存活，故官方口径下不可行（与网格无关）",
        }
    best = None
    V_CAP = 64  # 题面 §6：V ≤ 64
    for P in range(1, E + 1):
        if E % P or not (S % P == 0 or P % S == 0) or P > R:
            continue
        for V in range(1, min(L, R // P, V_CAP) + 1):
            per_layer = (E // P) * Z + Zs
            mexp = -(-L // V) * per_layer
            comm = U  # 本地口径：即使通信时长为 0 也计入一块缓冲
            need = mexp + comm + Uact
            item = {"V": V, "P": P, "mexp": mexp, "comm": comm,
                    "uact": Uact, "need": need, "M": M}
            if best is None or need < best["need"]:
                best = item
            if need <= M:
                return True, {"reason": "local_necessary_passed", **item,
                              "note": "仅输入层面必要条件，不是充分可行保证"}
    return False, {
        "reason": "local_necessary_failed",
        "best_effort": best,
        "note": "未通过本地保守必要条件（含零时长通信缓冲）；不等于官方不可行",
    }


def generate_heldout(seed: int, count: int, out_dir: Path, *,
                     max_r: int, max_l: int, max_e: int, max_nmb: int,
                     max_ops: int) -> list[Path]:
    tools_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(tools_dir))
    sys.path.insert(0, str(ROOT / "src"))
    import fuzz  # noqa: E402  （只复用其确定性用例生成器）

    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    chosen: list[Path] = []
    rejected: list[dict] = []
    scanned = 0
    while len(chosen) < count and scanned < count * 200:
        text, meta = fuzz.random_case(rng, scanned)
        scanned += 1
        if meta["R"] > max_r or meta["L"] > max_l or meta["E"] > max_e:
            continue
        if meta["nmb"] > max_nmb or meta["ops"] > max_ops:
            continue
        feasible, why = necessary_feasible(text)
        if not feasible:
            rejected.append({"index": scanned,
                             "reason": why.get("reason", "necessary_filter_failed"),
                             "detail": why})
            continue
        path = out_dir / f"h{len(chosen):02d}.in"
        path.write_text(text, encoding="utf-8")
        chosen.append(path)
    manifest = {
        "generator": "tools/fuzz.py:random_case（只读复用）",
        "seed": seed, "requested": count, "generated": len(chosen),
        "filter": {"max_R": max_r, "max_L": max_l, "max_E": max_e,
                   "max_nmb": max_nmb, "max_ops": max_ops},
        "selection": "按 RNG 顺序取前 N 个满足前置过滤 + 输入层面必要可行性检查的样本，"
                     "未参考任何求解结果",
        "necessary_filter": "Uact > M 单独即官方不可行；否则检查 "
                            "ceil(L/V)*((E/P)Z+Zs) + U + Uact <= M（本地保守口径，"
                            "V≤64，只用题面公式；False 不冒称官方不可行，True 非充分保证）",
        "rejected": rejected,
        "files": {p.name: sha256_file(p) for p in chosen},
    }
    (out_dir / "heldout-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return chosen


# --------------------------------------------------------------------------- #
# 自测：原有 4 条路径 + 输入资格 unknown / 官方明确拒绝 / 本地失败 / Time 不一致
# --------------------------------------------------------------------------- #
SELFTEST_COPY = """\
import pathlib, shutil, sys
MAPPING = {mapping}
name = pathlib.Path(sys.argv[1]).stem
src = MAPPING.get(name)
if src is None:
    print('no fake output for ' + name, file=sys.stderr)
    sys.exit(2)
shutil.copy(src, sys.argv[2])
sys.stdout.write(open(src, encoding='utf-8').read())
"""
SELFTEST_INVALID = """\
import sys
open(sys.argv[2], 'w', encoding='utf-8').write('this is not a mapping\\n')
sys.stdout.write('this is not a mapping\\n')
"""
SELFTEST_TIMEOUT = """\
import sys, time
time.sleep(5)
open(sys.argv[2], 'w', encoding='utf-8').write('late\\n')
"""
SELFTEST_ERROR = """\
import sys
print('deliberate failure', file=sys.stderr)
sys.exit(3)
"""

FAKE_GRADER_OK = """\
class Invalid(Exception):
    pass

def parse_instance(text):
    return {"ok": True}

def main():
    print(999)
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
"""
FAKE_GRADER_UNKNOWN = """\
def parse_instance(text):
    raise RuntimeError("probe infrastructure failure")

def main():
    print(999)
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
"""
FAKE_JUDGE = """\
import json
print(json.dumps({payload}))
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def selftest(out_root: Path) -> int:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = out_root / f"selftest-{stamp}"
    base.mkdir(parents=True, exist_ok=False)
    ex1 = SAMPLES_DIR / "ex1.in"
    ex1_out = SAMPLES_DIR / "ex1.out"
    mini = SAMPLES_DIR / "mini.in"
    mini_out = SAMPLES_DIR / "mini.out"
    if not all(p.is_file() for p in (ex1, ex1_out, mini, mini_out)):
        print("[selftest] 缺少 cases/ex1.in|ex1.out|mini.in|mini.out", file=sys.stderr)
        return 1

    # ---------- 假 solver ----------
    mapping = {ex1.stem: str(ex1_out), mini.stem: str(mini_out)}
    fake_solver = _write(base / "fake_solvers/copy.py", SELFTEST_COPY.format(mapping=mapping))
    _write(base / "fake_solvers/invalid.py", SELFTEST_INVALID)
    _write(base / "fake_solvers/timeout.py", SELFTEST_TIMEOUT)
    _write(base / "fake_solvers/error.py", SELFTEST_ERROR)

    # ---------- 假官方 grader（只用于 unknown 探针场景） ----------
    grader_ok = _write(base / "fake_graders/ok/grader.py", FAKE_GRADER_OK)
    grader_unknown = _write(base / "fake_graders/unknown/grader.py", FAKE_GRADER_UNKNOWN)

    # ---------- 假本地 judge（jduge 包放 src/judge，跑 python -m judge） ----------
    def fake_worktree(name: str, payload: str) -> Path:
        root = base / "fake_worktrees" / name
        _write(root / "src/judge/__init__.py", "")
        _write(root / "src/judge/__main__.py", FAKE_JUDGE.format(payload=payload))
        return root

    wt_ok = fake_worktree(
        "ok", '{"ok": True, "time": 999, "lb": 0, "groups": [], "errors": []}')
    wt_local_fail = fake_worktree(
        "local_fail", '{"ok": False, "time": None, "lb": 0, "groups": [], "errors": ["local reject"]}')
    wt_mismatch = fake_worktree(
        "mismatch", '{"ok": True, "time": 1000, "lb": 0, "groups": [], "errors": []}')

    failures: list[tuple] = []
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, condition: bool, detail: str) -> None:
        checks.append((name, condition, detail))
        if not condition:
            failures.append((name, detail))

    def invoke_cli(scenario: str, *, cases, solver, worktree, grader, timeout=5.0):
        run_dir = base / f"cli-{scenario}"
        args = [
            "--label", f"selftest-{scenario}", "--cases", *[str(c) for c in cases],
            "--solver", str(solver), "--worktree", str(worktree),
            "--grader", str(grader), "--budget", "1", "--timeout", str(timeout),
            "--out", str(run_dir),
        ]
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), *args],
            capture_output=True, text=True, timeout=180,
        )
        summary_path = run_dir / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else None
        return proc, summary

    print("[selftest] 原有 4 条路径（真 grader + 真本地 judge）", flush=True)
    direct = {
        "valid": (fake_solver, 10.0, "OK"),
        "invalid": (base / "fake_solvers/invalid.py", 10.0, "INVALID"),
        "timeout": (base / "fake_solvers/timeout.py", 1.0, "TO"),
        "error": (base / "fake_solvers/error.py", 10.0, "ERROR"),
    }
    for name, (solver, timeout, expected) in direct.items():
        run_dir = base / f"direct-{name}"
        run_dir.mkdir()
        record = run_one(
            None, ex1, solver=solver, worktree=ROOT, grader=DEFAULT_GRADER,
            run_dir=run_dir, budget_mode="auto", budget_override=1.0,
            timeout=timeout, case_set="selftest", repeat_index=0,
        )
        check(f"direct-{name}", record["status"] == expected,
              f"expected={expected} got={record['status']} flags={record['flags']}")
        if name == "valid":
            check("direct-valid-dual-judge",
                  bool(record.get("official") and record["official"].get("time") is not None
                       and record.get("local") and record["local"].get("ok")),
                  f"official={record.get('official')} local={record.get('local')}")

    print("[selftest] 新增异常路径（假 solver/grader/judge + 真实 CLI 退出码）", flush=True)

    proc, summary = invoke_cli("ok", cases=[ex1], solver=fake_solver,
                               worktree=wt_ok, grader=grader_ok)
    check("cli-ok-exit0", proc.returncode == 0, f"exit={proc.returncode} stderr={proc.stderr[-200:]}")
    check("cli-ok-status", bool(summary) and summary["by_status"].get("OK") == 1
          and summary["strict_pass"] is True, f"summary={summary and summary['by_status']}")

    proc, summary = invoke_cli("local-fail", cases=[ex1], solver=fake_solver,
                               worktree=wt_local_fail, grader=grader_ok)
    check("cli-local-fail-nonzero", proc.returncode != 0, f"exit={proc.returncode}")
    check("cli-local-fail-strict", bool(summary) and summary["by_status"].get("LOCAL_FAIL") == 1
          and summary["strict_pass"] is False
          and summary["official_valid"] == 1,
          f"status={summary and summary['by_status']} official_valid={summary and summary['official_valid']}")

    proc, summary = invoke_cli("time-mismatch", cases=[ex1], solver=fake_solver,
                               worktree=wt_mismatch, grader=grader_ok)
    check("cli-mismatch-nonzero", proc.returncode != 0, f"exit={proc.returncode}")
    check("cli-mismatch-strict", bool(summary) and summary["by_status"].get("TIME_MISMATCH") == 1
          and summary["strict_pass"] is False and "time_mismatch" in summary["flags"],
          f"status={summary and summary['by_status']} flags={summary and summary['flags']}")

    proc, summary = invoke_cli("unknown-probe", cases=[ex1], solver=fake_solver,
                               worktree=wt_ok, grader=grader_unknown)
    check("cli-unknown-nonzero", proc.returncode != 0, f"exit={proc.returncode}")
    check("cli-unknown-not-n-a", bool(summary) and summary["by_status"].get("UNVERIFIED") == 1
          and summary["input_unknown"] == [ex1.stem]
          and summary["officially_rejected"] == []
          and summary["strict_pass"] is False,
          f"status={summary and summary['by_status']} unknown={summary and summary['input_unknown']}")

    proc, summary = invoke_cli("official-reject-mixed", cases=[ex1, mini], solver=fake_solver,
                               worktree=ROOT, grader=DEFAULT_GRADER)
    check("cli-reject-exit0", proc.returncode == 0, f"exit={proc.returncode} stderr={proc.stderr[-200:]}")
    check("cli-reject-n-a", bool(summary) and summary["officially_rejected"] == [mini.stem]
          and summary["by_status"].get("INPUT_REJECT") == 1
          and summary["by_status"].get("OK") == 1
          and summary["strict_pass"] is True
          and summary["official_valid"] == 1,
          f"status={summary and summary['by_status']} rejected={summary and summary['officially_rejected']}")

    print(f"[selftest] artifacts: {base}")
    for name, condition, detail in checks:
        print(f"[selftest] {name:28s} {'PASS' if condition else 'FAIL'}  {detail}", flush=True)
    if failures:
        print(f"[selftest] FAIL: {failures}", file=sys.stderr)
        return 1
    print("[selftest] PASS: 原有 4 路径 + unknown/官方明确拒绝/本地失败/Time 不一致 "
          "均按 fail-closed 语义分类；unknown 未计 N/A，本地失败/Time 不一致未计 strict OK")
    return 0


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def build_meta(args, cases, run_dir: Path, tool_sha: str) -> dict:
    worktree = Path(args.worktree).resolve()
    solver = Path(args.solver).resolve()
    git_sha = None
    git_dirty = None
    try:
        git_sha = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False,
        ).stdout.strip() or None
        git_dirty = bool(subprocess.run(
            ["git", "-C", str(worktree), "status", "--porcelain"],
            capture_output=True, text=True, check=False,
        ).stdout.strip())
    except OSError:
        pass
    grader = Path(args.grader).resolve()
    return {
        "run_id": run_dir.name, "label": args.label,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "tool": str(Path(__file__).resolve()), "tool_sha256": tool_sha,
        "worktree": str(worktree), "solver": str(solver),
        "git": {"sha": git_sha, "dirty": git_dirty},
        "solver_hashes": sha256_set(worktree, SOLVER_FILES),
        "judge_hashes": sha256_set(worktree, JUDGE_FILES),
        "grader": {"path": str(grader), "sha256": sha256_file(grader)},
        "python": sys.version.split()[0], "executable": sys.executable,
        "platform": platform.platform(), "cpu_count": os.cpu_count(),
        "loadavg_start": loadavg(),
        "budget": {"mode": args.budget, "table": BUDGET_BY_OPS,
                   "timeout_s": args.timeout},
        "repeat": args.repeat, "reverse": args.reverse,
        "case_set": args.set, "case_set_hash": case_set_hash(cases),
        "cases": [str(case) for case in cases],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="frontier 串行公平对照工具（官方 grader + 本地 judge 双验）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--label", default="run", help="批次标签")
    parser.add_argument("--set", default="official50",
                        choices=("official50", "fast12", "samples7", "battery13", "custom"))
    parser.add_argument("--cases-dir", default=None, help="自定义用例目录")
    parser.add_argument("--cases", nargs="*", default=None, help="显式用例路径（覆盖 --set）")
    parser.add_argument("--solver", default=str(DEFAULT_SOLVER))
    parser.add_argument("--worktree", default=str(DEFAULT_WORKTREE),
                        help="被测代码所在 worktree（PYTHONPATH 与本地 judge 都取它）")
    parser.add_argument("--grader", default=str(DEFAULT_GRADER))
    parser.add_argument("--out", default=None, help="run 目录（必须不存在，除非 --force）")
    parser.add_argument("--budget", default="auto",
                        help="auto 或统一显式预算（秒）")
    parser.add_argument("--timeout", type=float, default=10.0,
                        help="求解子进程硬超时（秒，题面 10 s）")
    parser.add_argument("--repeat", type=int, default=1, help="每例重复次数")
    parser.add_argument("--reverse", action="store_true", help="逆序执行（A/B 交替用）")
    parser.add_argument("--force", action="store_true", help="允许复用已存在的 run 目录")
    parser.add_argument("--selftest", action="store_true", help="用假 solver 自测工具")
    parser.add_argument("--selftest-out", default=str(ROOT / "runs/frontier"))
    parser.add_argument("--gen-heldout", action="store_true", help="生成留出集后退出")
    parser.add_argument("--audit-inputs", action="store_true",
                        help="只用官方解析器审计输入资格，写 JSON 后退出（不求解）")
    parser.add_argument("--seed", type=int, default=424242)
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--max-r", type=int, default=128)
    parser.add_argument("--max-l", type=int, default=32)
    parser.add_argument("--max-e", type=int, default=128)
    parser.add_argument("--max-nmb", type=int, default=128)
    parser.add_argument("--max-ops", type=int, default=65_280)
    args = parser.parse_args(argv)

    tool_sha = sha256_file(Path(__file__).resolve())

    if args.selftest:
        return selftest(Path(args.selftest_out))

    if args.audit_inputs:
        if not args.out:
            print("[audit] 缺少 --out（JSON 文件路径）", file=sys.stderr)
            return 2
        cases = [c.resolve() for c in resolve_cases(
            args.set, Path(args.cases_dir) if args.cases_dir else None, args.cases)]
        if not cases:
            print("[audit] 没有用例", file=sys.stderr)
            return 2
        grader = Path(args.grader).resolve()
        rows = []
        for case in cases:
            probe = probe_official_input(case, grader)
            rows.append({
                "case": case.stem, "input": str(case),
                "input_sha256": sha256_file(case), **probe,
            })
        payload = {
            "grader": {"path": str(grader), "sha256": sha256_file(grader)},
            "case_set": args.set, "cases": rows,
            "eligible": sum(1 for row in rows if row["eligible"] is True),
            "officially_rejected": [row["case"] for row in rows if row["eligible"] is False],
            "input_unknown": [row["case"] for row in rows if row["eligible"] is None],
            "ineligible": [row["case"] for row in rows if row["eligible"] is False],  # 兼容旧字段
            "note": "资格只由官方 grader.parse_instance 判定，与 solver 输出无关；"
                    "False=官方明确拒绝，None=探针失败（未验证）",
        }
        out_path = Path(args.out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
        print(f"[audit] {len(rows)} 例，eligible={payload['eligible']}，"
              f"officially_rejected={payload['officially_rejected'] or '-'}，"
              f"input_unknown={payload['input_unknown'] or '-'} → {out_path}", flush=True)
        return 0 if payload["eligible"] == len(rows) else 1

    if args.gen_heldout:
        out_dir = Path(args.out).resolve()
        if out_dir.exists() and any(out_dir.iterdir()) and not args.force:
            print(f"[heldout] 目录已存在且非空：{out_dir}（用 --force 覆盖）", file=sys.stderr)
            return 2
        paths = generate_heldout(
            args.seed, args.count, out_dir, max_r=args.max_r, max_l=args.max_l,
            max_e=args.max_e, max_nmb=args.max_nmb, max_ops=args.max_ops,
        )
        print(f"[heldout] seed={args.seed} 生成 {len(paths)} 例 → {out_dir}", file=sys.stderr)
        return 0

    if not args.out:
        print("[bench] 缺少 --out", file=sys.stderr)
        return 2
    run_dir = Path(args.out).resolve()
    if run_dir.exists() and any(run_dir.iterdir()):
        if not args.force:
            print(f"[bench] run 目录已存在且非空：{run_dir}（协议要求追加不覆盖，"
                  f"请换新 run_id 或显式 --force）", file=sys.stderr)
            return 2
    run_dir.mkdir(parents=True, exist_ok=True)

    budget_override = None
    if args.budget != "auto":
        try:
            budget_override = float(args.budget)
        except ValueError:
            print(f"[bench] --budget 需要 auto 或数字，得到 {args.budget!r}", file=sys.stderr)
            return 2
        if not (0 < budget_override < args.timeout):
            print(f"[bench] 显式预算必须 0 < B < 超时 {args.timeout}", file=sys.stderr)
            return 2

    cases = [c.resolve() for c in resolve_cases(
        args.set, Path(args.cases_dir) if args.cases_dir else None, args.cases)]
    if not cases:
        print("[bench] 没有用例", file=sys.stderr)
        return 2
    missing = [str(case) for case in cases if not case.is_file()]
    if missing:
        print(f"[bench] 用例不存在：{missing[:3]}", file=sys.stderr)
        return 2
    if args.reverse:
        cases = list(reversed(cases))

    meta = build_meta(args, cases, run_dir, tool_sha)
    (run_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "cmd.txt").write_text(" ".join([sys.executable, *sys.argv]) + "\n",
                                     encoding="utf-8")
    (run_dir / "env.txt").write_text(
        "\n".join([
            f"python: {sys.version.split()[0]} ({sys.executable})",
            f"platform: {platform.platform()}",
            f"cpus: {os.cpu_count()}",
            f"solver worktree: {meta['worktree']}",
            f"solver: {meta['solver']}",
            f"git: {meta['git']}",
            f"grader: {meta['grader']}",
            f"loadavg start: {meta['loadavg_start']}",
        ]) + "\n", encoding="utf-8",
    )

    print(f"[bench] {args.label}: {len(cases)} 例, set={args.set}, worktree={meta['worktree']}, "
          f"budget={args.budget}, timeout={args.timeout}s, repeat={args.repeat}", flush=True)
    records: list[dict] = []
    started = time.perf_counter()
    for index, case in enumerate(cases, 1):
        for repeat_index in range(args.repeat):
            if args.repeat > 1:
                print(f"[bench] ({index}/{len(cases)}) {case.stem} trial {repeat_index + 1}/{args.repeat}",
                      flush=True)
            record = run_one(
                index, case, solver=Path(args.solver).resolve(),
                worktree=Path(args.worktree).resolve(), grader=Path(args.grader).resolve(),
                run_dir=run_dir, budget_mode=args.budget,
                budget_override=budget_override, timeout=args.timeout,
                case_set=args.set, repeat_index=repeat_index,
            )
            records.append(record)
            (run_dir / f"{case.stem}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            official = record.get("official") or {}
            time_text = str(official.get("time", "-")).rjust(12)
            cpu = record["solver"]["cpu_s"]
            cpu_text = "-" if cpu is None else f"{cpu:.2f}"
            print(
                f"[bench] {record['case']:26s} {record['status']:10s} "
                f"TIME={time_text} wall={record['solver']['wall_s']:6.3f}s "
                f"cpu={cpu_text:>6} B={record['budget_s']:.1f} "
                f"flags={','.join(record['flags']) or '-'}",
                flush=True,
            )

    total_wall = time.perf_counter() - started
    summary = summarize(records, args.label, meta)
    summary["total_wall_s"] = round(total_wall, 3)
    summary["loadavg_end"] = loadavg()
    meta["loadavg_end"] = summary["loadavg_end"]
    meta["total_wall_s"] = summary["total_wall_s"]
    (run_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "summary.md").write_text(render_markdown(summary), encoding="utf-8")
    print(f"[bench] total wall {total_wall:.1f}s  status={summary['by_status']}  "
          f"eligible={summary['eligible']}/{summary['cases']}  "
          f"official score={summary['official_valid']}/{summary['eligible']}  "
          f"strict OK={summary['strict_ok']}/{summary['eligible']}  "
          f"strict_pass={summary['strict_pass']}", flush=True)
    if summary["officially_rejected"]:
        print("[bench] 官方明确拒绝的输入（N/A，不计 solver 失败，也不计入官方分母）："
              f"{summary['officially_rejected']}", flush=True)
    if summary["input_unknown"]:
        print("[bench] 输入资格探针失败（UNVERIFIED，严格验证失败）："
              f"{summary['input_unknown']}", file=sys.stderr)
    if summary["strict_failures"]:
        print(f"[bench] 严格双判失败：{summary['strict_failures']}", file=sys.stderr)
    if summary["eligible"] == 0:
        print("[bench] 没有任何官方合格用例，无法形成官方成绩", file=sys.stderr)
        return 2
    if not summary["strict_pass"]:
        print("[bench] FAIL-CLOSED：官方成绩统计不等于严格双判通过；"
              "正式候选验收不得使用退出码 0", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
