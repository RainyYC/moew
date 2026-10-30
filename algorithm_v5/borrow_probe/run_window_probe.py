#!/usr/bin/env python3
"""Generate fixed-map configs, run the C++ window/mode sweep, grade improvements."""
from __future__ import annotations
import json, subprocess, sys, time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from solver.casein import parse_case
from solver import formula, sched

CASES=["x16_vl_trap4_ramp","x17_vl_tight_block","x18_vl_tight_small","x20_vl_flat_control","r64_v8_c8a"]
DIR=ROOT/"algorithm_v5/borrow_probe"; DIR.mkdir(exist_ok=True)
BIN=DIR/"window_probe"
subprocess.run(["g++","-std=c++17","-O2","-DNDEBUG",str(DIR/"window_probe.cpp"),"-o",str(BIN)],cwd=ROOT,check=True)

def parse_final(case,text):
    rows=[x.split() for x in text.splitlines() if x.strip()]
    V,P=map(int,rows[0]); Kpsi=list(map(int,rows[2])); K=Kpsi[0]; psi=Kpsi[1:]
    map_rows=[list(map(int,rows[4+l])) for l in range(case.L)]
    plan=formula.build_plan(case,V,P,1,psi,map_rows)
    starts=[-1]*case.n_ops
    for line in rows[5+case.L:]:
        t=int(line[0])
        for tok in line[1:]:
            mb,l,name=tok.split(":");idx=int(mb)*case.L*10+int(l)*10+formula.OP_INDEX[name]
            starts[idx]=t
    assert all(t>=0 for t in starts)
    ends=[starts[i]+plan.durations[(i%(case.L*10))//10][i%10] for i in range(len(starts))]
    return V,P,K,psi,map_rows,plan,starts,ends,max(ends,default=0)

def as_i128(v): return str(int(v))

records=[]
for name in CASES:
    t0=time.monotonic()
    case=parse_case(ROOT/"data/official/Problem/cases"/(name+".txt"))
    V,P,K,psi,map_rows,plan,old_start,old_end,before=parse_final(case,(ROOT/"algorithm_v5/results/final"/(name+".out")).read_text())
    G=plan.V; group=list(plan.group_of_layer); ng=[group.count(g) for g in range(G)]
    q=(case.E//P)*case.Z+case.Zs
    zero=[]
    for g in range(G):
        zero.append(all(not any(plan.durations[l][o] for o in (1,3,5,8)) for l in range(case.L) if group[l]==g))
    capsets=[];bufsets=[]
    # production automatic policy: b=2 if it leaves at least n_g slots; else b=1.
    for all1 in (False,True):
        caps=[];buf=[]
        for g in range(G):
            b=0 if zero[g] else 1
            if not all1 and not zero[g]:
                av2=case.M-ng[g]*q-2*case.U
                if av2>=0 and av2//case.Uact>=ng[g]: b=2
            avail=case.M-ng[g]*q-(0 if zero[g] else b*case.U)
            cap=min(case.nmb*ng[g],max(0,avail//case.Uact)) if case.Uact else case.nmb*ng[g]
            caps.append(int(cap));buf.append(b)
        capsets.append(caps);bufsets.append(buf)
    # Two policies have the same buffer=0 rule for all-zero groups, as production.
    config=DIR/(name+".cfg")
    lines=[f"{case.nmb} {case.L} {G}"," ".join(map(str,group))," ".join(map(str,ng))]
    for arr in (capsets[0],bufsets[0],capsets[1],bufsets[1]):lines.append(" ".join(map(str,arr)))
    lines += [" ".join(as_i128(x) for x in row) for row in plan.durations]
    config.write_text("\n".join(lines)+"\n")
    starts_path=DIR/(name+".starts")
    try:
        run=subprocess.run([str(BIN),str(config),str(starts_path)],cwd=ROOT,text=True,capture_output=True,timeout=11)
    except subprocess.TimeoutExpired:
        records.append({"case":name,"before":before,"status":"outer_timeout"});continue
    line=run.stdout.strip().splitlines()[-1] if run.stdout.strip() else ""
    fields=dict(item.split("=",1) for item in line.split() if "=" in item)
    if run.returncode or not fields.get("time"):
        records.append({"case":name,"before":before,"status":"failed","stdout":run.stdout,"stderr":run.stderr});continue
    after=int(fields["time"]);record={"case":name,"V":V,"P":P,"K":K,"before":before,"after":after,
        "delta":after-before,"window":int(fields["window"]),"mode":int(fields["mode"]),
        "buffers":fields["buffers"],"calls":int(fields["calls"]),"sec":float(fields["sec"]),
        "capped":bool(int(fields["capped"])),"official_legal":None}
    if after<before:
        numbers=starts_path.read_text().split(); count=int(numbers[0]); starts=list(map(int,numbers[1:]));assert count==case.n_ops and len(starts)==count
        ends=[starts[i]+plan.durations[(i%(case.L*10))//10][i%10] for i in range(count)]
        result=sched.Schedule(after,starts,ends,case.nmb,(True,False,False,False))
        out=DIR/(name+".out");out.write_text(sched.render_output(case,plan,result,map_rows));record["candidate"]=str(out.relative_to(ROOT))
        grade=subprocess.run([sys.executable,str(ROOT/"data/official/Problem/grader.py"),
            str(ROOT/"data/official/Problem/cases"/(name+".txt")),str(out)],cwd=ROOT,text=True,capture_output=True)
        try:gt=int(grade.stdout.strip().splitlines()[-1])
        except Exception:gt=None
        record["official_exit"]=grade.returncode;record["official_time"]=gt
        record["official_legal"]=grade.returncode==0 and gt==after
        record["official_stderr"]=grade.stderr[-1000:]
    record["wall_sec"]=time.monotonic()-t0
    records.append(record)
    print(json.dumps(record,sort_keys=True))
(DIR/"window_probe.json").write_text(json.dumps(records,indent=2)+"\n")
