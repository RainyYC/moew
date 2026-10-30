import json, time
from pathlib import Path
from solver.casein import parse_case
from solver.solve import enumerate_configs, _plan
from solver import sched

def main():
    records=[]
    for path in sorted(Path('bigcases/battery').glob('*.in')):
        case=parse_case(path)
        configs, pmaps=enumerate_configs(case)
        cfg=configs[0]; plan=_plan(case, pmaps[cfg.P], cfg)
        for mode in ('prio','early'):
            for fill in (False,True):
                t=time.monotonic()
                result=sched.schedule(case,plan,case.nmb,sched.VARIANTS[0],mode,fill_gaps=fill)
                ok, groups=sched.memory_usage(case,plan,result.start,result.end)
                errors=sched.check_schedule(case,plan,result)
                row=dict(case=path.stem,mode=mode,fill=fill,time=result.time,legal=ok,errors=len(errors),seconds=round(time.monotonic()-t,3))
                records.append(row); print(json.dumps(row),flush=True)
    Path('runs/probe_gap_fill.json').write_text(json.dumps(records,indent=2))
if __name__=='__main__': main()
