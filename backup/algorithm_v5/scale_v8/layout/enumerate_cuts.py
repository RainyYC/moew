#!/usr/bin/env python3
"""Enumerate contiguous folded layouts for a fixed exact make_map(P) map."""
import csv, importlib.util, itertools, math, subprocess
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[3]
AV=ROOT/'algorithm_v5'; CASES=ROOT/'data/official/Problem/cases'
RESULTS=AV/'results/diff_v7_default'; HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('profile_cases',AV/'scale_v8/profile/profile_cases.py')
prof=importlib.util.module_from_spec(spec); spec.loader.exec_module(prof)
gr=prof.gr

def make_map(case,P):
    src=HERE/'map_helper.cpp'; binary=HERE/'map_helper'
    if not binary.exists() or binary.stat().st_mtime<src.stat().st_mtime:
        subprocess.run(['g++','-std=c++17','-O2',str(src),'-o',str(binary)],check=True)
    cp=subprocess.run([str(binary),str(P)],input=(CASES/(case+'.txt')).read_bytes(),stdout=subprocess.PIPE,check=True)
    return [[int(v) for v in line.split()] for line in cp.stdout.decode().splitlines()]

def grouped_map(case,P):
    src=HERE/'placement_helper.cpp'; binary=HERE/'placement_helper'
    if not binary.exists() or binary.stat().st_mtime<src.stat().st_mtime:
        subprocess.run(['g++','-std=c++17','-O2',str(src),'-o',str(binary)],check=True)
    cp=subprocess.run([str(binary),str(P)],input=(CASES/(case+'.txt')).read_bytes(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
    (HERE/f'{case}_p{P}_placement.log').write_bytes(cp.stderr)
    return [[int(v) for v in line.split()] for line in cp.stdout.decode().splitlines()]

def bounds_for_chunks(L,cuts):
    edges=(0,)+cuts+(L,)
    return [list(range(edges[k],edges[k+1])) for k in range(len(edges)-1)]

def enumerate_case(case,P,reference_times,improve_map=False):
    inst=gr.parse_instance((CASES/(case+'.txt')).read_text())
    map_rows=grouped_map(case,P) if improve_map else make_map(case,P)
    mp=SimpleNamespace(P=P,map=map_rows)
    D={l:gr.durations(inst,mp,l) for l in range(inst.L)}
    dur={l:{o:D[l][o] for o in gr.OPS} for l in range(inst.L)}
    es,tail,cp=prof.get_bounds(inst.L,dur)
    Dgap=prof.layer_activation_gap(inst.L,dur)
    cap_cache={}
    def group_bound(layers):
        mask=sum(1<<l for l in layers)
        if mask in cap_cache:return cap_cache[mask]
        wc=inst.nmb*sum(dur[l][o] for l in layers for o in gr.OPS if gr.ENGINE[o]=='C')
        wn=inst.nmb*sum(dur[l][o] for l in layers for o in gr.OPS if gr.ENGINE[o]=='N')
        ht=prof.subset_bound(layers,dur,es,tail,inst.nmb)
        exp=len(layers)*(inst.E//P*inst.Z+inst.Zs)
        has_comm=any(dur[l][o]>0 for l in layers for o in gr.COMM_OPS)
        umin=inst.U if has_comm else 0
        room=inst.M-exp-umin
        if room<0 or inst.Uact>0 and room<inst.Uact:
            result=(max(wc,wn),ht,0,0,0)
            cap_cache[mask]=result;return result
        if inst.Uact>0:
            A=room//inst.Uact
            mem=max((es[l,'comb']+dur[l]['comb']+
                     prof.ceildiv(inst.nmb*(Dgap[l]+1),A)-1+
                     dur[l]['s_bwd']+tail[l,'s_bwd'] for l in layers),default=0)
        else: A=0;mem=0
        result=(max(wc,wn),ht,1,mem,A)
        cap_cache[mask]=result;return result

    R=inst.N*inst.S
    legal_pairs=set()
    for G in range(1,min(inst.L,R//P,64)+1):
        if G<=inst.L:legal_pairs.add((G,G))
        if 2*G<=inst.L:legal_pairs.add((G,2*G))
    counts={}; candidates=[]; layouts=0; memory_infeasible=0
    for G,K in sorted(legal_pairs,key=lambda x:(x[1],x[0])):
        cnt=0; below_v7=below_wave=0; best=(10**100,None); bestwave=(10**100,None)
        for cuts in itertools.combinations(range(1,inst.L),K-1):
            chunks=bounds_for_chunks(inst.L,cuts)
            glayers=[[] for _ in range(G)]
            for k,ls in enumerate(chunks):
                g=k if k<G else 2*G-1-k
                glayers[g].extend(ls)
            gb=[group_bound(ls) for ls in glayers]
            if any(not z[2] for z in gb):memory_infeasible+=1;continue
            reslb=max((z[0] for z in gb),default=0); htlb=max((z[1] for z in gb),default=0); memlb=max((z[3] for z in gb),default=0)
            lb=max(cp,reslb,htlb,memlb)
            cnt+=1;layouts+=1
            if lb<best[0]:best=(lb,cuts)
            if lb<reference_times['wave']:below_wave+=1
            if lb<reference_times['v7']:below_v7+=1
            if lb<bestwave[0]:bestwave=(lb,cuts)
            candidates.append((lb,G,K,cuts,max((z[4] for z in gb),default=0),reslb,htlb,memlb,cp))
        counts[G,K]={'layouts_feasible':cnt,'lb_below_v7':below_v7,'lb_below_wave':below_wave,
                     'best_lb':best[0] if cnt else 0,'best_cuts':','.join(map(str,best[1] or ())) }
    candidates.sort(key=lambda x:(x[0],x[1],x[2],x[3]))
    return inst,cp,layouts,memory_infeasible,counts,candidates,cap_cache

def main():
    case='r128_v8_c4'; P=16
    v7=next(int(x['new_time']) for x in csv.DictReader(open(RESULTS/'comparison.tsv'),delimiter='\t') if x['case']==case)
    wave=24_108_480
    inst,cp,n,mbad,counts,candidates,cache=enumerate_case(case,P,{'v7':v7,'wave':wave},improve_map=True)
    rows=[]
    for (G,K),x in sorted(counts.items(),key=lambda kv:(kv[0][1],kv[0][0])):
        rows.append({'G':G,'K':K,**x})
    with open(HERE/'r128_p16_grouped_cut_counts.tsv','w') as f:
        w=csv.DictWriter(f,fieldnames=['G','K','layouts_feasible','lb_below_v7','lb_below_wave','best_lb','best_cuts'],delimiter='\t');w.writeheader();w.writerows(rows)
    with open(HERE/'r128_p16_grouped_cut_top32.tsv','w') as f:
        w=csv.writer(f,delimiter='\t');w.writerow(['rank','LB','G','K','cuts','groups_max_activation_slots','resource_LB','headtail_LB','memory_area_LB','CP'])
        for i,(lb,G,K,cuts,A,reslb,htlb,memlb,cp0) in enumerate(candidates[:32],1):w.writerow([i,lb,G,K,','.join(map(str,cuts)),A,reslb,htlb,memlb,cp0])
    print(f'{case} P={P} MAP=make_map+grouped_placement: CP={cp}, legal layouts before memory={sum(math.comb(inst.L-1,K-1) for G,K in counts)}, feasible={n}, memory-infeasible={mbad}')
    print(f'best fixed-MAP cut LB={candidates[0][0] if candidates else None}; wave={wave}; v7={v7}; feasible layouts with LB<wave={sum(x["lb_below_wave"] for x in counts.values())}; with LB<v7={sum(x["lb_below_v7"] for x in counts.values())}')
    for (G,K),x in sorted(counts.items(),key=lambda kv:(kv[0][1],kv[0][0])):print(G,K,x)
    print('top candidates:')
    for x in candidates[:8]:print(x)

if __name__=='__main__':main()
