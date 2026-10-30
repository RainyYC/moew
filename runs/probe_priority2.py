import time
from solver.casein import parse_case
from solver.solve import enumerate_configs, _plan
from solver import sched


def priorities(c, kind):
    out=[]
    for mb in range(c.nmb):
        for layer in range(c.L):
            for op in range(10):
                branch = int(op in (7,9))
                if kind == 0:
                    key=(branch, mb + (layer if op < 4 else 2*c.L-layer), op)
                elif kind == 1:
                    key=(branch, mb, layer if op < 4 else -layer, op)
                elif kind == 2:
                    key=(branch, mb + (layer if op < 4 else -layer), op)
                elif kind == 3:
                    key=(branch, int(op not in (4,5,6,8)), mb + (layer if op < 4 else 2*c.L-layer), op)
                else:
                    key=(branch, mb + (layer if op < 4 else 2*c.L-layer), -op, op)
                out.append(key)
    return out

for name in ('b01-loose','b02-m512','b07-mixed','b08-narrow','b10-high-k','b12-compute-bound','b13-balanced-compute'):
    c=parse_case('bigcases/battery/'+name+'.in')
    configs, pmaps=enumerate_configs(c)
    cfg=configs[0]; plan=_plan(c, pmaps[cfg.P], cfg)
    print('CASE',name,'P',cfg.P,'V',cfg.V,'n_ops',c.n_ops,flush=True)
    for kind in range(5):
        started=time.monotonic()
        r=sched.schedule(c,plan,c.nmb,sched.VARIANTS[0],'prio',priority=priorities(c,kind),fill_gaps=True)
        ok,groups=sched.memory_usage(c,plan,r.start,r.end)
        print('RESULT',name,kind,r.time,ok,len(sched.check_schedule(c,plan,r)),round(time.monotonic()-started,3),flush=True)
