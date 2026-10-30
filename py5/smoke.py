"""对照 event_scheduler_smoke.cpp 的断言，验证移植正确性。"""
import event_sched as es

def verify_dag(ops, d, mb, L):
    st = {}
    for start, m, l, op in ops:
        st[(m, l, op)] = start
    end = lambda m, l, o: st[(m, l, o)] + d[l][o]
    for m in range(mb):
        for l in range(L):
            assert st[(m,l,1)] >= 0 and st[(m,l,2)] >= end(m,l,1) and st[(m,l,3)] >= end(m,l,2)
            assert st[(m,l,3)] >= end(m,l,0)
            assert st[(m,l,4)] >= end(m,l,3) and st[(m,l,5)] >= end(m,l,3)
            assert st[(m,l,6)] >= end(m,l,5) and st[(m,l,7)] >= end(m,l,5) and st[(m,l,9)] >= end(m,l,5)
            assert st[(m,l,8)] >= end(m,l,6) and st[(m,l,8)] >= end(m,l,4)
            if l: assert st[(m,l,0)] >= end(m,l-1,3) and st[(m,l,1)] >= end(m,l-1,3)
            if l+1 < L: assert st[(m,l,4)] >= end(m,l+1,8) and st[(m,l,5)] >= end(m,l+1,8)

mb, L, G = 3, 2, 2
group = [0, 1]; ng = [1, 1]; A = [2, 2]; b = [2, 1]
d = [[2,1,2,2,1,1,1,3,1,1] for _ in range(L)]

for mode in (0, 1, 2):
    ops, t = es.schedule(mb, L, G, group, d, ng, A, b, 0, mode)
    assert ops is not None and len(ops) == mb*L*10, mode
    assert t > 0
    verify_dag(ops, d, mb, L)
    print(f"mode={mode}: ops={len(ops)} makespan={t}")

# 全零时长：必须仍然输出全部节点，且 makespan=0
d0 = [[0]*10 for _ in range(L)]
ops, t = es.schedule(2, 2, 2, group, d0, ng, A, [0, 0], 0)
assert ops is not None and len(ops) == 40 and t == 0
print(f"零时长: ops={len(ops)} makespan={t}")
print("冒烟测试全部通过")
