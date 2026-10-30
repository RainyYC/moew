import heapq
import time, random
from sim import Input, validate, op_durations, OP_ENGINE

OPS = ['s', 'disp', 'gemm', 'comb', 's_bwd', 'comb_bwd', 'gemm_dx', 'gemm_dw', 'disp_bwd', 's_dw']
ENG = [0 if OP_ENGINE[o] == 'comp' else 1 for o in OPS]


def build_meta(inp, cfg):
    V, P, psi, map_rows, durs, ml = cfg
    L = inp.L
    nmb = inp.nmb
    two = 1 if len(psi) - 1 == 2 * V else 0
    K = 2 * V if two else V

    def gk(k):
        return k if not two else (k if k < V else 2 * V - 1 - k)

    stage_of = [0] * L
    layers_in_stage = [[] for _ in range(V)]
    for k in range(K):
        gg = gk(k)
        for l in range(psi[k], psi[k + 1]):
            stage_of[l] = gg
            layers_in_stage[gg].append(l)
    first_of_stage = [ls[0] for ls in layers_in_stage]
    return dict(V=V, P=P, psi=psi, durs=durs, ml=ml, two=two,
                stage_of=stage_of, layers_in_stage=layers_in_stage,
                first_of_stage=first_of_stage, L=L, nmb=nmb)


def extract_order(inp, cfg, sched):
    meta = build_meta(inp, cfg)
    V = meta['V']
    order = [[[] for _ in range(2)] for _ in range(V)]
    for t, ops in sched:
        for (mb, l, name) in ops:
            oi = OPS.index(name)
            v = meta['stage_of'][l]
            order[v][ENG[oi]].append((mb, l, oi))
    return order


def _init_pred(meta, W):
    """Initial predecessor counts under the updated spec 4.2 dependency model:
    s and disp are both entry ops (layer input / window only); comb waits
    gemm + s; disp_bwd waits gemm_dx + s_bwd; s_bwd and comb_bwd each wait own
    comb + next-layer disp_bwd."""
    L = meta['L']; nmb = meta['nmb']; V = meta['V']
    first_of_stage = meta['first_of_stage']
    base = L * 10; NIDX = nmb * base
    pred = [1] * NIDX
    for mb in range(nmb):
        mbi = mb * base
        wv = 0 if mb < W else 1
        pred[mbi] = wv
        pred[mbi + 1] = wv
        for v in range(1, V):
            p = 2 if mb >= W else 1
            pred[mbi + first_of_stage[v] * 10] = p
            pred[mbi + first_of_stage[v] * 10 + 1] = p
        for l in range(L):
            pred[mbi + l * 10 + 3] = 2
            pred[mbi + l * 10 + 8] = 2
        for l in range(L - 1):
            pred[mbi + l * 10 + 4] = 2
            pred[mbi + l * 10 + 5] = 2
    return pred, base


