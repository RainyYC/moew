"""只读实验：窗口 W（在飞 microbatch 数）对 Time 的影响。

题面**不强制** 1F1B/DUALPIPE 这类固定窗口——§4.2 只给了依赖与引擎互斥，任何满足
四条规则的排法都合法。求解器里的 `sched.schedule(window=W)` 是自加约束，它的作用
只是把 `Mact`（前向已完成、反向未进行的 (mb,ℓ) 数）压住。所以：

* **W 只有一个真实上限**：`Mact = Uact × peak ≤ M − Mexp − U`；
* 在这个上限之内，把 W 做大是**纯收益**（流水线填充 `(nmb+W−1)/W` 单调下降），
  直到 W ≥ nmb 时填充消失。

本探针在固定 (P,V,ψ,MAP) 下扫一组窗口候选，记录每个候选的 Time 与内存是否可行。
注意：`solve.py` 的 `_window_cap` 用 `spare // Uact // widest_layers` 做**保守上界**
（假设峰值激活可以同时压满一个卡组的所有层），往往把 W 剪得远小于真实可行值。

命令：
    PYTHONPATH=. python3 runs/score-strategy-20261030/probe_window_ceiling.py \
        > runs/score-strategy-20261030/probe_window_ceiling.json
"""
from __future__ import annotations

import json
import sys
import time

from solver import sched
from solver.casein import parse_case
from solver.solve import _plan, enumerate_configs

CASES = ["b01-loose", "b02-m512", "b03-m256", "b07-mixed", "b08-narrow",
         "b10-high-k", "b12-compute-bound", "b13-balanced-compute", "ex3", "ex6"]


def path_of(name):
    return f"bigcases/battery/{name}.in" if name.startswith("b") else f"cases/{name}.in"


def marginal_w(case, plan):
    """由「激活类内存上限」推出的理论最大 W：一个卡组的 Mact 至少要有一个
    (mb,ℓ) 活着；流水线里同时在飞的不超过 W 个 mb，每个 mb 在一个卡组里最多
    有 len(group) 个层同时在飞。实际峰值由调度决定，这里给出松上界。"""
    widest = max(len(g) for g in plan.layers_of_group) or 1
    per_layer = (case.E // plan.P) * case.Z + case.Zs
    mexp = max(len(g) for g in plan.layers_of_group) * per_layer
    spare = case.M - mexp - 2 * case.U
    if spare <= 0:
        return 1
    return max(1, spare // case.Uact)


def run(name):
    case = parse_case(path_of(name))
    configs, pmaps = enumerate_configs(case)
    cfg = configs[0]
    plan = _plan(case, pmaps[cfg.P], cfg)
    cap_loose = marginal_w(case, plan)
    widest = max(len(g) for g in plan.layers_of_group) or 1
    cap_conservative = max(1, cap_loose // widest)
    candidates = sorted({w for w in
                         (case.nmb, case.nmb // 2, case.nmb // 4, case.nmb // 8 if case.nmb >= 8 else 1,
                          widest, cap_conservative, cap_loose, 1)
                         if 1 <= w <= case.nmb})
    rows = []
    for W in candidates:
        best = None
        for mode in ("prio", "early"):
            started = time.monotonic()
            res = sched.schedule(case, plan, W, sched.VARIANTS[0], mode, fill_gaps=True)
            elapsed = round(time.monotonic() - started, 3)
            if res is None:
                continue
            ok, groups = sched.memory_usage(case, plan, res.start, res.end)
            row = {"W": W, "mode": mode, "time": res.time, "mem_ok": ok,
                   "peak_act": max(g.peak_act for g in groups),
                   "peak_comm": max(g.peak_comm for g in groups),
                   "mexp": groups[0].mexp, "limit": case.M, "seconds": elapsed}
            if best is None or (ok and not best["mem_ok"]) or (ok == best["mem_ok"] and res.time < best["time"]):
                best = row
        if best:
            rows.append(best)
    rows.sort(key=lambda r: (not r["mem_ok"], r["time"]))
    return {
        "case": name, "P": cfg.P, "V": cfg.V, "nmb": case.nmb,
        "cap_conservative (solve._window_cap)": cap_conservative,
        "cap_loose (spare//Uact)": cap_loose,
        "spare_bytes": case.M - max(len(g) for g in plan.layers_of_group) * ((case.E // cfg.P) * case.Z + case.Zs),
        "Uact": case.Uact, "U": case.U, "best": rows[0] if rows else None, "rows": rows,
    }


def main():
    out = []
    for name in CASES:
        out.append(run(name))
        sys.stderr.write(f"done {name}\n")
        sys.stderr.flush()
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
