"""对 b10/b13/b12/b01 的生产解算更紧的链下界 lb_chain（tools/lb_chain.py 的同一构造），
判断"b10 的 1.523×填充界"是不是真的还有空间（只读，不调度）。

用法：PYTHONPATH=. python3 runs/score-validation-20261030/scripts/lbchain_battery.py
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
from judge.core.evaluate import evaluate  # noqa: E402
from judge.core.parse import parse_case, parse_output  # noqa: E402
from solver import formula, place, solve  # noqa: E402

ALT = {"b10-high-k": [(64, 2), (32, 4), (16, 4), (8, 4), (32, 8)]}
CASES = ["b01-loose", "b05-maxmb", "b09-small-e", "b10-high-k", "b12-compute-bound", "b13-balanced-compute"]

def bound(case, text, pinned=None):
    """pinned=(V,P)：按指定网格重算下界（用于"当时的最佳网格"对照）。"""
    result = evaluate(case, text)
    if not result["ok"]:
        return None
    out = parse_output(text)
    V, P = (pinned if pinned else (out.V, out.P))
    psi = out.psi if pinned is None else [round(case.L * k / V) for k in range(1, V)]
    info = solve._pmap(case, P)
    plan = formula.build_plan_from_parts(case, V, P, 1, psi,
                                         info.rows, info.m, info.x, info.payload, info.durations)
    chain = 0
    for index, layers in enumerate(plan.layers_of_group):
        if index == 0:
            continue
        chain += min(plan.durations[layer][formula.OP_DISP_BWD] for layer in layers)
    return result["time"], plan.lb, plan.lb + chain, {"V": out.V, "P": out.P}

def main() -> int:
    rows = []
    for name in CASES:
        outp = common.OUTDIR / "battery/b13b12/outs" / f"{name}.cur.r0.out"
        if not outp.exists():
            continue
        case = parse_case(common.ROOT / f"bigcases/battery/{name}.in")
        got = bound(case, outp.read_text(encoding="utf-8"))
        if got is None:
            rows.append({"case": name, "illegal": True}); continue
        t, lb, chain, grid = got
        alt = {}
        for (V, P) in ALT.get(name, []):
            o = bound(case, outp.read_text(encoding="utf-8"), pinned=(V, P))
            if o:
                alt[f"V{V}P{P}"] = {"lb": o[1], "lb_chain": o[2]}
        rows.append({"case": name, "time": t, "lb": lb, "lb_chain": chain,
                     "T_over_lb": round(t / lb, 4), "T_over_lb_chain": round(t / chain, 4), "grid": grid,
                     "alt_grids": alt})
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    (common.OUTDIR / "battery/lbchain.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
