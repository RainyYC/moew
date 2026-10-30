"""只读探针：验证"把 PSI 换成 nmb 的整数倍切点"能否把填充型用例压到下方解析界。

背景（见 REPORT.md §3）：当**单个卡组的层太轻**、作业数只有 nmb 时，流水线是按
"mb" 推进的，Time = (nmb+V−1) × seg。题面 §3.1 的 PSI 只要求**严格递增**，不要求等分，
K=V 时每个块对应一个卡组。取块长 m = 使 `m × seg` 为 nmb 的整数倍的整数，就能让
每个卡组在一层之后开始下一层，Time 降到 nmb × seg（K=V 可达到的下界）。

本脚本在**不改生产代码**的前提下，用 solver 自己的 `sched.schedule` 重放：
  * 等分切点（生产口径）：V = L，块长 L/V；
  * 非等分切点：块长 m = L/V ± 若干，使 (m × seg) % nmb 最小；
对每个 (P,V) 组合比较两套切点的 Time 与内存，并用 solver 的 `memory_usage` 复核。

命令：
    PYTHONPATH=. python3 runs/score-strategy-20261030/probe_psi_alignment.py \
        > runs/score-strategy-20261030/probe_psi_alignment.json
"""
from __future__ import annotations

import json
import sys
import time

from solver import formula, sched
from solver.casein import parse_case
from solver.solve import _pmap, _plan, enumerate_configs

CASES = ["b02-m512", "b03-m256", "b04-m96", "b08-narrow", "b10-high-k", "b07-mixed",
         "b13-balanced-compute", "b12-compute-bound", "b01-loose"]


def group_seg(case, info, layers):
    """一个卡组的 seg = max(ΣC, ΣWc)（逐层相加）。"""
    comp = sum(sum(info.durations[l][i] for i in formula.COMP_OPS) for l in layers)
    comm = sum(sum(info.durations[l][i] for i in formula.COMM_OPS) for l in layers)
    return max(comp, comm), comp, comm


def aligned_cuts(case, V, chunk):
    """把 L 层切成 V 块，块长在 [chunk-2, chunk+2] 之间取，尽量让每个块长 × seg 对齐 nmb。"""
    out = []
    remaining = case.L
    cursor = 0
    for block in range(V - 1):
        left_blocks = V - 1 - block
        lo = max(1, remaining - left_blocks * (chunk + 2))
        hi = min(chunk + 2, remaining - left_blocks * 1)
        out.append((lo, hi, cursor))
        cursor += chunk
        remaining -= chunk
    return out


def build_cuts(case, chunk, V):
    """尽量把块长取成 chunk（V-1 个内部切点），返回切点列表（长度 V-1）。"""
    cuts = []
    pos = 0
    for block in range(V - 1):
        pos += chunk
        cuts.append(pos)
    if cuts and cuts[-1] < case.L and len(cuts) == V - 1:
        return tuple(cuts)
    return None


def evaluate(case, info, V, cuts, W, mode, fill, variant_idx=0):
    psi_full = (0,) + cuts + (case.L,)
    layers = [list(range(psi_full[i], psi_full[i + 1])) for i in range(len(psi_full) - 1)]
    plan = formula.build_plan_from_parts(
        case, V, info.P, 1, cuts, info.rows, info.m, info.x, info.payload, info.durations
    )
    started = time.monotonic()
    res = sched.schedule(case, plan, W, sched.VARIANTS[variant_idx], mode, fill_gaps=fill)
    spent = time.monotonic() - started
    if res is None:
        return None
    ok, groups = sched.memory_usage(case, plan, res.start, res.end)
    return {"time": res.time, "mem_ok": ok, "seconds": round(spent, 3),
            "block_sizes": [psi_full[i + 1] - psi_full[i] for i in range(len(psi_full) - 1)],
            "lb": plan.lb}


def main():
    out = []
    for name in CASES:
        case = parse_case(f"bigcases/battery/{name}.in")
        configs, pmaps = enumerate_configs(case)
        cfg = configs[0]
        info = pmaps[cfg.P]
        V = cfg.V
        rows = []
        if case.L % V:
            out.append({"case": name, "skipped": "L % V != 0"})
            continue
        chunk0 = case.L // V
        seg0 = group_seg(case, info, list(range(0, chunk0)))[0]
        for chunk in sorted({max(1, chunk0 + d) for d in (-3, -2, -1, 0, 1, 2, 3)}):
            cuts = build_cuts(case, chunk, V)
            if cuts is None or len(set(cuts)) != len(cuts) or max(cuts) >= case.L:
                continue
            best = None
            for W in sorted({case.nmb, max(1, case.nmb // 2)}):
                for mode in ("prio", "early"):
                    r = evaluate(case, info, V, cuts, W, mode, True)
                    if r is None:
                        continue
                    if best is None or (r["mem_ok"], -r["time"]) > (best["mem_ok"], -best["time"]):
                        best = dict(r, W=W, mode=mode)
                    if best["mem_ok"] and r["mem_ok"] and r["time"] <= best["time"]:
                        best = dict(r, W=W, mode=mode)
            if best is None:
                continue
            seg = group_seg(case, info, list(range(0, chunk)))[0]
            # 块长 × seg 对 nmb 的对齐余数：0 表示每块结束时都能接上下一个 mb
            align = (chunk * seg) % case.nmb if case.nmb else None
            rows.append({"chunk": chunk, "V": V, "P": info.P, "seg_per_layer": seg,
                         "chunk_x_seg": chunk * seg, "align_remainder": align,
                         "optimal_blocks": (chunk * seg) // case.nmb if case.nmb else None,
                         **best})
        rows.sort(key=lambda r: (not r["mem_ok"], r["time"]))
        out.append({"case": name, "P": cfg.P, "V": V, "nmb": case.nmb,
                    "even_chunk": chunk0, "even_seg": seg0,
                    "rows": rows[:8]})
        sys.stderr.write(f"done {name}\n")
        sys.stderr.flush()
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
