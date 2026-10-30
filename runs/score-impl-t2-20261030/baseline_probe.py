"""基线采样（只读）：对每个 battery 用例连跑 N 次**当前工作区**求解器，记录 judge Time 与墙钟分布。
用来区分"真实回退"与"单次采样抖动"（b12 在 budget=7 的 A/B 里出现 3.69e17，而默认预算是 8.38e16）。

用法：PYTHONPATH=. python3 runs/score-impl-t2-20261030/baseline_probe.py --reps 3 [--cases ...] [--budget auto]
"""
import argparse, json, os, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
BAT = ROOT / "bigcases/battery"
CASES = ["b01-loose","b02-m512","b03-m256","b04-m96","b05-maxmb","b06-maxmb-tight","b07-mixed",
         "b08-narrow","b09-small-e","b10-high-k","b11-short-l","b12-compute-bound","b13-balanced-compute"]

def one(inp, out, budget):
    cmd = [sys.executable, "solver/solve_all.py", str(inp), str(out)]
    if budget: cmd += ["--budget", str(budget)]
    t0 = time.monotonic()
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=str(ROOT)))
    wall = time.monotonic() - t0
    if p.returncode != 0:
        return {"ok": False, "exit": p.returncode, "wall_s": round(wall,3), "err": (p.stderr or p.stdout)[-300:]}
    ev = subprocess.run([sys.executable, "-m", "judge", "eval", "--json", str(inp), str(out)],
                        cwd=ROOT, capture_output=True, text=True)
    d = json.loads(ev.stdout)
    g = d.get("groups") or []
    peak = max(((x["mexp"]+x["movl"]+x["mact"])/x["limit"] for x in g), default=0.0)
    return {"ok": d["ok"], "time": d["time"], "lb": d["lb"], "grid": d["grid"], "K": d["K"],
            "wall_s": round(wall,3), "peak_ratio": round(peak,4), "n_err": len(d["errors"])}

ap = argparse.ArgumentParser(); ap.add_argument("--reps", type=int, default=3)
ap.add_argument("--cases", nargs="*", default=CASES); ap.add_argument("--budget", default="auto")
ap.add_argument("--out", required=True); a = ap.parse_args()
budget = None if a.budget == "auto" else float(a.budget)
od = Path(a.out); (od/"out").mkdir(parents=True, exist_ok=True)
rows=[]
for name in a.cases:
    reps=[]
    for r in range(a.reps):
        reps.append(one(BAT/f"{name}.in", od/"out"/f"{name}.r{r}.out", budget))
    times=[x.get("time") for x in reps if x.get("ok")]
    rows.append({"case":name,"reps":reps,"min":min(times) if times else None,"max":max(times) if times else None,
                 "spread":(max(times)/min(times)) if times else None, "all_ok": len(times)==len(reps)})
    print(f"{name}: {sorted(times)} wall={[x['wall_s'] for x in reps]}", file=sys.stderr, flush=True)
(od/"probe.json").write_text(json.dumps({"budget":a.budget,"reps":a.reps,"rows":rows}, indent=2))