def _resim_core(inp, cfg, W, order, want_events):
    """Heap-driven replay of a per-engine order. Semantically identical to the
    original O(ops*V) full-scan version: at each step the ready head with the
    smallest start time wins, ties broken by (stage, engine) order. Only the
    head of each (stage, engine) queue is ever a candidate, so a heap of at
    most 2V entries replaces the per-step scan; newly-ready nodes are pushed
    when their last predecessor finishes. Returns (max_t, scheduled, ev)."""
    meta = build_meta(inp, cfg)
    L = meta['L']; nmb = meta['nmb']; V = meta['V']
    stage_of = meta['stage_of']; first_of_stage = meta['first_of_stage']
    layers_in_stage = meta['layers_in_stage']; two = meta['two']; durs = meta['durs']
    pred, base = _init_pred(meta, W)
    bwd_rem = [[6 * len(layers_in_stage[v]) for v in range(V)] for _ in range(nmb)]
    rt = [0] * (nmb * base)
    pos = [[0, 0] for _ in range(V)]
    efree = [[0, 0] for _ in range(V)]
    max_t = 0
    scheduled = 0
    total = sum(len(x) for vv in order for x in vv)
    ev = {} if want_events else None
    heap = []

    def head(v, e):
        p = pos[v][e]
        if p >= len(order[v][e]):
            return None
        return order[v][e][p]

    def push_if_ready(v, e):
        h = head(v, e)
        if h is None:
            return
        mb, l, oi = h
        idx = (mb * L + l) * 10 + oi
        if pred[idx] > 0:
            return
        r = rt[idx] if rt[idx] > efree[v][e] else efree[v][e]
        heapq.heappush(heap, (r, v, e, idx))

    def notify(idx):
        oi = idx % 10
        l = (idx // 10) % L
        v = stage_of[l]
        e = ENG[oi]
        h = head(v, e)
        if h is not None and (h[0] * L + h[1]) * 10 + h[2] == idx and pred[idx] == 0:
            r = rt[idx] if rt[idx] > efree[v][e] else efree[v][e]
            heapq.heappush(heap, (r, v, e, idx))

    for v in range(V):
        for e in (0, 1):
            push_if_ready(v, e)

    while heap:
        r, v, e, idx = heapq.heappop(heap)
        h = head(v, e)
        if h is None:
            continue
        mb, l, oi = h
        if (mb * L + l) * 10 + oi != idx or pred[idx] > 0:
            continue
        if rt[idx] > r:
            r = rt[idx]
        if efree[v][e] > r:
            r = efree[v][e]
        fin = r + durs[l][OPS[oi]]
        if want_events:
            ev.setdefault(r, []).append((mb, l, OPS[oi]))
        efree[v][e] = fin
        pos[v][e] += 1
        scheduled += 1
        if fin > max_t:
            max_t = fin

        def rel(pi):
            pred[pi] -= 1
            if fin > rt[pi]:
                rt[pi] = fin
            if pred[pi] == 0:
                notify(pi)

        if oi == 3:
            rel((mb * L + l) * 10 + 4)
            rel((mb * L + l) * 10 + 5)
            nl = l + 1
            if two:
                if nl < L:
                    rel((mb * L + nl) * 10)
                    rel((mb * L + nl) * 10 + 1)
            elif nl < L and stage_of[nl] == v:
                rel((mb * L + nl) * 10)
                rel((mb * L + nl) * 10 + 1)
            elif v + 1 < V:
                nl = first_of_stage[v + 1]
                rel((mb * L + nl) * 10)
                rel((mb * L + nl) * 10 + 1)
        elif oi >= 4:
            bwd_rem[mb][v] -= 1
            if bwd_rem[mb][v] == 0:
                m2 = mb + W
                if m2 < nmb:
                    nl = first_of_stage[v]
                    rel((m2 * L + nl) * 10)
                    rel((m2 * L + nl) * 10 + 1)
            if oi == 5:
                for no in (6, 7, 9):
                    rel((mb * L + l) * 10 + no)
            elif oi == 6:
                rel((mb * L + l) * 10 + 8)
            elif oi == 8:
                pl = l - 1
                if pl >= 0:
                    rel((mb * L + pl) * 10 + 4)
                    rel((mb * L + pl) * 10 + 5)
            elif oi == 4:
                rel((mb * L + l) * 10 + 8)
        else:
            if oi == 0:
                no = 3
            elif oi == 1:
                no = 2
            else:
                no = 3
            rel((mb * L + l) * 10 + no)

        push_if_ready(v, e)

    return max_t, scheduled, ev


def resim(inp, cfg, W, order):
    max_t, scheduled, _ = _resim_core(inp, cfg, W, order, False)
    total = sum(len(x) for vv in order for x in vv)
    if scheduled < total:
        return None
    return max_t


def resim_events(inp, cfg, W, order):
    """Re-simulate a per-engine order; return (events dict, makespan, scheduled)."""
    max_t, scheduled, ev = _resim_core(inp, cfg, W, order, True)
    return ev, max_t, scheduled


def copy_order(order):
    return [[list(x) for x in vv] for vv in order]


def descent(inp, cfg, W, order, rng, budget=None):
    t0 = time.time()
    cur = resim(inp, cfg, W, order)
    if cur is None:
        return order, None
    n = len(order)
    improved = True
    while improved:
        improved = False
        engines = [(v, e) for v in range(n) for e in (0, 1)
                   if len(order[v][e]) >= 2]
        rng.shuffle(engines)
        for (v, e) in engines:
            s = order[v][e]
            m = len(s)
            moves = []
            for i in range(m - 1):
                moves.append(('adj', i))
            for j in range(m):
                for i in range(max(0, j - 10), j):
                    moves.append(('ins', i, j))
            rng.shuffle(moves)
            for mv in moves:
                if budget is not None and time.time() - t0 > budget:
                    return order, cur
                if mv[0] == 'adj':
                    i = mv[1]
                    s[i], s[i + 1] = s[i + 1], s[i]
                    t2 = resim(inp, cfg, W, order)
                    if t2 is not None and t2 < cur:
                        cur = t2
                        improved = True
                        break
                    s[i], s[i + 1] = s[i + 1], s[i]
                else:
                    _, i, j = mv
                    item = s.pop(j)
                    s.insert(i, item)
                    t2 = resim(inp, cfg, W, order)
                    if t2 is not None and t2 < cur:
                        cur = t2
                        improved = True
                        break
                    item = s.pop(i)
                    s.insert(j, item)
            if improved:
                break
    return order, cur


def ils(inp, cfg, W, order, budget=6.0, seed=0):
    rng = random.Random(seed)
    best_order = copy_order(order)
    best_t = resim(inp, cfg, W, order)
    t0 = time.time()
    while time.time() - t0 < budget:
        cand = copy_order(best_order)
        k = 1 + rng.randint(1, 3)
        for _ in range(k):
            v = rng.randrange(len(cand))
            e = rng.randint(0, 1)
            s = cand[v][e]
            if len(s) < 2:
                continue
            i = rng.randrange(len(s) - 1)
            s[i], s[i + 1] = s[i + 1], s[i]
        if resim(inp, cfg, W, cand) is None:
            continue
        cand, t2 = descent(inp, cfg, W, cand, rng, budget=budget - (time.time() - t0))
        if t2 is not None and (best_t is None or t2 < best_t):
            best_order = copy_order(cand)
            best_t = t2
    return best_order, best_t, t0


def lns(inp, cfg, W, order, budget=6.0, seed=0):
    """Large-neighborhood search: repeatedly ruin one (stage,engine) queue by
    removing a contiguous burst and greedily reinserting each removed op at its
    best position, then descend. Burst destroy-repair reaches block reorderings
    that single adjacent-swap / insertion descent cannot (e.g. regrouping the
    backward chain on the compute engine), then descent polishes locally."""
    rng = random.Random(seed)
    best = copy_order(order)
    best_t = resim(inp, cfg, W, best)
    t0 = time.time()
    stall = 0
    while time.time() - t0 < budget:
        cand = copy_order(best)
        v = rng.randrange(len(cand)); e = rng.randint(0, 1)
        s = cand[v][e]
        if len(s) < 3:
            stall += 1
            if stall > 20:
                break
            continue
        q = rng.randint(2, min(8, len(s)))
        start = rng.randrange(len(s) - q + 1)
        burst = s[start:start + q]
        del s[start:start + q]
        for item in burst:
            bt = None; bi = 0
            for pos in range(len(s) + 1):
                s.insert(pos, item)
                t = resim(inp, cfg, W, cand)
                if t is not None and (bt is None or t < bt):
                    bt = t; bi = pos
                s.pop(pos)
            s.insert(bi, item)
        cand, t2 = descent(inp, cfg, W, cand, rng, budget=budget - (time.time() - t0))
        if t2 is not None and (best_t is None or t2 < best_t):
            best = copy_order(cand)
            best_t = t2
            stall = 0
        else:
            stall += 1
    return best, best_t


def refine(inp, cfg, W, sched, budget=2.0, nseed=2, max_ops=512, best_time=None,
           lns_extra=0.0):
    """Post-processing: per-engine order ILS refinement.

    Returns (events_sorted, makespan) strictly better than the input schedule
    and passing the official validator, or None if no improvement found.
    """
    L = inp.L
    nmb = inp.nmb
    if nmb * L > max_ops:
        return None
    if sched is None:
        return None
    try:
        order = extract_order(inp, cfg, sched)
    except Exception:
        return None
    total = sum(len(x) for vv in order for x in vv)
    if total != nmb * L * 10:
        return None
    if W is None or W < 1:
        bestW = None
        bestDiff = None
        for w in range(1, nmb + 1):
            bt = resim(inp, cfg, w, order)
            if bt is None:
                continue
            ref = best_time if best_time is not None else bt
            d = abs(bt - ref)
            if bestW is None or d < bestDiff:
                bestW = w
                bestDiff = d
        if bestW is None:
            return None
        W = bestW
    base_t = resim(inp, cfg, W, order)
    if base_t is None:
        return None
    best_o = None
    best_t = None
    # Established adjacent-swap ILS kernel gets its original full budget so that
    # previously-delivered solutions are reproduced unchanged.
    per = max(0.05, budget / max(1, nseed))
    for s in range(nseed):
        o2, t2, _ = ils(inp, cfg, W, copy_order(order), budget=per, seed=s)
        if t2 is not None and (best_t is None or t2 < best_t):
            best_t = t2
            best_o = o2
    # Burst destroy-repair LNS runs on an ADDITIONAL absolute slice (appended,
    # not carved out of the ILS budget), so it can only add improvements.
    if lns_extra > 0:
        # Equal split across two LNS restarts: seed 0 reaches the block reorder
        # on reverse-heavy queues, seed 1 reaches compute/fill regimes.
        per_l = max(0.05, lns_extra / 2)
        for s in range(2):
            o3, t3 = lns(inp, cfg, W, copy_order(order), budget=per_l, seed=s)
            if t3 is not None and (best_t is None or t3 < best_t):
                best_t = t3
                best_o = o3
    if best_o is None or best_t is None or best_t >= base_t:
        return None
    ev, mt, schedn = resim_events(inp, cfg, W, best_o)
    if schedn != total:
        return None
    V, P, psi, map_rows, durs, ml = cfg
    newsched = sorted(ev.items())
    vres, err = validate(inp, V, P, psi, map_rows, newsched, durs=durs)
    if err is not None or vres is None or vres >= base_t:
        return None
    return newsched, vres

