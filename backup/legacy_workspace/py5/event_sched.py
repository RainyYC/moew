"""event_scheduler.hpp 的逐行 Python 移植（用于度量 C++ 带来的真实收益）。

语义与原实现一致：激活额度预约准入、通信缓冲 b_g∈{0,1,2}、三种优先级模式、
零时长操作同刻闭包、s_bwd 开始后 t+1 归还预约。

注意：本模块**不做**任何性能优化（不搞 C 扩展、不用 numpy），就是要量出
"同一算法换语言"的真实差距。
"""

from __future__ import annotations

import heapq

# op 顺序：0=s 1=disp 2=gemm 3=comb 4=s_bwd 5=comb_bwd 6=gemm_dx 7=gemm_dw 8=disp_bwd 9=s_dw
COMM_OPS = (1, 3, 5, 8)


def engine(op: int) -> int:
    return 1 if op in COMM_OPS else 0


def _priority_item(l: int, op: int, mb: int, idx: int, mode: int, tail: int):
    """返回 ReadyItem 的堆键（数值越小越先出堆）。

    对应 C++ 的 ReadyLater 比较器：
      p0 升序；mode!=0 时 tail 降序；其余 (p1,p2,p3,node) 升序。
    """
    if op == 4:
        p = 0
    elif op == 6:
        p = 1
    elif op == 8:
        p = 2
    elif op == 5:
        p = 3
    elif op in (0, 1):
        p = 5 if l == 0 else 4
    elif op in (2, 3):
        p = 4
    else:  # 7, 9
        p = 6
    layer_order = -l if op in (4, 5, 6, 8) else l
    if mode == 1:
        reverse = 0 if op in (4, 5, 6, 8) else (2 if op in (7, 9) else 1)
        return (reverse, -tail, mb, layer_order, op, idx)
    if mode == 2:
        if engine(op) == 1:
            coarse = 0 if op in (3, 8) else 1
        elif op in (0, 2, 4, 6):
            coarse = 0
        elif op == 5:
            coarse = 1
        elif op in (7, 9):
            coarse = 3
        else:
            coarse = 2
        return (coarse, -tail, mb, layer_order, op, idx)
    return (p, 0, mb, layer_order, op, idx)


