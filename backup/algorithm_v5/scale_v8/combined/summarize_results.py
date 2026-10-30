#!/usr/bin/env python3
import csv, math, statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "algorithm_v5/results/scale_v8_default"
V8_FILE = RESULTS / "summary.tsv"
BOUND_FILE = ROOT / "algorithm_v5/scale_v8/profile/refined_bounds.tsv"

def rows(path):
    with path.open() as f:
        return list(csv.DictReader(f, delimiter="\t"))

v8 = {r["case"]: r for r in rows(V8_FILE)}
bounds = rows(BOUND_FILE)
out = []
for b in bounds:
    name = b["case"]
    r = v8[name]
    v7 = int(b["Time"]); old = int(b["old_placement_time"])
    new = int(r["v8_time"]); py = int(b["official_python_base_time"])
    lb = int(b["refined_global_LB"]); rc = int(r["exit"])
    nops = int(b["Nops"])
    nops_bucket = "<1k Nops" if nops < 1000 else "1-2k Nops" if nops < 2000 else "2-5k Nops" if nops < 5000 else ">=5k Nops"
    out.append({
        "case": name, "official_python": py, "old_placement": old, "v7": v7, "v8": new,
        "v7_to_v8_reduction_pct": 100*(v7-new)/v7,
        "old_to_v7_reduction_pct": 100*(old-v7)/old,
        "old_to_v8_reduction_pct": 100*(old-new)/old,
        "v7_over_v8_speedup": v7/new, "old_over_v8_speedup": old/new,
        "refined_global_LB": lb, "v8_theoretical_headroom_pct": 100*(new-lb)/new,
        "v7_time_bucket": b["time_bucket"], "v7_Nops": nops, "v7_Nops_bucket": nops_bucket,
        "wall_seconds": float(r["wall_seconds"]), "exit": rc,
    })

fields = list(out[0])
with (RESULTS / "comparison.tsv").open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
    w.writeheader(); w.writerows(out)

def gm(xs): return math.exp(sum(math.log(x) for x in xs)/len(xs))
def summary(items):
    v7p = [r["v7_to_v8_reduction_pct"] for r in items]
    oldp = [r["old_to_v8_reduction_pct"] for r in items]
    v7s = [r["v7_over_v8_speedup"] for r in items]
    olds = [r["old_over_v8_speedup"] for r in items]
    return {
        "n": len(items), "v7_to_v8_mean_reduction_pct": statistics.mean(v7p),
        "v7_to_v8_median_reduction_pct": statistics.median(v7p), "v7_to_v8_worst_reduction_pct": min(v7p),
        "v7_strict_wins": sum(r["v8"] < r["v7"] for r in items), "v7_ties": sum(r["v8"] == r["v7"] for r in items),
        "v7_losses": sum(r["v8"] > r["v7"] for r in items),
        "v7_over_v8_mean_speedup": statistics.mean(v7s), "v7_over_v8_median_speedup": statistics.median(v7s),
        "v7_over_v8_geomean_speedup": gm(v7s), "mean_v7_time": statistics.mean(r["v7"] for r in items),
        "mean_v8_time": statistics.mean(r["v8"] for r in items), "median_v8_time": statistics.median(r["v8"] for r in items),
        "old_to_v8_mean_reduction_pct": statistics.mean(oldp), "old_to_v8_median_reduction_pct": statistics.median(oldp),
        "old_to_v8_worst_reduction_pct": min(oldp), "old_over_v8_geomean_speedup": gm(olds),
        "old_strict_wins": sum(r["v8"] < r["old_placement"] for r in items),
        "old_ties": sum(r["v8"] == r["old_placement"] for r in items),
        "old_losses": sum(r["v8"] > r["old_placement"] for r in items),
        "official_python_over_v8_geomean_speedup": gm([r["official_python"]/r["v8"] for r in items]),
        "max_wall_seconds": max(r["wall_seconds"] for r in items),
        "nonzero_exit_count": sum(r["exit"] != 0 for r in items),
    }

stats = summary(out)
with (RESULTS / "metrics.tsv").open("w") as f:
    f.write("metric\tvalue\n")
    for k,v in stats.items(): f.write(f"{k}\t{v:.6f}\n" if isinstance(v,float) else f"{k}\t{v}\n")

for field, order in (("v7_time_bucket", ["<5M","5-10M","10-30M",">=30M"]),
                     ("v7_Nops_bucket", ["<1k Nops","1-2k Nops","2-5k Nops",">=5k Nops"])):
    with (RESULTS / ("time_buckets.tsv" if field == "v7_time_bucket" else "nops_buckets.tsv")).open("w") as f:
        f.write("bucket\tn\tv7_to_v8_mean_pct\tv7_to_v8_median_pct\tv7_to_v8_worst_pct\tv7_over_v8_geomean\told_to_v7_mean_pct\told_to_v7_median_pct\told_to_v8_mean_pct\told_to_v8_median_pct\tmean_v8_headroom_pct\n")
        for bucket in order:
            subset = [r for r in out if r[field] == bucket]
            if not subset: continue
            p=[r["v7_to_v8_reduction_pct"] for r in subset]
            q=[r["old_to_v8_reduction_pct"] for r in subset]
            v7q=[r["old_to_v7_reduction_pct"] for r in subset]
            f.write(f"{bucket}\t{len(subset)}\t{statistics.mean(p):.6f}\t{statistics.median(p):.6f}\t{min(p):.6f}\t{gm([r['v7_over_v8_speedup'] for r in subset]):.6f}\t{statistics.mean(v7q):.6f}\t{statistics.median(v7q):.6f}\t{statistics.mean(q):.6f}\t{statistics.median(q):.6f}\t{statistics.mean(r['v8_theoretical_headroom_pct'] for r in subset):.6f}\n")
