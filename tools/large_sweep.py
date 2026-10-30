#!/usr/bin/env python3
"""大用例的"P 取舍曲线"：把每个合法 P 都解一遍，看我们选的网格是不是最优。

2026-10 版题面取消 D 后 V=P 唯一确定（V=R/P），于是 P 同时决定三件事：

1. 计算量：每 rank 的专家数 E/P，`gemm = m·Fin`，m 随 1/P 下降；
2. 通信量：`X = ⌈T·H/P⌉` 随 1/P 下降，但节点内/跨节点对端数 (p_in, p_out) 由 P 与 S 的关系决定；
3. 流水线深度：V=R/P，填充代价 `(nmb+V-1)/nmb` 随 P 增大而改善。

三者互相拉扯，所以"选哪个 P"不能只看下界。本脚本逐 P 求解并列表。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from solver import casein, solve, sched  # noqa: E402


def sweep(path: str, budget: float = 2.0) -> None:
    case = casein.parse_case(path)
    print(f"\n=== {Path(path).name}  R={case.R} L={case.L} E={case.E} nmb={case.nmb} "
          f"M={case.M / 2**20:.0f}MiB S={case.S} Bin={case.Bin} Bout={case.Bout}")
    print(f"{'P':>4} {'V':>4} {'x':>14} {'gemm':>8} {'pin':>4} {'pout':>5} "
          f"{'lb':>18} {'fill':>6} {'Time':>18} {'Time/lb':>8}")
    configs, pmaps = solve.enumerate_configs(case)
    by_p: dict[int, list] = {}
    for cfg in configs:
        by_p.setdefault(cfg.P, []).append(cfg)
    best = None
    for P in sorted(by_p):
        cfgs = sorted(by_p[P], key=lambda c: c.lb)
        cfg = cfgs[0]
        info = pmaps[P]
        deadline = time.monotonic() + budget
        b = solve._try_config(case, cfg, info, None, deadline, case.n_ops > 120_000, None, {"est": 0.0})
        fill = (case.nmb + cfg.V - 1) / case.nmb
        if b is None:
            print(f"{P:>4} {cfg.V:>4} {info.x[0]:>14} {info.durations[0][2]:>8} "
                  f"{info.pin:>4} {info.pout:>5} {cfg.lb:>18} {fill:>6.2f} {'无合法解':>18}")
            continue
        print(f"{P:>4} {cfg.V:>4} {info.x[0]:>14} {info.durations[0][2]:>8} "
              f"{info.pin:>4} {info.pout:>5} {cfg.lb:>18} {fill:>6.2f} {b.time:>18} "
              f"{b.time / cfg.lb:>8.2f}")
        if best is None or b.time < best[0]:
            best = (b.time, P, cfg.V, b.time / cfg.lb)
    if best:
        print(f"  → 最优 P={best[1]} V={best[2]} Time={best[0]} ({best[3]:.2f}×lb)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cases", nargs="*", default=["data/battery/b01-loose.in",
                                                "data/battery/b05-maxmb.in",
                                                "data/battery/b11-short-l.in"])
    ap.add_argument("--budget", type=float, default=2.0)
    args = ap.parse_args()
    for path in args.cases:
        sweep(path, args.budget)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
