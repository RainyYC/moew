"""把三份官方 50 例结果逐例对拍：t2-base / t2-cur / 本次验证 cur。
用途：检验 t2 的"base 与 cur 逐例相同、几何比 1.000000"能否独立复现。"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

def load(p):
    return {r["case"]: r for r in json.loads(Path(p).read_text())["rows"]}

t2b = load(common.ROOT / "runs/score-impl-t2-20261030/official50-base/result.json")
t2c = load(common.ROOT / "runs/score-impl-t2-20261030/official50-cur/result.json")
mine = load(common.OUTDIR / "official/cur/result.json")
rows, diffs_cmp, diffs_mine = [], [], []
for name in sorted(mine):
    a, b, c = t2b.get(name, {}), t2c.get(name, {}), mine[name]
    r = {"case": name, "t2_base": a.get("time"), "t2_cur": b.get("time"), "val_cur": c.get("time"),
         "t2_status": (a.get("status"), b.get("status")), "val_status": c.get("status")}
    if a.get("time") and c.get("time"):
        r["val_over_t2base"] = round(c["time"] / a["time"], 6)
    if b.get("time") and c.get("time"):
        r["val_over_t2cur"] = round(c["time"] / b["time"], 6)
    rows.append(r)
    if a.get("time") != b.get("time"):
        diffs_cmp.append(name)
    if b.get("time") != c.get("time"):
        diffs_mine.append(name)
ok = [r for r in rows if r.get("val_over_t2base")]
summary = {
    "n": len(rows),
    "t2_base_vs_t2_cur_differ": diffs_cmp,
    "t2_cur_vs_val_cur_differ": diffs_mine,
    "geomean_val_over_t2base": common.geomean([r["val_over_t2base"] for r in ok]),
    "geomean_val_over_t2cur": common.geomean([r["val_over_t2cur"] for r in ok]),
    "rows": rows,
}
(common.OUTDIR / "official/compare-vs-t2.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False))
print("max |val-t2cur| rel:", max(abs(r["val_over_t2cur"] - 1) for r in ok))
