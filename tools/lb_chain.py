#!/usr/bin/env python3
"""更紧的下界：引擎工作量下界 + 「反向回传链」（内网报告 §5.4A.1 的构造）。

    lb_chain(V,ψ) = nmb·max_v seg_v  +  Σ_{v=1..V-1} min_{ℓ∈stage v} disp_bwd(ℓ)

引擎项 = 各卡组的稳态占用；链项 = 最后一个 microbatch 的反向必须逐 stage 回穿
`V−1 → 0`，每跨一跳都要等该 stage 某层的 `disp_bwd` 完成（取该 stage 内**最小**值
是安全方向）。

用途**只是估算距离**：判分不用它。自检：对每个用例必须 `lb_chain ≤ Time`，
否则构造无效（脚本会打印违反项）。

用法：
    python3 tools/lb_chain.py                 # 官方 50 例（需要 official/outs/*.out）
    python3 tools/lb_chain.py --top 15
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from judge.core.evaluate import evaluate  # noqa: E402
from judge.core.parse import parse_case, parse_output  # noqa: E402
from solver import formula, solve  # noqa: E402

CASES = ROOT / "official/extracted/Problem/cases"
OUTS = ROOT / "official/outs"


def bound(case, text: str) -> tuple[int, int, int] | None:
    """返回 ``(Time, lb_engine, lb_chain)``；解非法时返回 None。"""
    result = evaluate(case, text)
    if not result["ok"]:
        return None
    out = parse_output(text)
    info = solve._pmap(case, out.P)
    plan = formula.build_plan_from_parts(
        case, out.V, out.P, 1, out.psi,
        info.rows, info.m, info.x, info.payload, info.durations,
    )
    chain = 0
    for index, layers in enumerate(plan.layers_of_group):
        if index == 0:
            continue
        chain += min(plan.durations[layer][formula.OP_DISP_BWD] for layer in layers)
    return result["time"], plan.lb, plan.lb + chain


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=12, help="打印距离最大的前 N 例")
    args = ap.parse_args(argv)

    rows = []
    for out in sorted(OUTS.glob("*.out")):
        case_path = CASES / f"{out.stem}.txt"
        if not case_path.exists():
            continue
        got = bound(parse_case(case_path), (OUTS / out.name).read_text(encoding="utf-8"))
        if got is None:
            print(f"{out.stem}: 解非法，跳过", file=sys.stderr)
            continue
        time, lb, chain = got
        rows.append((time / chain, time / lb, out.stem, time, lb, chain))

    violations = [row for row in rows if row[4] > row[3]]
    if violations:
        print(f"!! 链下界无效：{len(violations)} 例 Time < lb_chain")
        for row in violations[:5]:
            print("   ", row[2], row[3], "<", row[5])

    print(f"{'T/lb_chain':>10} {'T/lb':>6} {'用例':32s} {'Time':>13} {'lb_chain':>13}")
    for row in sorted(rows, reverse=True)[: args.top]:
        print(f"{row[0]:10.2f} {row[1]:6.2f} {row[2]:32s} {row[3]:>13d} {row[5]:>13d}")
    print()
    print(f"中位数 T/lb = {statistics.median(r[1] for r in rows):.3f}"
          f"  →  T/lb_chain = {statistics.median(r[0] for r in rows):.3f}")
    for cut in (1.10, 1.20, 1.50):
        count = sum(1 for r in rows if r[0] <= cut)
        print(f"  T/lb_chain ≤ {cut:.2f}: {count}/{len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
