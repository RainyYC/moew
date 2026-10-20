#!/usr/bin/env python3
"""退化形态自测：每个形态至少一个自造用例，求解后用 `python3 -m judge eval` 判定合法。

覆盖的退化形态（任务书要求）
--------------------------
| 形态 | 用例 | 断言 |
| --- | --- | --- |
| ``V=1``（单 stage） | `r1.in`、`v1_l1.in` | 输出网格 ``V=1`` |
| ``L=1``（单层） | `v1_l1.in` | 输入 ``L=1`` 且输出 ``V=1`` |
| ``P=1`` 零通信 | `p1_zero_comm.in` | 输出 ``P=1``（EP 组无对端 ⇒ ``X=0, x=0``） |
| ``x=0`` | `p1_zero_comm.in`、`x0_zero_payload.in` | ``P=1`` 或 ``T=0``（``X=0``）；后者 Time=0 |
| ``s=0`` | `s0.in`（``Fs=0``）、`x0_zero_payload.in`（``T=0``） | 输入 ``Fs=0`` / 全零载荷 |
| ``R=1``（单卡） | `r1.in` | 输入 ``N=S=1`` 且输出 ``V=P=D=1`` |
| ``nmb=2`` | `nmb2.in`（``V=2`` 双 stage） | 输入 ``nmb=2`` 且输出 ``V=2`` |

除合法性外，还核对**求解器自算 Time == judge 判定 Time**（两套公式实现一致性的证据）；
不一致会显式报出来（见 `solver/NOTES.md`）。

用法：``python3 solver/selftests/run.py [--quiet] [--budget 5]``
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from solver import casein, judgedbridge, solve  # noqa: E402

#: 用例 → (形态标签, 断言(case, solution) -> bool)
CHECKS: dict[str, tuple[list[str], object]] = {
    "v1_l1": (
        ["V=1", "L=1"],
        lambda case, sol: case.L == 1 and sol.V == 1 and sol.P * sol.D == case.R,
    ),
    "p1_zero_comm": (
        ["P=1", "x=0"],
        lambda case, sol: sol.P == 1 and case.E % 3 == 0 and sol.V * sol.P * sol.D == case.R,
    ),
    "x0_zero_payload": (
        ["x=0", "s=0", "全零时长"],
        lambda case, sol: all(total == 0 for total in case.T) and sol.time == 0,
    ),
    "s0": (
        ["s=0"],
        lambda case, sol: case.Fs == 0 and sol.time >= 0,
    ),
    "r1": (
        ["R=1", "V=1", "P=1"],
        lambda case, sol: case.R == 1 and (sol.V, sol.P, sol.D) == (1, 1, 1),
    ),
    "nmb2": (
        ["nmb=2", "V=2"],
        lambda case, sol: case.nmb == 2 and sol.V == 2 and sol.P == 2,
    ),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="求解器退化形态自测（含 judge 复核）")
    parser.add_argument("--quiet", action="store_true", help="只打印结论")
    parser.add_argument("--budget", type=float, default=5.0, help="单例求解墙钟预算（秒）")
    parser.add_argument("--no-judge", action="store_true", help="跳过 judge 复核（仅自检）")
    args = parser.parse_args(argv)

    inputs = sorted(_HERE.glob("*.in"))
    if not inputs:
        print(f"[selftests] {_HERE} 下没有 .in 用例", file=sys.stderr)
        return 1
    if not args.quiet:
        print(f"退化形态自测：{len(inputs)} 个用例（judge 复核={'开' if not args.no_judge else '关'}）")
    failures: list[str] = []
    for path in inputs:
        name = path.stem
        labels, check = CHECKS.get(name, (["（未登记形态）"], lambda case, sol: True))
        case = casein.parse_case(path)
        started = time.monotonic()
        solution = solve.solve_case(case, budget=args.budget)
        solve_s = time.monotonic() - started
        if solution is None:
            failures.append(f"{name}: 没有找到合法映射")
            print(f"  {name:16s} 求解失败", file=sys.stderr)
            continue
        out_path = path.with_suffix(".out")
        out_path.write_text(solution.text, encoding="utf-8")
        verdict: dict = {"ok": True, "time": solution.time, "lb": solution.lb}
        if not args.no_judge:
            try:
                verdict = judgedbridge.judge_eval(path, out_path)
            except judgedbridge.JudgeError as exc:
                failures.append(f"{name}: judge CLI 不可用：{exc}")
                print(f"  {name:16s} judge 不可用：{exc}", file=sys.stderr)
                continue
        ok = bool(verdict.get("ok"))
        judge_time = verdict.get("time")
        consistent = judge_time == solution.time
        shape_ok = bool(check(case, solution))
        if not ok:
            failures.append(f"{name}: judge 判定非法 {verdict.get('errors')}")
        if not consistent:
            failures.append(f"{name}: 自算 Time={solution.time} 与 judge {judge_time} 不一致")
        if not shape_ok:
            failures.append(f"{name}: 没有落到预期退化形态 {labels}")
        if not args.quiet:
            mark = "OK" if (ok and consistent and shape_ok) else "FAIL"
            print(
                f"  {name:16s} V={solution.V} P={solution.P} D={solution.D} K={solution.K} "
                f"psi={list(solution.psi)} W={solution.window} "
                f"Time={solution.time} (judge {judge_time}, lb={solution.lb}) "
                f"solve={solve_s:.2f}s  形态={','.join(labels)} [{mark}]"
            )
    if failures:
        print(f"[selftests] 失败 {len(failures)} 项：", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1
    if not args.quiet:
        print(f"[selftests] {len(inputs)} 个退化形态全部合法（judge 复核通过）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
