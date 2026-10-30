"""独立验证用公共件：官方 grader 调用、judge 调用、几何均值、子进程求解。

只读：不写生产目录，不改生产代码；子进程用 PYTHONPATH 指向验证留下的源码快照。
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROB = ROOT / "official/extracted/Problem"
GRADER = PROB / "grader.py"
OUTDIR = ROOT / "runs/score-validation-20261030"


def sha256(path: Path) -> str:
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def official_grade(case: Path, out: Path) -> dict:
    t0 = time.perf_counter()
    g = subprocess.run([sys.executable, str(GRADER), str(case), str(out)],
                       capture_output=True, text=True, timeout=120)
    grader_s = time.perf_counter() - t0
    lines = [ln.strip() for ln in (g.stdout or "").splitlines() if ln.strip()]
    text = lines[-1] if lines else ""
    row = {"grader_rc": g.returncode, "grader_out": text, "grader_s": round(grader_s, 3)}
    if g.returncode == 0 and text.isdigit():
        row["time"] = int(text)
    else:
        row["invalid"] = text[:200] or (g.stderr or "")[-200:]
    return row


def judge_eval(case: Path, out: Path) -> dict:
    ev = subprocess.run([sys.executable, "-m", "judge", "eval", "--json", str(case), str(out)],
                        cwd=ROOT, capture_output=True, text=True)
    text = ev.stdout or ""
    idx = text.find("{\n")
    if idx < 0:
        return {"ok": None, "failure": (ev.stderr or text)[-400:]}
    d = json.loads(text[idx:])
    groups = d.get("groups") or []
    peak = max(((gr.get("mexp", 0) + gr.get("movl", 0) + gr.get("mact", 0)) / max(gr.get("limit", 1), 1))
               for gr in groups) if groups else None
    return {"ok": d.get("ok"), "time": d.get("time"), "lb": d.get("lb"), "grid": d.get("grid"),
            "K": d.get("K"), "n_errors": len(d.get("errors") or []),
            "errors": (d.get("errors") or [])[:3], "peak_mem_ratio": peak}


def solve(inp: Path, outp: Path, src: Path | None = None, timeout: float = 10.0, budget: float | None = None,
          extra: list[str] | None = None) -> dict:
    """跑 solver/solve_all.py 单例模式：stdout 即映射。src 非空时把它放在 PYTHONPATH 最前。"""
    env = dict(os.environ)
    root = str(ROOT)
    env["PYTHONPATH"] = f"{src}{os.pathsep}{root}" if src else root
    cmd = [sys.executable, str(ROOT / "solver/solve_all.py"), str(inp), str(outp)]
    if budget is not None:
        cmd += ["--budget", str(budget)]
    if extra:
        cmd += extra
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=env, timeout=timeout)
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
        status = "OK" if proc.returncode == 0 else "ERROR"
    except subprocess.TimeoutExpired as exc:
        rc, out, err, status = None, b"", exc.stderr or b"", "TO"
        out = out.decode() if isinstance(out, bytes) else out
        err = err.decode() if isinstance(err, bytes) else err
    wall = time.perf_counter() - t0
    row = {"status": status, "rc": rc, "wall_s": round(wall, 3)}
    for ln in (err or "").splitlines():
        if "Time=" in ln and "(lb=" in ln:
            row["solver_time"] = ln
    row["stderr_tail"] = (err or "")[-400:]
    if status == "OK":
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(out)
        row["out_sha256"] = sha256(outp)
    return row


def geomean(values):
    vals = [v for v in values if v]
    return math.exp(sum(math.log(v) for v in vals) / len(vals)) if vals else None
