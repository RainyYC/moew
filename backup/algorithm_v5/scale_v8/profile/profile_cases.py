#!/usr/bin/env python3
"""Read-only profile of saved v7 schedules against DAG/resource lower bounds."""
import csv, importlib.util, math, statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AV = ROOT / 'algorithm_v5'
CASES = ROOT / 'data/official/Problem/cases'
OUT = AV / 'results/diff_v7_default'
DEST = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('grader', ROOT / 'data/official/Problem/grader.py')
gr = importlib.util.module_from_spec(spec); spec.loader.exec_module(gr)

def ceildiv(a,b): return (a+b-1)//b

def graph(L):
    succ = {(l,o): [] for l in range(L) for o in gr.OPS}
    pred = {(l,o): [] for l in range(L) for o in gr.OPS}
    for l in range(L):
        for op in gr.OPS:
            for pl,pop,_ in gr.op_preds(L,l,op):
                pred[l,op].append((pl,pop)); succ[pl,pop].append((l,op))
    indeg = {k:len(v) for k,v in pred.items()}; q=[k for k,v in indeg.items() if not v]; order=[]
    while q:
        k=q.pop(); order.append(k)
        for n in succ[k]:
            indeg[n]-=1
            if indeg[n]==0:q.append(n)
    if len(order)!=len(indeg): raise ValueError('DAG cycle')
    return pred,succ,order

def get_bounds(L,dur):
    pred,succ,order=graph(L); es={}; tail={}
    for k in order: es[k]=max((es[p]+dur[p[0]][p[1]] for p in pred[k]), default=0)
    for k in reversed(order): tail[k]=max((dur[n[0]][n[1]]+tail[n] for n in succ[k]), default=0)
    cp=max(es[k]+dur[k[0]][k[1]] for k in order)
    return es,tail,cp

def subset_bound(layers, dur, es, tail, mb):
    # layers is a list of layer ids sharing a card-group; resource engines are independent.
    best=0
    for eng in ('C','N'):
        keys=[(l,o) for l in layers for o in gr.OPS if gr.ENGINE[o]==eng and dur[l][o]>0]
        if not keys: continue
        Rs=sorted({es[k] for k in keys}); Qs=sorted({tail[k] for k in keys})
        for R in Rs:
            for Q in Qs:
                work=sum(mb*dur[l][o] for l,o in keys if es[l,o]>=R and tail[l,o]>=Q)
                if work: best=max(best,R+work+Q)
    return best

def dag_for_inst(inst, mapping):
    D={l:gr.durations(inst,mapping,l) for l in range(inst.L)}
    dur={l:{o:D[l][o] for o in gr.OPS} for l in range(inst.L)}
    return D,dur

