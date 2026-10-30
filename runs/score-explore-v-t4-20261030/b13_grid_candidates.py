"""t4：把 b13 的**全部合法配置**（P,V,ψ）逐一真跑（不受搜索预算/顺序影响），
回答"4.298e16 是否真实可达、要哪个 P/V/ψ"，用于区分"不限预算潜力"与"10 s 内可实现"。

只读冻结快照（runs/score-explore-v-t4-20261030/snapshot/），不写生产；
每个配置用固定 (窗口 × mode × variant) 真跑调度，内存过 → 渲染 → **官方 grader** 判 TIME。

用法：PYTHONPATH=. python3 runs/score-explore-v-t4-20261030/b13_grid_candidates.py \
        --per-config-wall 6 --out runs/score-explore-v-t4-20261030/probe/b13-grid.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runs/score-explore-v-t4-20261030/snapshot"))
sys.path.insert(1, str(ROOT))
from solver import casein, sched, solve  # noqa: E402

CASE = ROOT / "bigcases/battery/b13-balanced-compute.in"
WORK = ROOT / "runs/score-explore-v-t4-20261030"


def grade(text, tag):
    out = WORK / "out" / f"b13.grid.{tag}.out"
    out.write_text(text)
    g = subprocess.run([sys.executable, str(ROOT / "official/extracted/Problem/grader.py"),
                        str(CASE), str(out)], capture_output=True, text=True)
    line = (g.stdout or "").strip().splitlines()
    line = line[-1].strip() if line else ""
    return (int(line) if line.isdigit() else None), str(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-config-wall", type=float, default=6.0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    case = casein.parse_case(CASE)
    configs, pmaps = solve.enumerate_configs(case)
    windows = sorted({case.nmb, case.nmb // 2, case.nmb // 4, case.nmb // 8}, reverse=True)
    rows = []
    for cfg in configs:
        info = pmaps[cfg.P]
        plan = solve._plan(case, info, cfg)
        t0 = time.monotonic()
        best = None
        for W in windows:
            if time.monotonic() - t0 > a.per_config_wall:
                break
            for mode in ("early", "prio"):
                for vi, variant in enumerate(sched.VARIANTS[:4]):
                    if time.monotonic() - t0 > a.per_config_wall:
                        break
                    res = sched.schedule(case, plan, W, variant, mode)
                    if res is None:
                        continue
                    ok, groups = sched.memory_usage(case, plan, res.start, res.end)
                    if not ok:
                        continue
                    if best is None or res.time < best["time"]:
                        best = {"time": res.time, "W": W, "mode": mode, "variant": vi,
                                "peak": round(max(g.used / case.M for g in groups), 4), "res": res}
        spent = round(time.monotonic() - t0, 2)
        row = {"P": cfg.P, "V": cfg.V, "psi": list(cfg.psi), "lb": cfg.lb, "search_s": spent}
        if best is not None:
            text = sched.render_output(case, plan, best["res"], info.rows)
            gtime, out = grade(text, f"P{cfg.P}V{cfg.V}_{len(rows)}")
            row.update({"time": best["time"], "grader_time": gtime, "W": best["W"],
                        "mode": best["mode"], "variant": best["variant"],
                        "peak": best["peak"], "out": out})
        else:
            row["time"] = None
        rows.append(row)
        print(json.dumps({k: row.get(k) for k in ("P", "V", "psi", "lb", "search_s", "time", "grader_time", "W", "mode")},
                         ensure_ascii=False), flush=True)
    rows.sort(key=lambda r: (r.get("grader_time") is None, r.get("grader_time") or 0))
    Path(a.out).write_text(json.dumps(rows, indent=1))
    print("BEST:", json.dumps({k: rows[0].get(k) for k in ("P", "V", "psi", "lb", "W", "mode", "variant", "time", "grader_time", "search_s")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
