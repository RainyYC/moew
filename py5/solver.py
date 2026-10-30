"""solver.cpp 的逐行 Python 移植。

目的：把「同一算法换语言」的差距量出来——算法侧全部照抄（同样的候选集、同样的
剪枝、同样的调度器），只把 C++ 换成纯 Python，然后逐例比较
（a）输出 Time 是否完全相同（b）墙钟慢多少倍。

用法：
    python3 solver.py <case.txt> [out.txt] [--baseline] [--force-p=N] [--time-cap=秒]

`--time-cap` 是本移植新增的**测量用**开关：C++ 版本没有时间预算（固定候选集），
纯 Python 跑不动时用它模拟"如果在 10 s 内必须交卷会损失多少"。
"""

from __future__ import annotations

import sys
import time

from event_sched import schedule as event_schedule

INF = 1 << 126
NAMES = ("s", "disp", "gemm", "comb", "s_bwd", "comb_bwd",
         "gemm_dx", "gemm_dw", "disp_bwd", "s_dw")


def cd(a: int, b: int) -> int:
    """向上取整除法（a>=0, b>0），与 C++ 的 (a+b-1)/b 一致。"""
    return (a + b - 1) // b


class In:
    __slots__ = ("N", "S", "M", "Bi", "Bo", "L", "E", "Z", "Zs", "U", "Ua",
                 "k", "mb", "Fs", "Fio", "Fin", "ax", "bx", "d", "b", "T", "load")


def read_input(path: str) -> In:
    x = In()
    with open(path) as f:
        tok = f.read().split()
    it = iter(tok)
    nxt = lambda: int(next(it))
    x.N = nxt(); x.S = nxt(); x.M = nxt(); x.Bi = nxt(); x.Bo = nxt()
    x.L = nxt(); x.E = nxt(); x.Z = nxt(); x.Zs = nxt(); x.U = nxt(); x.Ua = nxt()
    x.k = nxt(); x.mb = nxt(); x.Fs = nxt(); x.Fio = nxt(); x.Fin = nxt()
    x.ax = nxt(); x.bx = nxt()
    x.d = nxt(); x.b = nxt()
    x.T = []
    x.load = []
    # 每层：T_l + （可能）E 个负载。按 C++ 的规则：该行恰好有 E 个 token 才算显式负载，
    # 否则回退成 floor/rem 均分。逐行读原始文本以保留这个判定。
    lines = []
    with open(path) as f:
        raw = f.read().splitlines()
    # 头部 3 行 + 层行
    for line in raw[3:]:
        if line.strip():
            lines.append(line.strip())
    for l in range(x.L):
        parts = lines[l].split()
        T = int(parts[0])
        vals = [int(p) for p in parts[1:]]
        x.T.append(T)
        if len(vals) == x.E:
            x.load.append(vals)
        else:
            base, rem = divmod(T, x.E)
            x.load.append([base + (1 if e < rem else 0) for e in range(x.E)])
    return x


class Cand:
    __slots__ = ("P", "V", "score", "cuts", "map")

    def __init__(self):
        self.P = 0
        self.V = 0
        self.score = 0
        self.cuts = []
        self.map = []


