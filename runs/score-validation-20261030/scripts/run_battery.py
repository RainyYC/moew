"""13 个大用例独立复验（官方 grader 判分 + 仓库 judge 交叉核对 + 内存峰值 + 墙钟）。

每个 (case, variant) 串行跑 --reps 次；变体：
  cur    = 本轮验证快照（工作区 solver/ 的副本）
  base   = 本轮增量基线（t2 start-snapshot，即本轮开始时的工作区状态）
  HEAD   = 仅作历史对照（git show HEAD:solver/*.py 导出到临时目录；**不可**当本轮基线）

只读生产代码：导出/临时目录都在 runs/score-validation-20261030/ 下，跑完即删。
所有运行都显式 `--budget <相同值>`，消除"预算不同"这一混淆因素。

用法：
  PYTHONPATH=. python3 runs/score-validation-20261030/scripts/run_battery.py \
      --cases b12-compute-bound b13-balanced-compute --variants cur base HEAD --reps 3 --budget 6.0
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

BATTERY = common.ROOT / "bigcases/battery"
BASE_SRC = common.ROOT / "runs/score-impl-t2-20261030/start-snapshot"
ALL_CASES = ["b01-loose", "b02-m512", "b03-m256", "b04-m96", "b05-maxmb", "b06-maxmb-tight",
             "b07-mixed", "b08-narrow", "b09-small-e", "b10-high-k", "b11-short-l",
             "b12-compute-bound", "b13-balanced-compute"]


def head_src(dest: Path) -> Path:
    """把 HEAD 版本的 solver/*.py 导出到 dest（只读 git show，不 checkout、不动工作区）。"""
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("__init__.py", "casein.py", "exact.py", "formula.py", "judgedbridge.py",
                 "place.py", "psi.py", "sched.py", "solve.py", "solve_all.py"):
        blob = subprocess.run(["git", "show", f"HEAD:solver/{name}"], cwd=common.ROOT,
                              capture_output=True, check=True)
        (dest / name).write_bytes(blob.stdout)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", nargs="+", default=ALL_CASES)
    ap.add_argument("--variants", nargs="+", default=["cur", "base"])
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--budget", type=float, default=None, help="显式 --budget（秒）；缺省用 auto_budget")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out = Path(args.out) if args.out else (common.OUTDIR / "battery" / "run")
    (out / "outs").mkdir(parents=True, exist_ok=True)
    srcs = {"cur": common.OUTDIR / "snapshot", "base": BASE_SRC,
            "v2": common.OUTDIR / "snapshot_v2",
            "noprune": common.OUTDIR / "scripts/noprune-src"}
    if "HEAD" in args.variants:
        srcs["HEAD"] = head_src(out / "_head_src")
    budget = args.budget
    rows = []
    for name in args.cases:
        inp = BATTERY / f"{name}.in"
        for variant in args.variants:
            src = srcs[variant]
            per = []
            for rep in range(args.reps):
                outp = out / "outs" / f"{name}.{variant}.r{rep}.out"
                r = {"rep": rep}
                r.update(common.solve(inp, outp, src=src, timeout=10.0, budget=budget))
                if r["status"] == "OK":
                    r["official"] = common.official_grade(inp, outp)
                    r["judge"] = common.judge_eval(inp, outp)
                    if "time" in r["official"]:
                        r["time"] = r["official"]["time"]
                per.append(r)
                print(json.dumps({"case": name, "variant": variant, "rep": rep,
                                  "status": r["status"], "time": r.get("time"),
                                  "wall_s": r["wall_s"],
                                  "official": r.get("official", {}).get("grader_out"),
                                  "judge_ok": r.get("judge", {}).get("ok")}, ensure_ascii=False),
                      flush=True)
            times = [p.get("time") for p in per if p.get("time")]
            rows.append({
                "case": name, "variant": variant,
                "src_sha256": common.sha256(src / "solve.py"),
                "times": times,
                "time_stable": len(set(times)) <= 1,
                "time_spread_pct": (max(times) / min(times) - 1) * 100 if times else None,
                "all_legal": all(p.get("judge", {}).get("ok") for p in per) if times else False,
                "grader_legal": all("time" in p.get("official", {}) for p in per) if times else False,
                "n_errors": [p.get("judge", {}).get("n_errors") for p in per],
                "peak_mem_ratio": max((p.get("judge", {}).get("peak_mem_ratio") or 0) for p in per) if times else None,
                "wall_s_max": max(p["wall_s"] for p in per),
                "wall_s": [p["wall_s"] for p in per],
                "out_sha256": [p.get("out_sha256") for p in per],
                "runs": per,
            })
    summary = {"budget": budget, "reps": args.reps, "variants": args.variants,
               "src_sha256": {k: common.sha256(v / "solve.py") for k, v in srcs.items()},
               "rows": rows}
    (out / "result.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    if "HEAD" in args.variants:
        shutil.rmtree(out / "_head_src", ignore_errors=True)
    print(json.dumps({"done": len(rows), "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
