#!/usr/bin/env python3
"""Build an offline, exact schedule/DAG viewer from the official grader."""
import hashlib, importlib.util, json, re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
CASE = ROOT / 'data/official/Problem/cases/r64_v4_c4b.txt'
SCHEDULE = ROOT / 'results/retiming_speed/full50/r64_v4_c4b.out'
GRADER = ROOT / 'data/official/Problem/grader.py'
spec = importlib.util.spec_from_file_location('official_grader', GRADER)
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
inst = g.parse_instance(CASE.read_text())
m = g.parse_mapping(SCHEDULE.read_text(), inst)
time, info = g.simulate(inst, m)
dur, groups = info['dur'], info['group']
starts = {(mb,l,op): t for t,mb,l,op,_ in m.sched}
nodes = [(mb,l,op) for mb in range(inst.nmb) for l in range(inst.L) for op in g.OPS]
assert len(nodes) == len(m.sched) == 4480
pred, succ = {}, defaultdict(list)
for mb,l,op in nodes:
    ps = [(mb,pl,po) for pl,po,_ in g.op_preds(inst.L,l,op)]
    pred[(mb,l,op)] = ps
    for p in ps: succ[p].append((mb,l,op))

tasks=[]
for mb,l,op in nodes:
    d=dur[l][op]; group=groups[l]
    tasks.append({'id':f'{mb}:{l}:{op}','mb':mb,'l':l,'op':op,'group':group,
      'engine':g.ENGINE[op],'start':starts[(mb,l,op)],'duration':d,'end':starts[(mb,l,op)]+d,
      'pred':[f'{a}:{b}:{c}' for a,b,c in pred[(mb,l,op)]],
      'succ':[f'{a}:{b}:{c}' for a,b,c in succ[(mb,l,op)]]})

# Resource ordering is reconstructed by group/engine and scheduled interval;
# this edge class is explicitly separate from model dependencies.
resource_edges=[]
byres=defaultdict(list)
for x in tasks:
    if x['duration']>0: byres[(x['group'],x['engine'])].append(x)
for (v,e),xs in byres.items():
    xs.sort(key=lambda x:(x['start'],x['end'],x['mb'],x['l'],x['op']))
    for i,x in enumerate(xs):
        x['resource_prev']=xs[i-1]['id'] if i else None
        x['resource_next']=xs[i+1]['id'] if i+1<len(xs) else None
    for a,b in zip(xs,xs[1:]):
        assert a['end'] <= b['start'], (a,b)
        resource_edges.append([a['id'],b['id']])

busy=defaultdict(int)
for x in tasks: busy[(x['group'],x['engine'])]+=x['duration']
metrics=[]
for v in range(m.V):
    metrics.append({'group':v,'compute_busy':busy[(v,'C')], 'network_busy':busy[(v,'N')],
      'compute_pct':100*busy[(v,'C')]/time,'network_pct':100*busy[(v,'N')]/time})
payload={'case':'r64_v4_c4b','L':inst.L,'nmb':inst.nmb,'V':m.V,'P':m.P,'K':m.K,
 'Time':time,'tasks':tasks,'resource_edges':resource_edges,'metrics':metrics,
 'compute_average_pct':sum(x['compute_pct'] for x in metrics)/len(metrics),
 'network_average_pct':sum(x['network_pct'] for x in metrics)/len(metrics),
 'dependencies_count':sum(map(len,pred.values())),
 'resource_edges_count':len(resource_edges),'zero_duration_count':sum(x['duration']==0 for x in tasks),
 'hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (CASE,SCHEDULE,GRADER)}}
encoded=json.dumps(payload,separators=(',',':')).replace('</','<\\/')
(OUT/'trace.json').write_text(json.dumps(payload,separators=(',',':'))+'\n')
html_path=OUT/'index.html'
html=html_path.read_text()
html,n=re.subn(r'(<script id="trace-data" type="application/json">).*?(</script>)',lambda m:m.group(1)+encoded+m.group(2),html,count=1,flags=re.S)
if n!=1: raise RuntimeError('index.html must contain one trace-data script element')
html_path.write_text(html)
readme=OUT/'README.md'
if readme.exists():
    hashes='\n'.join(f"- `{path}`: `{digest}`" for path,digest in (
        ('data/official/Problem/cases/r64_v4_c4b.txt',payload['hashes'][CASE.name]),
        ('results/retiming_speed/full50/r64_v4_c4b.out',payload['hashes'][SCHEDULE.name]),
        ('data/official/Problem/grader.py',payload['hashes'][GRADER.name])))
    content=readme.read_text()
    content,n=re.subn(r'<!-- INPUT_HASHES_BEGIN -->.*?<!-- INPUT_HASHES_END -->',
                      '<!-- INPUT_HASHES_BEGIN -->\n'+hashes+'\n<!-- INPUT_HASHES_END -->',content,count=1,flags=re.S)
    if n!=1: raise RuntimeError('README.md must contain input hash markers')
    readme.write_text(content)
print(json.dumps({k:payload[k] for k in ('Time','L','nmb','V','P','K','dependencies_count','resource_edges_count','zero_duration_count','compute_average_pct','network_average_pct','metrics','hashes')},indent=2))
