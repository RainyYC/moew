#!/usr/bin/env python3
"""Create a separate refined table from saved profiles; no solver runs."""
import csv, math, statistics
from pathlib import Path

HERE=Path(__file__).resolve().parent
def read(path): return list(csv.DictReader(open(path),delimiter='\t'))

def main():
    rows=read(HERE/'cases.tsv')
    per_p=read(HERE/'global_p.tsv')
    p16={r['case']:r for r in read(HERE/'r128_p16_grouped_cut_top32.tsv')[:1]} if (HERE/'r128_p16_grouped_cut_top32.tsv').exists() else {}
    # The exhaustive P=16 cut search proves the best-cut LB from the top row.
    p16_lb=int(p16['r128_v8_c4']['LB']) if 'r128_v8_c4' in p16 else 25_883_940
    bycase={}
    for r in per_p:
        if int(r['feasible_memory']): bycase.setdefault(r['case'],[]).append((int(r['P']),int(r['P_LB'])))
    refined=[]
    for r in rows:
        bounds=list(bycase[r['case']])
        if r['case']=='r128_v8_c4':
            bounds=[(P,max(lb,p16_lb) if P==16 else lb) for P,lb in bounds]
        glb=min(lb for _,lb in bounds)
        time=int(r['Time']); old=int(r['old_time'])
        refined.append({
          'case':r['case'],'time_bucket':r['time_bucket'],'Nops':r['Nops'],'Time':time,'old_placement_time':old,
          'old_to_v7_reduction_pct':float(r['old_reduction_pct']),
          'refined_global_LB':glb,'refined_global_P':min(P for P,lb in bounds if lb==glb),
          'max_improvement_vs_old_pct':(old-glb)*100/old,
          'max_headroom_vs_v7_pct':(time-glb)*100/time,
          'official_python_base_time':r['official_python_base_time'],
        })
    fields=list(refined[0])
    with open(HERE/'refined_bounds.tsv','w') as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter='\t');w.writeheader();w.writerows(refined)
    buckets=[]
    for b in ('<5M','5-10M','10-30M','>=30M'):
        xs=[x for x in refined if x['time_bucket']==b]
        buckets.append({
          'Time_bucket':b,'n':len(xs),
          'old_to_v7_reduction_mean_pct':statistics.mean(x['old_to_v7_reduction_pct'] for x in xs),
          'old_to_v7_reduction_median_pct':statistics.median(x['old_to_v7_reduction_pct'] for x in xs),
          'old_to_v7_reduction_worst_pct':min(x['old_to_v7_reduction_pct'] for x in xs),
          'geomean_old_over_v7':math.exp(statistics.mean(math.log(x['old_placement_time']/x['Time']) for x in xs)),
          'max_gain_vs_old_mean_pct':statistics.mean(x['max_improvement_vs_old_pct'] for x in xs),
          'max_gain_vs_old_median_pct':statistics.median(x['max_improvement_vs_old_pct'] for x in xs),
          'max_gain_vs_old_worst_pct':min(x['max_improvement_vs_old_pct'] for x in xs),
          'max_headroom_vs_v7_mean_pct':statistics.mean(x['max_headroom_vs_v7_pct'] for x in xs),
          'max_gain_vs_old_le_5pct':sum(x['max_improvement_vs_old_pct']<=5 for x in xs),
          'max_gain_vs_old_le_2pct':sum(x['max_improvement_vs_old_pct']<=2 for x in xs),
          'max_gain_vs_old_le_1pct':sum(x['max_improvement_vs_old_pct']<=1 for x in xs),
        })
    with open(HERE/'refined_buckets.tsv','w') as f:
        w=csv.DictWriter(f,fieldnames=list(buckets[0]),delimiter='\t');w.writeheader();w.writerows(buckets)
    for p in (5,2,1):
        original=sum((int(x['old_time'])-int(x['global_LB']))*100/int(x['old_time'])<=p for x in rows)
        updated=sum(x['max_improvement_vs_old_pct']<=p for x in refined)
        print(f'max possible improvement vs old <= {p}%: original {original}/50, refined {updated}/50')
    print('r128 original P16 LB/global LB',next(lb for P,lb in bycase['r128_v8_c4'] if P==16),min(lb for _,lb in bycase['r128_v8_c4']))
    print('r128 refined P16/global LB',p16_lb,min(lb for _,lb in [(P,max(lb,p16_lb) if P==16 else lb) for P,lb in bycase['r128_v8_c4']]))
    for b in buckets: print(b)

if __name__=='__main__':main()
