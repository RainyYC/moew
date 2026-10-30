"""t4 离线联合探索：P × V × 切层 ψ（含非均匀切层）× 窗口 × priority → 真实调度 → 官方 grader。

**只读**：不 import 生产 `solver.solve` 的搜索路径，只用 `casein / formula / place / psi / sched`
（纯函数 + 调度器）自己拼候选；生产源码零改动。

候选生成
--------
* P：`solve.p_candidates`（合法 P 全集：P∣E、P∣R、P∣S 或 S∣P）；
* V：vmax 与 vmax 的 3/4、1/2、1/3、1/4（去重；并要求 V ≤ L、V·P ≤ R、
  每卡组层数 × (E/P·Z + Zs) ≤ M —— 否则 Mexp 静态就超限，这属于**合法性**，不是剪枝）；
* ψ：现有 `psi.psi_candidates`（dp_split2 / 只计算 / 只通信 / 均分 / 均分±1）
  + 新增的**非均匀**切层族（见 `extra_splits`）：按 fnb / bwd / chain 权重做 DP 最小化，
  用来检验"前向与反向耗时不对称时，层应该按什么分"。

排序只是启发式
--------------
`(nmb+V−1)/nmb × max_v max(ΣC, ΣWc)` 只用来**挑先跑谁**，不作合法剪枝、不称下界。

真机检验
--------
每个候选按 (窗口, priority 顺序) 真跑 `sched.schedule`，`memory_usage` 必须通过，
然后渲染成题面格式交给**官方 grader.py** 判 TIME。

用法：
    PYTHONPATH=. python3 runs/score-explore-v-t4-20261030/explore_psi.py \
        --cases x16_vl_trap4_ramp,x14_lr_twochunk_p15 --max-per-case 1.0 --top 6
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from solver import casein, formula, place, psi as psi_mod, sched  # noqa: E402
from solver.solve import p_candidates  # noqa: E402  （纯枚举函数，无状态）

PROB = ROOT / "official/extracted/Problem"
GRADER = PROB / "grader.py"
WORK = ROOT / "runs/score-explore-v-t4-20261030"


def _prefix(v):
    out = [0]
    s = 0
    for x in v:
        s += x
        out.append(s)
    return out


def _dp_max(L, V, weights):
    pre = _prefix(weights)
    INF = float("inf")
    dp = [[INF] * (L + 1) for _ in range(V + 1)]
    dp[0][0] = 0
    for v in range(1, V + 1):
        for i in range(v, L + 1):
            best = INF
            for j in range(v - 1, i):
                cand = max(dp[v - 1][j], pre[i] - pre[j])
                if cand < best:
                    best = cand
            dp[v][i] = best
    return dp[V][L]


def _split_by(L, V, weights):
    """贪心/DP 回溯出切点（最小化 max 段权重）。"""
    pre = _prefix(weights)
    INF = float("inf")
    dp = [[INF] * (L + 1) for _ in range(V + 1)]
    back = [[0] * (L + 1) for _ in range(V + 1)]
    dp[0][0] = 0
    for v in range(1, V + 1):
        for i in range(v, L + 1):
            for j in range(v - 1, i):
                cand = max(dp[v - 1][j], pre[i] - pre[j])
                if cand < dp[v][i]:
                    dp[v][i] = cand
                    back[v][i] = j
    cuts, i = [], L
    for v in range(V, 0, -1):
        j = back[v][i]
        if v > 1:
            cuts.append(j)
        i = j
    return tuple(sorted(cuts))


def extra_splits(case, P, V, durations):
    """非均匀切层族：按"前向段 / 反向段 / 层内链"三组权重各做 DP。"""
    if V <= 1:
        return [()]
    fwd, bwd, chain = [], [], []
    for l in range(case.L):
        d = durations[l]
        fwd.append(d[0] + d[1] + d[2] + d[3])            # s disp gemm comb
        bwd.append(d[4] + d[5] + d[6] + d[7] + d[8] + d[9])
        chain.append(max(d[0], d[1]) + d[2] + d[3] + d[5] + d[6] + d[8])
    out = []
    for w in (fwd, bwd, chain, [max(f, b) for f, b in zip(fwd, bwd)]):
        cuts = _split_by(case.L, V, w)
        if len(cuts) == V - 1:
            out.append(cuts)
    return out


def group_walls(case, P, V, cuts, durations, per_layer_bytes):
    psi_full = (0,) + tuple(cuts) + (case.L,)
    layers = formula.group_layers(V, psi_full)
    if any(len(g) * per_layer_bytes > case.M for g in layers):
        return None
    comp = [sum(sum(durations[l][i] for i in formula.COMP_OPS) for l in g) for g in layers]
    comm = [sum(sum(durations[l][i] for i in formula.COMM_OPS) for l in g) for g in layers]
    return max(max(c, w) for c, w in zip(comp, comm)), layers


def evaluate(case, P, V, cuts, info, per_layer_bytes, wall_s):
    """真跑调度；返回 (best, cost) 或 None。"""
    got = group_walls(case, P, V, cuts, info.durations, per_layer_bytes)
    if got is None:
        return None
    pred, layers = got
    try:
        plan = formula.build_plan_from_parts(case, V, P, 1, tuple(cuts), info.rows, info.m,
                                             info.x, info.payload, info.durations)
    except ValueError:
        return None
    # 窗口候选：nmb 与 nmb/1,2,4,8,16（真实调度时窗口影响很大，不能只靠预测）
    windows = sorted({max(1, case.nmb // k) for k in (1, 2, 4, 8, 16)}, reverse=True)
    best = None
    spent = 0.0
    modes = ("prio", "early") if case.n_ops <= 200_000 else ("prio",)
    for W in windows:
        for mode in modes:
            for vi, variant in enumerate(sched.VARIANTS[:4] if mode == "prio" else sched.VARIANTS[:2]):
                if spent > wall_s:
                    break
                t0 = time.monotonic()
                res = sched.schedule(case, plan, W, variant, mode)
                spent += time.monotonic() - t0
                if res is None:
                    continue
                ok, groups = sched.memory_usage(case, plan, res.start, res.end)
                if not ok:
                    continue
                if best is None or res.time < best["time"]:
                    peak = max(g.used / case.M for g in groups)
                    best = {"time": res.time, "W": W, "mode": mode, "variant": vi,
                            "peak": round(peak, 4), "pred": pred, "res": res, "plan": plan,
                            "layers": [len(g) for g in layers], "cuts": tuple(cuts)}
    return best, spent


def grader(case_path, text, tag):
    out = WORK / "out" / f"{case_path.stem}.{tag}.out"
    out.write_text(text)
    g = subprocess.run([sys.executable, str(GRADER), str(case_path), str(out)],
                       capture_output=True, text=True, timeout=60)
    line = (g.stdout or "").strip().splitlines()
    line = line[-1].strip() if line else ""
    return (int(line) if line.isdigit() else None), line[:120], out


def explore(name, max_per_case, top, rel_cands):
    case_path = PROB / "cases" / f"{name}.txt"
    case = casein.parse_case(case_path)
    rows = []
    for P in p_candidates(case):
        if case.R % P:
            continue
        info = solve_pmap(case, P)
        per_layer = (case.E // P) * case.Z + case.Zs
        vmax = min(case.L, 64, case.R // P)
        vs = {vmax, max(1, vmax * 3 // 4), max(1, vmax // 2), max(1, vmax // 3), max(1, vmax // 4)}
        for V in sorted(v for v in vs if 1 <= v <= case.L and v * P <= case.R):
            if case.L % V:
                # 非均分也能切，这里只排除 V>L 或静态内存超限（在 group_walls 里）
                pass
            comp_w = [sum(info.durations[l][i] for i in formula.COMP_OPS) for l in range(case.L)]
            comm_w = [sum(info.durations[l][i] for i in formula.COMM_OPS) for l in range(case.L)]
            splits = list(psi_mod.psi_candidates(case.L, V, comp_w, comm_w))
            for cuts in extra_splits(case, P, V, info.durations):
                if cuts not in splits:
                    splits.append(cuts)
            for cuts in splits:
                got = group_walls(case, P, V, cuts, info.durations, per_layer)
                if got is None:
                    continue
                pred, _layers = got
                est = pred * (case.nmb + V - 1) // case.nmb
                if rel_cands:  # 只保留预测排名靠前的候选，控制真跑次数
                    rows.append({"P": P, "V": V, "cuts": list(cuts), "est": est})
    if rel_cands:
        rows.sort(key=lambda r: r["est"])
        rows = rows[: rel_cands]
    out = []
    for r in rows:
        t0 = time.monotonic()
        got = evaluate(case, r["P"], r["V"], tuple(r["cuts"]), solve_pmap(case, r["P"]),
                       (case.E // r["P"]) * case.Z + case.Zs, max_per_case)
        cost = time.monotonic() - t0
        if not got or not got[0]:
            out.append({**r, "status": "no-legal-schedule", "cost_s": round(cost, 2)})
            continue
        best, _ = got
        text = sched.render_output(case, best["plan"], best["res"], solve_pmap(case, r["P"]).rows)
        gtime, detail, path = grader(case_path, text, f"P{r['P']}V{r['V']}_{'_'.join(map(str, r['cuts']))}")
        out.append({**r, "status": "ok" if gtime is not None else "grader-invalid",
                    "grader_time": gtime, "detail": detail if gtime is None else "",
                    "sched_time": best["time"], "W": best["W"], "mode": best["mode"],
                    "variant": best["variant"], "peak": best["peak"],
                    "layers": best["layers"], "cost_s": round(cost, 2), "out": str(path)})
    out.sort(key=lambda r: (r.get("grader_time") is None, r.get("grader_time") or 0))
    return {"case": name, "L": case.L, "nmb": case.nmb, "E": case.E, "R": case.R,
            "n_ops": case.n_ops, "top": out[:top], "n": len(out)}


def solve_pmap(case, P):
    rows, m = place.best_placement(case, P)
    pin, pout = formula.peer_counts(case, 1, P)
    payload = [formula.comm_payload(case, l, P) for l in range(case.L)]
    x = [formula.comm_time(case, payload[l], pin, pout) for l in range(case.L)]
    durations = [formula.layer_durations(case, l, m[l], x[l]) for l in range(case.L)]
    return type("PM", (), {"rows": rows, "m": m, "x": x, "payload": payload,
                           "durations": durations, "pin": pin, "pout": pout})()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", required=True)
    ap.add_argument("--max-per-case", type=float, default=1.0)
    ap.add_argument("--top", type=int, default=6)
    ap.add_argument("--cands", type=int, default=40)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    res = []
    for name in a.cases.split(","):
        r = explore(name.strip(), a.max_per_case, a.top, a.cands)
        res.append(r)
        print(json.dumps({"case": r["case"], "n": r["n"], "best": r["top"][0] if r["top"] else None},
                         ensure_ascii=False), flush=True)
    Path(a.out).write_text(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
