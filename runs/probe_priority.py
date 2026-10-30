import time
from solver.casein import parse_case
from solver.solve import enumerate_configs, _plan
from solver import sched
for name in ('b01-loose','b12-compute-bound','b02-m512'):
    c=parse_case('bigcases/battery/'+name+'.in'); configs,pm=enumerate_configs(c); cfg=configs[0]; p=_plan(c,pm[cfg.P],cfg)
    for kind in range(5):
        rank=[]
        for mb in range(c.nmb):
            for l in range(c.L):
                for op in range(10):
                    if kind==0: key=(int(op in (7,9)),mb,l,op)
                    elif kind==1: key=(int(op in (7,9)), int(op<4),mb,-l,op)
                    elif kind==2: key=(int(op in (7,9)),mb+ (l if op<4 else 2*c.L-l),op)
                    elif kind==3: key=(int(op in (7,9)),mb-l,op)
                    else: key=(int(op in (7,9)),mb+l,op)
                    rank.append(key)
        t=time.monotonic(); r=sched.schedule(c,p,c.nmb,sched.VARIANTS[0],'prio',priority=rank,fill_gaps=True)
        ok,_=sched.memory_usage(c,p,r.start,r.end)
        print(name,kind,r.time,ok,len(sched.check_schedule(c,p,r)),round(time.monotonic()-t,3),flush=True)