def schedule(mb, L, G, layer_group, dur, group_layers, activation_capacity,
             comm_buffers, window, mode=0):
    """返回 (ops, makespan)；ops 为 [(start, mb, l, op)]，与 C++ 同序。

    与 C++ 的差异仅在于：非法输入返回 (None, None)。
    """
    if mb < 0 or L <= 0 or G <= 0 or len(layer_group) != L or len(dur) != L:
        return None, None
    if len(group_layers) != G or len(activation_capacity) != G or len(comm_buffers) != G:
        return None, None
    total = mb * L * 10
    if total > 2147483647:
        return None, None
    for g in range(G):
        if group_layers[g] < 0 or activation_capacity[g] < group_layers[g]:
            return None, None
        if comm_buffers[g] < 0 or comm_buffers[g] > 2:
            return None, None
    actual = [0] * G
    for l in range(L):
        if layer_group[l] < 0 or layer_group[l] >= G:
            return None, None
        actual[layer_group[l]] += 1
        for o in range(10):
            if dur[l][o] < 0:
                return None, None
    if actual != list(group_layers):
        return None, None
    for g in range(G):
        if comm_buffers[g] == 0:
            for l in range(L):
                if layer_group[l] == g and (dur[l][1] or dur[l][3] or dur[l][5] or dur[l][8]):
                    return None, None
    if mode not in (0, 1, 2):
        return None, None

    N = total
    stride = L * 10

    # 出边表：用扁平 list 的 list（与 C++ 一致）
    out_edges = [[] for _ in range(N)]
    indeg = [0] * N
    mb_of = [0] * N
    l_of = [0] * N
    op_of = [0] * N
    for m in range(mb):
        for l in range(L):
            base = (m * L + l) * 10
            for o in range(10):
                mb_of[base + o] = m
                l_of[base + o] = l
                op_of[base + o] = o

    def edge(a, b):
        out_edges[a].append(b)
        indeg[b] += 1

    for m in range(mb):
        for l in range(L):
            base = (m * L + l) * 10
            edge(base + 1, base + 2)
            edge(base + 2, base + 3)
            edge(base + 0, base + 3)
            edge(base + 3, base + 4)
            edge(base + 3, base + 5)
            edge(base + 5, base + 6)
            edge(base + 5, base + 7)
            edge(base + 5, base + 9)
            edge(base + 6, base + 8)
            edge(base + 4, base + 8)
            if l > 0:
                prev = (m * L + l - 1) * 10
                edge(prev + 3, base + 0)
                edge(prev + 3, base + 1)
            if l + 1 < L:
                nxt = (m * L + l + 1) * 10
                edge(nxt + 8, base + 4)
                edge(nxt + 8, base + 5)

    # bottom-level（每个 microbatch 相同，只在 mb=0 上算一次）
    bottom = [0] * N
    if mode in (1, 2) and mb > 0:
        sys_setrecursion = 20000
        import sys as _sys
        old = _sys.getrecursionlimit()
        _sys.setrecursionlimit(max(old, sys_setrecursion))
        seen = [False] * (L * 10)

        def calc(idx):
            local = idx % stride
            if seen[local]:
                return bottom[idx]
            seen[local] = True
            child = 0
            for v in out_edges[idx]:
                cv = calc(v)
                if cv > child:
                    child = cv
            bottom[idx] = dur[l_of[idx]][op_of[idx]] + child
            return bottom[idx]

        for idx in range(stride):
            calc(idx)
        for m in range(1, mb):
            base = m * stride
            for local in range(stride):
                bottom[base + local] = bottom[local]

    ready = [[] for _ in range(2 * G)]
    remaining = list(activation_capacity)
    done_mb = [0] * mb
    mb_active = [False] * mb
    busy = [False] * (2 * G)
    last_comm_start = [0] * G
    last_comm_end = [0] * G
    has_comm = [False] * G
    events = []          # (t, kind, node, group)
    node_done = [False] * N
    out = []
    makespan = 0
    next_mb = 0
    active_mb = 0
    finished = 0
    W = window if window > 0 else mb

    def make_ready(idx):
        l = l_of[idx]
        op = op_of[idx]
        g = layer_group[l]
        heapq.heappush(ready[2 * g + engine(op)],
                       _priority_item(l, op, mb_of[idx], idx, mode, bottom[idx]))

    def try_admit():
        nonlocal next_mb, active_mb
        changed = False
        while next_mb < mb and active_mb < W:
            ok = True
            for g in range(G):
                if remaining[g] < group_layers[g]:
                    ok = False
                    break
            if not ok:
                break
            for g in range(G):
                remaining[g] -= group_layers[g]
            m = next_mb
            next_mb += 1
            active_mb += 1
            mb_active[m] = True
            changed = True
            base = m * stride
            for idx in range(base, base + stride):
                if indeg[idx] == 0:
                    make_ready(idx)
        return changed

    def complete_node(idx):
        nonlocal finished, active_mb
        node_done[idx] = True
        done_mb[mb_of[idx]] += 1
        finished += 1
        for v in out_edges[idx]:
            indeg[v] -= 1
            if indeg[v] == 0:
                make_ready(v)
        if done_mb[mb_of[idx]] == stride:
            mb_active[mb_of[idx]] = False
            active_mb -= 1
            try_admit()

    def take_ready_mode2(slot, now):
        """mode==2 的取用：最多看 16 个候选，先滤掉被通信冷却挡住的。"""
        q = ready[slot]
        candidates = []
        deferred = []
        for _ in range(16):
            if not q:
                break
            item = heapq.heappop(q)
            idx = item[5]
            l = l_of[idx]
            op = op_of[idx]
            g = layer_group[l]
            blocked = False
            if slot % 2 == 1 and dur[l][op] > 0 and comm_buffers[g] != 0 and has_comm[g]:
                if comm_buffers[g] == 1:
                    allowed = last_comm_end[g] + 1
                else:
                    allowed = max(last_comm_end[g], last_comm_start[g] + 1)
                blocked = now < allowed
            (deferred if blocked else candidates).append(item)
        for item in deferred:
            heapq.heappush(q, item)
        if not candidates:
            return -1
        best = 0
        best_score = 100
        for k, item in enumerate(candidates):
            idx = item[5]
            l = l_of[idx]
            op = op_of[idx]
            g = layer_group[l]
            if engine(op) == 0:
                if (op == 0 and node_done[idx + 2]) or (op == 2 and node_done[idx - 2]):
                    sc = 0
                elif op == 4:
                    if node_done[idx + 2]:
                        sc = 0
                    elif (next_mb < mb and active_mb < W and group_layers[g] > 0
                          and remaining[g] < 2 * group_layers[g]):
                        sc = 1
                    else:
                        sc = 3
                elif op == 6 and node_done[idx - 2]:
                    sc = 0
                elif op in (5, 8):
                    sc = 2
                elif op in (7, 9):
                    sc = 5
                else:
                    sc = 3
            else:
                sc = 0 if op in (3, 8) else 1
            # 比较器：score 小者优先；同分时 tail 大者优先；再按 p1（=mb）
            if sc < best_score or (sc == best_score and (
                    candidates[k][1] < candidates[best][1] or
                    (candidates[k][1] == candidates[best][1] and
                     candidates[k][2] < candidates[best][2]))):
                best = k
                best_score = sc
        chosen = candidates[best][5]
        for k, item in enumerate(candidates):
            if k != best:
                heapq.heappush(q, item)
        return chosen

    try_admit()
    now = 0
    while finished < N:
        did_event = False
        while events and events[0][0] == now:
            t, kind, node, group = heapq.heappop(events)
            did_event = True
            if kind == 0:
                l = l_of[node]
                busy[2 * layer_group[l] + engine(op_of[node])] = False
                complete_node(node)
            else:
                remaining[group] = min(activation_capacity[group], remaining[group] + 1)
                try_admit()

        started_any = False
        zero_started = False
        for g in range(G):
            for e in range(2):
                slot = 2 * g + e
                while not busy[slot] and ready[slot]:
                    idx = ready[slot][0][5]
                    l = l_of[idx]
                    op = op_of[idx]
                    d = dur[l][op]
                    if mode != 2 and e == 1 and d > 0 and comm_buffers[g] != 0 and has_comm[g]:
                        if comm_buffers[g] == 1:
                            allowed = last_comm_end[g] + 1
                        else:
                            allowed = max(last_comm_end[g], last_comm_start[g] + 1)
                        if now < allowed:
                            break
                    if mode == 2:
                        idx = take_ready_mode2(slot, now)
                        if idx < 0:
                            break
                        l = l_of[idx]
                        op = op_of[idx]
                        d = dur[l][op]
                    else:
                        heapq.heappop(ready[slot])
                    end = now + d
                    out.append((now, mb_of[idx], l, op))
                    if end > makespan:
                        makespan = end
                    started_any = True
                    if e == 1 and d > 0 and comm_buffers[g] != 0:
                        has_comm[g] = True
                        last_comm_start[g] = now
                        last_comm_end[g] = end
                    if op == 4:
                        heapq.heappush(events, (now + 1, 1, -1, g))
                    if d == 0:
                        zero_started = True
                        complete_node(idx)
                    else:
                        busy[slot] = True
                        heapq.heappush(events, (end, 0, idx, -1))
                        break
        if finished >= N:
            break
        if zero_started:
            continue

        ready_now = False
        for s in range(2 * G):
            if busy[s] or not ready[s]:
                continue
            g = s // 2
            e = s % 2
            top_l = l_of[ready[s][0][5]]
            top_op = op_of[ready[s][0][5]]
            if e == 0 or dur[top_l][top_op] == 0 or comm_buffers[g] == 0 or not has_comm[g]:
                ready_now = True
                break
            if comm_buffers[g] == 1:
                allow = last_comm_end[g] + 1
            else:
                allow = max(last_comm_end[g], last_comm_start[g] + 1)
            if allow <= now:
                ready_now = True
                break
        if ready_now:
            continue

        has_next = False
        nxt = 0
        if events:
            nxt = events[0][0]
            has_next = True
        for g in range(G):
            s = 2 * g + 1
            if busy[s] or not ready[s] or comm_buffers[g] == 0 or not has_comm[g]:
                continue
            top = ready[s][0][5]
            if dur[l_of[top]][op_of[top]] <= 0:
                continue
            if comm_buffers[g] == 1:
                allow = last_comm_end[g] + 1
            else:
                allow = max(last_comm_end[g], last_comm_start[g] + 1)
            if allow > now and (not has_next or allow < nxt):
                nxt = allow
                has_next = True
        if not has_next or nxt < now:
            return None, None
        if nxt == now and not did_event and not started_any:
            return None, None
        now = nxt

    out.sort()
    if len(out) != N:
        return None, None
    return out, makespan
