import time
from solver.casein import parse_case
from solver.solve import enumerate_configs, _plan
from solver import sched

for name in ('b02-m512','b03-m256','b04-m96','b07-mixed','b08-narrow','b13-balanced-compute'):
    c=parse_case('bigcases/battery/'+name+'.in')
    configs, pmaps=enumerate_configs(c)
    cfg=configs[0]; plan=_plan(c,pmaps[cfg.P],cfg)
    windows=sorted(set([c.nmb,c.nmb//2,c.nmb//4,c.nmb//8,32,16,8,4,2,1]),reverse=True)
    print('CASE',name,'P',cfg.P,'V',cfg.V,flush=True)
    best=None
    for w in windows:
        if w<1 or w>c.nmb: continue
        for mode in ('prio','early'):
            for vi,variant in enumerate(sched.VARIANTS):
                t=time.monotonic(); r=sched.schedule(c,plan,w,variant,mode,fill_gaps=True)
                ok,_=sched.memory_usage(c,plan,r.start,r.end)
                if ok and (best is None or r.time<best[0]):
                    best=(r.time,w,mode,vi)
                    print('BEST',name,*best,'elapsed',round(time.monotonic()-t,3),flush=True)
    print('FINAL',name,best,flush=True)