def make_map(x: In, P: int) -> tuple[list[list[int]], int]:
    """LPT 初值 + 至多 6 轮最优配对交换（先降最大负载，再降平方和）。"""
    cap = x.E // P
    mp = [[0] * x.E for _ in range(x.L)]
    cost = 0
    for l in range(x.L):
        order = sorted(range(x.E), key=lambda e: -x.load[l][e])
        loads = [0] * P
        cnt = [0] * P
        for e in order:
            r = -1
            for j in range(P):
                if cnt[j] < cap and (r < 0 or loads[j] < loads[r]):
                    r = j
            mp[l][e] = r
            cnt[r] += 1
            loads[r] += x.load[l][e]
        total = sum(x.load[l])
        heavy = max(x.load[l]) if x.load[l] else 0
        sq = sum(v * v for v in loads)
        lower = max(heavy, cd(total, P))
        for _ in range(6):
            mx = max(loads)
            if mx == lower:
                break
            order_rank = sorted(range(P), key=lambda r: -loads[r])
            be = bf = -1
            bm, bs = mx, sq
            for a in range(x.E):
                ra = mp[l][a]
                for b in range(a + 1, x.E):
                    rb = mp[l][b]
                    if ra == rb:
                        continue
                    na = loads[ra] - x.load[l][a] + x.load[l][b]
                    nb = loads[rb] - x.load[l][b] + x.load[l][a]
                    outside = 0
                    for r in order_rank:
                        if r != ra and r != rb:
                            outside = loads[r]
                            break
                    nm = max(outside, na, nb)
                    ns = (sq - loads[ra] * loads[ra] - loads[rb] * loads[rb]
                          + na * na + nb * nb)
                    if nm < bm or (nm == bm and ns < bs):
                        bm, bs, be, bf = nm, ns, a, b
            if be < 0:
                break
            ra, rb = mp[l][be], mp[l][bf]
            loads[ra] = loads[ra] - x.load[l][be] + x.load[l][bf]
            loads[rb] = loads[rb] - x.load[l][bf] + x.load[l][be]
            mp[l][be], mp[l][bf] = mp[l][bf], mp[l][be]
            sq = bs
        cost += max(loads)
    return mp, cost


def durations(x: In, c: Cand) -> list[list[int]]:
    H = x.d * x.b // x.k
    out = []
    for l in range(x.L):
        load = [0] * c.P
        for e in range(x.E):
            load[c.map[l][e]] += x.load[l][e]
        m = max(load)
        X = cd(x.T[l] * H, c.P)
        pin = min(c.P, x.S) - 1
        pout = c.P - 1 - pin
        com = max(cd(pin * X, x.Bi), cd(pout * X, x.Bo)) * x.Fio
        g = m * x.Fin
        s = x.T[l] * x.Fs
        out.append([
            s, com, g, com,
            cd(x.ax * s, 1000000), cd(x.ax * com, 1000000),
            cd(x.ax * g, 1000000),
            cd(x.ax * x.bx * g, 1000000000000),
            cd(x.ax * com, 1000000),
            cd(x.ax * x.bx * s, 1000000000000),
        ])
    return out


class Result:
    __slots__ = ("c", "G", "K", "time", "cuts", "group", "ops")

    def __init__(self):
        self.c = None
        self.G = 0
        self.K = 0
        self.time = INF
        self.cuts = []
        self.group = []
        self.ops = []


