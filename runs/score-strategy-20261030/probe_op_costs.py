"""只读计时探针：单次 `sched.schedule` 的墙钟 × 窗口，以及"在 10 s 上限内能试多少次"。

用途：评估改进项（多种子并行、更多窗口/变体、序列退火）的**时间可行性**。
所有数字都在本机（12 核、Python 3.14）实测，不写任何生产文件。

命令：
    PYTHONPATH=. python3 runs/score-strategy-20261030/probe_op_costs.py
"""
from __future__ import annotations

import json
import time

from solver import sched
from solver.casein import parse_case
from solver.solve import _plan, enumerate_configs

CASES = ["b01-loose", "b02-m512", "b05-maxmb", "b07-mixed", "b10-high-k",
         "b12-compute-bound", "b13-balanced-compute"]


def path_of(name):
    return f"bigcases/battery/{name}.in"


def main():
    out = []
    for name in CASES:
        case = parse_case(path_of(name))
        configs, pmaps = enumerate_configs(case)
        cfg = configs[0]
        plan = _plan(case, pmaps[cfg.P], cfg)
        for W in sorted({case.nmb, max(1, case.nmb // 2), max(1, case.nmb // 8)}):
            for mode in ("prio", "early"):
                started = time.monotonic()
                res = sched.schedule(case, plan, W, sched.VARIANTS[0], mode,
                                     priority=None, fill_gaps=True)
                spent = time.monotonic() - started
                ok = res is not None
                out.append({"case": name, "n_ops": case.n_ops, "W": W, "mode": mode,
                            "seconds": round(spent, 3), "ok": ok,
                            "n_schedules_in_10s": int(10 / spent) if spent > 0 else None})
        # 渲染一次输出文本的耗时（落盘体积也在 10 s 预算里）
        if out and out[-1]["ok"]:
            res = sched.schedule(case, plan, case.nmb, sched.VARIANTS[0], "prio", fill_gaps=True)
            started = time.monotonic()
            text = sched.render_output(case, plan, res, pmaps[cfg.P].rows)
            spent = time.monotonic() - started
            out.append({"case": name, "render_seconds": round(spent, 3), "bytes": len(text)})
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
