"""官方 50 例基线 / 诊断（只读）：按官方 `run_all.py` 的同一口径跑我们的求解器。

- 命令：`python3 solver/solve_all.py <case>`（单例模式，stdout 即映射），每例 10 s 墙钟；
- 评测：官方 `grader.py`（**官方判定器**，不是本仓库 judge），输出整数 TIME 或 INVALID；
- 记录：status / TIME / CPU / wall / stderr 尾 160 字；并另存每例映射用于二次分析。
- 官方基准（base）**未随包提供**：本脚本只用 `--ref`（另一个结果 JSON）计算
  相对几何时间比 `exp(mean log(time_cur/time_ref))`，**不能**称为"官方绝对分"。

用法：
    python3 runs/score-impl-t2-20261030/scripts/official50.py --label cur \
        --out runs/score-impl-t2-20261030/official50-cur
    python3 runs/score-impl-t2-20261030/scripts/official50.py --label prior \
        --out runs/score-impl-t2-20261030/official50-prior --src <snapshot_dir> \
        --ref runs/score-impl-t2-20261030/official50-cur/result.json
"""
from __future__ import annotations

import argparse
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


def run_case(case: Path, src: Path | None, timeout: float, keep: Path) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{src}{os.pathsep}{ROOT}" if src else str(ROOT)
    t0 = time.perf_counter()
    try:
        proc = subprocess.run([sys.executable, str(ROOT / "solver/solve_all.py"), str(case)],
                              cwd=ROOT, capture_output=True, text=True, env=env, timeout=timeout)
        status, out, err = "OK", proc.stdout, proc.stderr
        if proc.returncode != 0:
            status = "ERROR"
    except subprocess.TimeoutExpired as exc:
        status, out, err = "TO", exc.stdout or "", exc.stderr or ""
        out = out.decode() if isinstance(out, bytes) else out
        err = err.decode() if isinstance(err, bytes) else err
    wall = time.perf_counter() - t0
    row: dict = {"case": case.name, "status": status, "wall_s": round(wall, 3),
                 "stderr_tail": (err or "")[-160:] if isinstance(err, str) else ""}
    if status != "OK":
        return row
    out_file = keep / case.name.replace(".txt", ".out")
    out_file.write_text(out)
    g = subprocess.run([sys.executable, str(GRADER), str(case), str(out_file)],
                       capture_output=True, text=True, timeout=60)
    text = (g.stdout or "").strip()
    line = text.splitlines()[-1].strip() if text else ""
    if g.returncode == 0 and line.isdigit():
        row["time"] = int(line)
    else:
        row["status"] = "INVALID"
        row["detail"] = line[:160]
    for ln in (err or "").splitlines():
        if "Time=" in ln and "(lb=" in ln:
            row["solver_lb"] = int(ln.split("(lb=")[1].split(")")[0])
            row["solver_time"] = int(ln.split("Time=")[1].split(" ")[0])
            row["grid"] = ln.split(": V=")[1].split(" ")[0] if ": V=" in ln else None
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--src", default=None, help="替换 solver/ 的源码目录（基线对比用）")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--ref", default=None, help="另一个 result.json，用于相对几何时间比")
    args = ap.parse_args()
    out = Path(args.out)
    (out / "maps").mkdir(parents=True, exist_ok=True)
    src = Path(args.src) if args.src else None
    rows = []
    for case in sorted((PROB / "cases").glob("*.txt")):
        row = run_case(case, src, args.timeout, out / "maps")
        rows.append(row)
        print(json.dumps({k: row.get(k) for k in ("case", "status", "time", "wall_s", "grid")},
                         ensure_ascii=False), flush=True)
    ok = [r for r in rows if r["status"] == "OK"]
    summary = {"label": args.label, "n": len(rows), "ok": len(ok),
               "invalid": sum(1 for r in rows if r["status"] == "INVALID"),
               "timeout": sum(1 for r in rows if r["status"] == "TO"),
               "error": sum(1 for r in rows if r["status"] == "ERROR"),
               "max_wall_s": max(r["wall_s"] for r in rows),
               "mean_time": (sum(r["time"] for r in ok) / len(ok)) if ok else None, "rows": rows}
    if args.ref:
        ref = {r["case"]: r for r in json.loads(Path(args.ref).read_text())["rows"]}
        logs = [math.log(r["time"] / ref[r["case"]]["time"]) for r in ok
                if r["case"] in ref and ref[r["case"]].get("time")]
        summary["relative_geomean_vs_ref"] = round(math.exp(sum(logs) / len(logs)), 6) if logs else None
        summary["relative_geomean_n"] = len(logs)
    (out / "result.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