def evaluate(x: In, c: Cand, rich: bool, deep: bool,
             deadline: float | None = None) -> Result:
    best = Result()
    best.c = c
    dur = durations(x, c)
    base_group = [0] * x.L
    for g in range(c.V):
        for l in range(c.cuts[g], c.cuts[g + 1]):
            base_group[l] = g

    def test_layout(lg, cuts, K, G):
        nonlocal best
        if deadline is not None and time.monotonic() > deadline:
            return
        ng = [0] * G
        for g in lg:
            ng[g] += 1
        windows = [1, 2, G, 2 * G, 0] if rich else [0]
        windows = sorted(set(windows))
        for one in range(0, (1 if rich else 0) + 1):
            caps = [0] * G
            buf = [0] * G
            ok = True
            for g in range(G):
                zero = True
                for l in range(x.L):
                    if lg[l] == g and (dur[l][1] or dur[l][3] or dur[l][5] or dur[l][8]):
                        zero = False
                        break
                bbuf = 0 if zero else 1
                if rich and not one and not zero:
                    two = x.M - ng[g] * ((x.E // c.P) * x.Z + x.Zs) - 2 * x.U
                    if two >= 0 and two // x.Ua >= ng[g]:
                        bbuf = 2
                avail = x.M - ng[g] * ((x.E // c.P) * x.Z + x.Zs) - (0 if zero else bbuf * x.U)
                if avail < 0:
                    ok = False
                    break
                caps[g] = min(avail // x.Ua, x.mb * ng[g])
                buf[g] = bbuf
                if caps[g] < ng[g]:
                    ok = False
                    break
            if not ok:
                continue
            mmax = 2 if rich else 0
            for mode in range(mmax + 1):
                for w in windows:
                    ops, tm = event_schedule(x.mb, x.L, G, lg, dur, ng, caps, buf, w, mode)
                    if ops is not None and tm < best.time:
                        best.time = tm
                        best.G = G
                        best.K = K
                        best.cuts = list(cuts)
                        best.group = list(lg)
                        best.ops = ops

    test_layout(base_group, c.cuts, c.V, c.V)
    if rich and deep:
        maxG = min(x.L // 2, x.N * x.S // c.P)
        gs = set()
        for g in (maxG, min(maxG, c.V), max(1, min(maxG, c.V // 2))):
            if 1 <= g <= maxG:
                gs.add(g)
        for G in sorted(gs):
            K = 2 * G
            cuts = [x.L * j // K for j in range(K + 1)]
            group = [0] * x.L
            for j in range(K):
                g = j if j < G else 2 * G - 1 - j
                for l in range(cuts[j], cuts[j + 1]):
                    group[l] = g
            test_layout(group, cuts, K, G)
        if best.time < INF:
            lw = [sum(dur[l]) for l in range(x.L)]
            order = [j for j in range(1, best.K) if 0 < best.cuts[j] < x.L]
            order.sort(key=lambda a: -abs(lw[best.cuts[a] - 1] - lw[best.cuts[a]]))
            seed = list(best.cuts)
            K, G = best.K, best.G
            tried = 0
            for j in order:
                for delta in (-1, 1):
                    cuts = list(seed)
                    cuts[j] += delta
                    ok = True
                    for z in range(1, K):
                        if cuts[z] <= cuts[z - 1] or cuts[z] >= cuts[z + 1]:
                            ok = False
                            break
                    if not ok:
                        continue
                    group = [0] * x.L
                    for bl in range(K):
                        g = bl if K == G else (bl if bl < G else 2 * G - 1 - bl)
                        for l in range(cuts[bl], cuts[bl + 1]):
                            group[l] = g
                    test_layout(group, cuts, K, G)
                tried += 1
                if tried >= 3:
                    break
    if best.time >= INF:
        # 保底：完整串行
        best.G = c.V
        best.K = c.V
        best.cuts = c.cuts
        best.group = base_group
        best.time = sum(d + 1 for l in range(x.L) for d in dur[l]) * x.mb
    return best


def main(argv):
    serial = False
    force_p = 0
    time_cap = None
    out_path = None
    inp = None
    for a in argv:
        if a == "--baseline":
            serial = True
        elif a.startswith("--force-p="):
            force_p = int(a.split("=", 1)[1])
        elif a.startswith("--time-cap="):
            time_cap = float(a.split("=", 1)[1])
        elif out_path is None and inp is not None:
            out_path = a
        elif inp is None:
            inp = a
    t0 = time.monotonic()
    deadline = (t0 + time_cap) if time_cap else None
    x = read_input(inp)
    R = x.N * x.S
    H = x.d * x.b // x.k

    pcs = []
    for P in range(1, min(R, x.E) + 1):
        if (force_p and P != force_p) or x.E % P or (x.S % P and P % x.S):
            continue
        mp, mapcost = make_map(x, P)
        q = (x.E // P) * x.Z + x.Zs
        zero_comms = True
        pref = [0] * (x.L + 1)
        for l in range(x.L):
            X = cd(x.T[l] * H, P)
            pin = min(P, x.S) - 1
            pout = P - 1 - pin
            com = max(cd(pin * X, x.Bi), cd(pout * X, x.Bo)) * x.Fio
            g = cd(x.T[l], P) * x.Fin
            s = x.T[l] * x.Fs
            if com:
                zero_comms = False
            pref[l + 1] = (pref[l] + 4 * com + 2 * g + 2 * s
                           + 2 * cd(x.ax * com, 1000000)
                           + cd(x.ax * g, 1000000)
                           + cd(x.ax * x.bx * g, 1000000000000)
                           + cd(x.ax * s, 1000000)
                           + cd(x.ax * x.bx * s, 1000000000000))
        pc = {"P": P, "bestV": None, "maxV": None, "maxV_time": INF}
        best_score = INF
        vmax = min(x.L, 64, R // P)
        for V in range(1, vmax + 1):
            dp = [[INF] * (x.L + 1) for _ in range(V + 1)]
            par = [[-1] * (x.L + 1) for _ in range(V + 1)]
            dp[0][0] = 0
            for j in range(1, V + 1):
                for i in range(j, x.L - (V - j) + 1):
                    for h in range(j - 1, i):
                        if dp[j - 1][h] >= INF:
                            continue
                        cost = (i - h) * (q + x.Ua) + (0 if zero_comms else x.U)
                        if cost > x.M:
                            continue
                        val = max(dp[j - 1][h], pref[i] - pref[h])
                        if val < dp[j][i]:
                            dp[j][i] = val
                            par[j][i] = h
            if dp[V][x.L] >= INF:
                continue
            c = Cand()
            c.P = P
            c.V = V
            c.score = dp[V][x.L] * 1000000 + mapcost
            c.map = mp
            c.cuts = [0] * (V + 1)
            c.cuts[V] = x.L
            at = x.L
            ok = True
            for j in range(V, 0, -1):
                h = par[j][at]
                if h < 0:
                    ok = False
                    break
                c.cuts[j - 1] = h
                at = h
            if not ok:
                continue
            if c.score < best_score:
                best_score = c.score
                pc["bestV"] = c
            pc["maxV"] = c
        if pc["maxV"] is not None:
            pcs.append(pc)
    if not pcs:
        print("no feasible config", file=sys.stderr)
        return 2

    probes = []
    for pc in pcs:
        if deadline is not None and time.monotonic() > deadline:
            r = Result(); r.c = pc["maxV"]; r.time = INF; r.G = pc["maxV"].V
            r.K = pc["maxV"].V; r.cuts = pc["maxV"].cuts
            r.group = [0] * x.L; r.ops = []
        else:
            r = evaluate(x, pc["maxV"], False, False, deadline)
        pc["maxV_time"] = r.time
        probes.append(r)
    winner = 0
    for i in range(1, len(probes)):
        if probes[i].time < probes[winner].time:
            winner = i
    best = probes[winner]
    if not serial:
        order = sorted(range(len(pcs)), key=lambda i: probes[i].time)
        if order[0] != winner:
            w = order.index(winner)
            order[0], order[w] = order[w], order[0]
        for j in range(min(2, len(order))):
            pid = order[j]
            c = pcs[pid]["bestV"] if pcs[pid]["bestV"] is not None else pcs[pid]["maxV"]
            r = evaluate(x, c, True, j == 0, deadline)
            if r.time < best.time:
                best = r

    lines = [f"{best.G} {best.c.P}", "PSI",
             " ".join(str(v) for v in [best.K] + list(best.cuts[1:best.K]))]
    lines.append("MAP")
    for row in best.c.map:
        lines.append(" ".join(str(v) for v in row))
    lines.append("SCHEDULE")
    if serial:
        dur = durations(x, best.c)
        t = 0
        for mb in range(x.mb):
            for l in range(x.L):
                for op in (0, 1, 2, 3):
                    lines.append(f"{t} {mb}:{l}:{NAMES[op]}")
                    t += dur[l][op] + 1
            for l in range(x.L - 1, -1, -1):
                for op in (5, 4, 6, 8, 7, 9):
                    lines.append(f"{t} {mb}:{l}:{NAMES[op]}")
                    t += dur[l][op] + 1
    else:
        for start, mb, l, op in best.ops:
            lines.append(f"{start} {mb}:{l}:{NAMES[op]}")
    text = "\n".join(lines) + "\n"
    if out_path:
        with open(out_path, "w") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    print(f"Time={best.time} V={best.G} P={best.c.P} K={best.K} "
          f"wall={time.monotonic()-t0:.2f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