def schedule_metrics(inst,m,dur,group):
    # parsed checker schedule, compute makespan plus exact resource and memory peaks.
    starts={(mb,l,o):t for t,mb,l,o,_ in m.sched}
    end={(mb,l,o):t+dur[l][o] for t,mb,l,o,_ in m.sched}
    makespan=max(end.values())
    busy={}
    mem={}
    for g in range(m.V):
        ls=[l for l in range(inst.L) if group[l]==g]
        c=sum(inst.nmb*dur[l][o] for l in ls for o in gr.OPS if gr.ENGINE[o]=='C')
        n=sum(inst.nmb*dur[l][o] for l in ls for o in gr.OPS if gr.ENGINE[o]=='N')
        busy[g]=(c,n)
        ss={}; ee={}
        for mb,l,o in starts:
            if group[l]==g and o in gr.COMM_OPS and dur[l][o]>0:
                ss[starts[mb,l,o]]=ss.get(starts[mb,l,o],0)+1
                ee[end[mb,l,o]]=ee.get(end[mb,l,o],0)+1
        cur=peak=0
        for t in sorted(set(ss)|set(ee)):
            cur+=ss.get(t,0); peak=max(peak,cur); cur-=ee.get(t,0)
        arr={}; dep={}
        for mb in range(inst.nmb):
            for l in ls:
                fe=end[mb,l,'comb']; bs=starts[mb,l,'s_bwd']
                arr[fe]=arr.get(fe,0)+1; dep[bs]=dep.get(bs,0)+1
        cur=ap=0
        for t in sorted(set(arr)|set(dep)):
            cur+=arr.get(t,0); ap=max(ap,cur); cur-=dep.get(t,0)
        exp=len(ls)*(inst.E//m.P*inst.Z+inst.Zs)
        mem[g]=exp+inst.U*peak+inst.Uact*ap
    return makespan,busy,mem

def optimistic_durations(inst,P):
    H=inst.d*inst.b//inst.k
    p_in=sum(1 for q in range(P) if q!=0 and q//inst.S==0)
    p_out=P-1-p_in
    ds={}
    for l,(T,loads) in enumerate(inst.layers):
        if loads is None: loads=gr.balanced_loads(T,inst.E)
        ml=max(ceildiv(T,P),max(loads))
        X=ceildiv(T*H,P)
        x=max(ceildiv(p_in*X,inst.Bin),ceildiv(p_out*X,inst.Bout))*inst.Fio
        s=T*inst.Fs; gemm=ml*inst.Fin; a=inst.ax; b=inst.bx
        dd={'s':s,'disp':x,'gemm':gemm,'comb':x,
            's_bwd':ceildiv(a*s,1000000),'comb_bwd':ceildiv(a*x,1000000),
            'gemm_dx':ceildiv(a*gemm,1000000),'gemm_dw':ceildiv(a*b*gemm,10**12),
            'disp_bwd':ceildiv(a*x,1000000),'s_dw':ceildiv(a*b*s,10**12)}
        ds[l]=dd
    return ds

def layer_activation_gap(L,dur):
    """Longest DAG path from comb(l).end to s_bwd(l).start, excluding endpoints."""
    pred,succ,order=graph(L); result={}
    for l in range(L):
        src=(l,'comb'); target=(l,'s_bwd'); memo={}
        def walk(node):
            if node in memo:return memo[node]
            candidates=[]
            for n in succ[node]:
                if n==target: candidates.append(0)
                else:
                    v=walk(n)
                    if v is not None:candidates.append(dur[n[0]][n[1]]+v)
            memo[node]=max(candidates) if candidates else None
            return memo[node]
        value=walk(src)
        if value is None: raise AssertionError(f'no DAG path from {src} to {target}')
        result[l]=value
    return result

def activation_area_bound(inst,P,dur,es,tail):
    """Per-layer live-activation area lower bound, with optimistic group memory."""
    D=layer_activation_gap(inst.L,dur)
    layer_bounds=[]; capacities=[]
    for l in range(inst.L):
        exp=inst.E//P*inst.Z+inst.Zs
        needs_comm=any(dur[l][o]>0 for o in gr.COMM_OPS)
        umin=inst.U if needs_comm else 0
        room=inst.M-exp-umin
        if room<0:return None,None,D
        if inst.Uact<=0:
            # No per-activation memory charge: this area argument is unavailable.
            capacities.append(None); layer_bounds.append(0); continue
        A=room//inst.Uact
        if A<1:return None,None,D
        capacities.append(A)
        first=es[l,'comb']+dur[l]['comb']
        last=dur[l]['s_bwd']+tail[l,'s_bwd']
        area=inst.nmb*(D[l]+1)
        bound=first+ceildiv(area,A)-1+last
        layer_bounds.append(bound)
    return max(layer_bounds,default=0),max((a for a in capacities if a is not None),default=None),D

def fixed_bounds(inst,m,dur,group):
    es,tail,cp=get_bounds(inst.L,dur)
    work=0
    groups=[]
    for g in range(m.V):
        ls=[l for l in range(inst.L) if group[l]==g]
        wc=sum(inst.nmb*dur[l][o] for l in ls for o in gr.OPS if gr.ENGINE[o]=='C')
        wn=sum(inst.nmb*dur[l][o] for l in ls for o in gr.OPS if gr.ENGINE[o]=='N')
        groups.append(max(wc,wn))
    resource=max(groups,default=0)
    subset=subset_bound(list(range(inst.L)),dur,es,tail,inst.nmb) if m.V==1 else max((subset_bound([l for l in range(inst.L) if group[l]==g],dur,es,tail,inst.nmb) for g in range(m.V)),default=0)
    return max(cp,resource,subset),cp,resource,subset

def global_bound(inst):
    R=inst.N*inst.S; best=None; bestP=None; details=[]
    legal=[p for p in range(1,min(R,inst.E)+1) if inst.E%p==0 and (inst.S%p==0 or p%inst.S==0)]
    for P in legal:
        base=inst.E//P*inst.Z+inst.Zs
        G=max(1,min(inst.L,R//P,64))
        # Every nonempty group has at least one live activation at its peak.
        # Ignore communication-buffer memory here to keep this a safe,
        # optimistic feasibility filter, including mixed zero-traffic layers.
        if inst.M < inst.Uact or (base>0 and G*((inst.M-inst.Uact)//base)<inst.L):
            details.append({'P':P,'Gmax':G,'feasible_memory':0,'single_layer_activation_slots':0,
                            'D_min':0,'D_max':0,'core_LB':0,'activation_area_LB':0,'P_LB':0})
            continue
        dur=optimistic_durations(inst,P)
        es,tail,cp=get_bounds(inst.L,dur)
        ctot=inst.nmb*sum(dur[l][o] for l in range(inst.L) for o in gr.OPS if gr.ENGINE[o]=='C')
        ntot=inst.nmb*sum(dur[l][o] for l in range(inst.L) for o in gr.OPS if gr.ENGINE[o]=='N')
        c_layer=max(inst.nmb*sum(dur[l][o] for o in gr.OPS if gr.ENGINE[o]=='C') for l in range(inst.L))
        n_layer=max(inst.nmb*sum(dur[l][o] for o in gr.OPS if gr.ENGINE[o]=='N') for l in range(inst.L))
        k=ceildiv(inst.L,G)
        c_layers=sorted(inst.nmb*sum(dur[l][o] for o in gr.OPS if gr.ENGINE[o]=='C') for l in range(inst.L))
        n_layers=sorted(inst.nmb*sum(dur[l][o] for o in gr.OPS if gr.ENGINE[o]=='N') for l in range(inst.L))
        pigeonhole=max(sum(c_layers[:k]),sum(n_layers[:k]))
        # Every layer maps to one group, so per-layer head/tail work is also a valid bound.
        ht=max((subset_bound([l],dur,es,tail,inst.nmb) for l in range(inst.L)),default=0)
        core_lb=max(cp,ceildiv(ctot,G),ceildiv(ntot,G),c_layer,n_layer,pigeonhole,ht)
        act_lb,act_capacity,D=activation_area_bound(inst,P,dur,es,tail)
        if act_lb is None:
            details.append({'P':P,'Gmax':G,'feasible_memory':0,'single_layer_activation_slots':act_capacity or 0,
                            'D_min':min(D.values()),'D_max':max(D.values()),'core_LB':core_lb,'activation_area_LB':0,'P_LB':0})
            continue
        lb=max(core_lb,act_lb)
        details.append({'P':P,'Gmax':G,'feasible_memory':1,'single_layer_activation_slots':act_capacity or 0,
                        'D_min':min(D.values()),'D_max':max(D.values()),'core_LB':core_lb,'activation_area_LB':act_lb,'P_LB':lb})
        if best is None or lb<best: best,bestP=lb,P
    return best or 0,bestP,details

def main():
    comp=list(csv.DictReader(open(OUT/'comparison.tsv'),delimiter='\t'))
    history={x['case']:x for x in csv.DictReader(open(AV/'results/comparison_history.tsv'),delimiter='\t')}
    rows=[]; p_rows=[]
    for r in comp:
        name=r['case']; inst=gr.parse_instance((CASES/(name+'.txt')).read_text())
        m=gr.parse_mapping((OUT/(name+'.out')).read_text(),inst)
        D,dur=dag_for_inst(inst,m); group=gr.group_index(m,inst)
        makespan,busy,mem=schedule_metrics(inst,m,dur,group)
        flb,fcp,fres,fsub=fixed_bounds(inst,m,dur,group)
        glb,gp,pdetails=global_bound(inst)
        old=int(r['old_placement_time']); new=int(r['new_time']); pybase=int(history[name]['official_python_time'])
        worst=max(mem.values()); cmax=max(v[0] for v in busy.values()); nmax=max(v[1] for v in busy.values())
        busiest_g=max(busy,key=lambda g:max(busy[g]))
        row={
          'case':name,'Nops':10*inst.L*inst.nmb,'L':inst.L,'mb':inst.nmb,'E':inst.E,'P':m.P,'G':m.V,'K':m.K,
          'Time':new,'time_bucket':(' <5M' if new<5_000_000 else '5-10M' if new<10_000_000 else '10-30M' if new<30_000_000 else '>=30M').strip(),
          'old_time':old,'old_reduction_pct':(old-new)*100/old if old else 0,'old_speedup':old/new if new else 0,
          'official_python_base_time':pybase,'official_python_reduction_pct':(pybase-new)*100/pybase if pybase else 0,
          'fixed_LB':flb,'fixed_CP':fcp,'fixed_resource_LB':fres,'fixed_headtail_LB':fsub,'Time_over_fixed_LB':new/flb if flb else 0,
          'fixed_headroom_pct':(new-flb)*100/new if new else 0,'global_LB':glb,'global_best_P':gp,
          'Time_over_global_LB':new/glb if glb else 0,'global_headroom_pct':(new-glb)*100/new if new else 0,
          'nmb_over_G':inst.nmb/m.V,'busiest_group':busiest_g,
          'busiest_group_C_over_N':busy[busiest_g][0]/busy[busiest_g][1] if busy[busiest_g][1] else 0,
          'max_C_work_over_max_N_work':cmax/nmax if nmax else 0,
          'memory_peak_pct':worst*100/inst.M if inst.M else 0,'memory_peak':worst,'M':inst.M,
          'schedule_makespan':makespan,
        }
        if not (glb <= flb <= new):
            raise AssertionError(f'{name}: invalid lower-bound ordering: global={glb}, fixed={flb}, Time={new}')
        this_p=[x for x in pdetails if x['P']==m.P]
        if len(this_p)!=1 or not this_p[0]['feasible_memory'] or this_p[0]['P_LB']>new:
            raise AssertionError(f'{name}: current-P bound invalid or P memory-infeasible: {this_p}, Time={new}')
        rows.append(row)
        for drow in pdetails:
            drow['case']=name
            drow['current_P']=m.P
            p_rows.append(drow)
    keys=list(rows[0])
    with open(DEST/'cases.tsv','w') as f:
        w=csv.DictWriter(f,fieldnames=keys,delimiter='\t');w.writeheader();w.writerows(rows)
    with open(DEST/'global_p.tsv','w') as f:
        cols=['case','P','current_P','Gmax','feasible_memory','single_layer_activation_slots','D_min','D_max','core_LB','activation_area_LB','P_LB']
        w=csv.DictWriter(f,fieldnames=cols,delimiter='\t');w.writeheader()
        for drow in p_rows:w.writerow(drow)
    def summary(key,vals):
        vals=list(vals)
        return {'bucket':key,'n':len(vals),'old_reduction_mean_pct':statistics.mean(x['old_reduction_pct'] for x in vals),
          'old_reduction_median_pct':statistics.median(x['old_reduction_pct'] for x in vals),
          'old_reduction_worst_pct':min(x['old_reduction_pct'] for x in vals),
          'geomean_old_over_v7':math.exp(statistics.mean(math.log(x['old_speedup']) for x in vals)),
          'official_python_reduction_mean_pct':statistics.mean(x['official_python_reduction_pct'] for x in vals)}
    buckets=[]
    for b in ('<5M','5-10M','10-30M','>=30M'):
        buckets.append(summary('Time '+b,[x for x in rows if x['time_bucket']==b]))
    for lo,hi,label in [(0,1000,'<1k Nops'),(1000,2000,'1-2k Nops'),(2000,5000,'2-5k Nops'),(5000,10**9,'>=5k Nops')]:
        buckets.append(summary(label,[x for x in rows if lo<=x['Nops']<hi]))
    with open(DEST/'buckets.tsv','w') as f:
        w=csv.DictWriter(f,fieldnames=list(buckets[0]),delimiter='\t');w.writeheader();w.writerows(buckets)
    print('profiled',len(rows),'cases')
    print('low old improvement with fixed/global headroom >=10%:')
    for x in rows:
        if x['old_reduction_pct']<=2 and max(x['fixed_headroom_pct'],x['global_headroom_pct'])>=10:
            print(x['case'],f"old={x['old_reduction_pct']:.2f}% fixed={x['fixed_headroom_pct']:.2f}% global={x['global_headroom_pct']:.2f}% LB={x['fixed_LB']}/{x['global_LB']} T={x['Time']}")
    print('bucket summary:',buckets)

if __name__=='__main__': main()
