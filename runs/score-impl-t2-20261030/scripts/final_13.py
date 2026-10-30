"""t2 交付：13 个大用例 旧基线 vs 当前工作区（独立子进程 + judge 复核 + 几何均值 score）。

- base：生产求解器快照 runs/score-impl-20261030/src-snapshots/prior（gap-fill 版，solver 三个文件）
- cur ：当前工作区 solver/
- 每例各跑 --reps 次，记录 Time/lb/合法性/内存峰值/墙钟；两次都失败也照实记。
输出：runs/score-impl-t2-20261030/final-13/{result.json, README 数据}
用法：PYTHONPATH=. python3 runs/score-impl-t2-20261030/scripts/final_13.py --reps 1
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PRIOR = ROOT / "runs/score-impl-20261030/src-snapshots/prior"
OUT = ROOT / "runs/score-impl-t2-20261030/final-13"
CASES = ["b01-loose", "b02-m512", "b03-m256", "b04-m96", "b05-maxmb", "b06-maxmb-tight",
         "b07-mixed", "b08-narrow", "b09-small-e", "b10-high-k", "b11-short-l",
         "b12-compute-bound", "b13-balanced-compute"]


def run(inp: Path, out: Path, src: Path | None) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{src}{os.pathsep}{ROOT}" if src else str(ROOT)
    began = time.monotonic()
    proc = subprocess.run([sys.executable, "solver/solve_all.py", str(inp), str(out)],
                          cwd=ROOT, capture_output=True, text=True, env=env)
    wall = time.monotonic() - began
    if proc.returncode != 0 or not out.exists():
        return {"ok": False, "wall_s": round(wall, 3), "failure": (proc.stderr or proc.stdout)[-400:]}
    ev = subprocess.run([sys.executable, "-m", "judge", "eval", "--json", str(inp), str(out)],
                        cwd=ROOT, capture_output=True, text=True)
    text = ev.stdout
    idx = text.find("{\n")
    if idx < 0:
        return {"ok": False, "wall_s": round(wall, 3), "failure": f"judge: {(ev.stderr or text)[-300:]}"}
    data = json.loads(text[idx:])
    peak = max((g["mexp"] + g["movl"] + g["mact"]) / g["limit"] for g in data["groups"])
    return {"ok": data["ok"], "time": data["time"], "lb": data["lb"], "grid": data["grid"],
            "K": data["K"], "n_errors": len(data["errors"]), "peak_mem_ratio": round(peak, 4),
            "wall_s": round(wall, 3)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=1)
    args = ap.parse_args()
    for sub in ("base", "cur", "judge"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="t2-base-"))
    shutil.copytree(PRIOR, tmp / "solver")
    rows = []
    for name in CASES:
        inp = ROOT / "bigcases/battery" / f"{name}.in"
        entry = {"case": name}
        for label, src in (("base", tmp), ("cur", None)):
            reps = [run(inp, OUT / label / f"{name}.r{i}.out", src) for i in range(args.reps)]
            entry[label] = reps[0] if len(reps) == 1 else reps
        b, c = entry["base"], entry["cur"]
        b = b if isinstance(b, dict) else min((r for r in b if r["ok"]), key=lambda r: r["time"])
        c = c if isinstance(c, dict) else min((r for r in c if r["ok"]), key=lambda r: r["time"])
        entry["time_rel_cur_over_base"] = round(c["time"] / b["time"], 6) if b.get("ok") and c.get("ok") else None
        rows.append(entry)
        print(json.dumps({"case": name, "base": b.get("time"), "cur": c.get("time"),
                          "rel": entry["time_rel_cur_over_base"],
                          "base_ok": b.get("ok"), "cur_ok": c.get("ok"),
                          "cur_wall": c.get("wall_s"), "cur_mem": c.get("peak_mem_ratio")},
                         ensure_ascii=False), flush=True)
    shutil.rmtree(tmp, ignore_errors=True)
    ok_pairs = [r for r in rows if r["base"].get("ok") and r["cur"].get("ok")]
    geo_cur_over_base = math.exp(sum(math.log(r["time_rel_cur_over_base"]) for r in ok_pairs) / len(ok_pairs)) if ok_pairs else None
    all_ok = all(r["cur"].get("ok") for r in rows)
    summary = {"reps": args.reps, "n_cases": len(rows), "cur_all_legal": all_ok,
               "geomean_cur_over_base": round(geo_cur_over_base, 6) if geo_cur_over_base else None,
               "max_wall_s": max(r["cur"].get("wall_s", 0) for r in rows),
               "rows": rows}
    (OUT / "result.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
