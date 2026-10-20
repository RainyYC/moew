#!/usr/bin/env python3
"""独立复核器：**不 import `judge`**，按题面 §4 从零实现解析 / 时长 / 调度模拟 / 内存，
复算 7 个验收值（ex1–ex6 + mini）并与 `python3 -m judge eval` 逐项对照。

用法::

    python3 tools/independent_check.py                 # 7 例全查（默认）
    python3 tools/independent_check.py --cases ex1 ex5  # 子集
    python3 tools/independent_check.py --json           # 机器可读

退出码：0 = 7 值、Time、lb、groups、engines 与 judge 完全一致；1 = 有任何不一致或非法。

口径（题面 / CONTRACT §1）：
* 时长：``s=T·Fs``、``gemm=m·Fin``、``X=⌈T·H·(P−1)/P⌉``、``x=max(⌈pin·X/Bin⌉,⌈pout·X/Bout⌉)·Fio``，
  反向 α/αβ 单次向上取整；``pin/pout`` 按物理卡号 ``q=v·(P·D)+d·P+p`` 复核；
* 调度：题面 §4.2 的层内链、``gemm_dw/s_dw`` 只依赖 ``comb_bwd``、``s_bwd ≥ 本层 comb 结束``、
  ``s(l) ≥ comb(l−1)``、``s_bwd(l) ≥ disp_bwd(l+1)``；零时长不占引擎、相等时刻释放；
* 内存：Mexp/Movl/Mact，通信与激活都是**闭区间**峰值（零长度通信计入 Movl）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

OPS = ["s", "disp", "gemm", "comb", "s_bwd", "comb_bwd", "gemm_dx", "gemm_dw", "disp_bwd", "s_dw"]
ENGINE = {
    "s": "C", "disp": "N", "gemm": "C", "comb": "N", "s_bwd": "C",
    "comb_bwd": "N", "gemm_dx": "C", "gemm_dw": "C", "disp_bwd": "N", "s_dw": "C",
}
BASE_DEPS = {
    "s": (), "disp": ("s",), "gemm": ("disp",), "comb": ("gemm",), "s_bwd": ("comb",),
    "comb_bwd": ("s_bwd",), "gemm_dx": ("comb_bwd",), "gemm_dw": ("comb_bwd",),
    "disp_bwd": ("gemm_dx",), "s_dw": ("comb_bwd",),
}


def ceil_div(a: int, b: int) -> int:
    return -((-a) // b)


# --------------------------------------------------------------------------- #
# 解析（题面 §2 / §3）
# --------------------------------------------------------------------------- #
def parse_case(path: Path) -> dict:
    lines = [line.split() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    n, s, m, bin_w, bout_w = map(int, lines[0])
    (layers, experts, z, zs, u, uact, k, nmb, fs, fio, fin, alpha, beta) = map(int, lines[1])
    d, b = map(int, lines[2])
    t_layers, loads = [], []
    for i in range(layers):
        row = [int(x) for x in lines[3 + i]]
        t_layers.append(row[0])
        loads.append(row[1:] if len(row) > 1 else None)
    for load in loads:
        assert load is None or len(load) == experts, "负载向量长度必须等于 E"
    return {
        "N": n, "S": s, "M": m, "Bin": bin_w, "Bout": bout_w,
        "L": layers, "E": experts, "Z": z, "Zs": zs, "U": u, "Uact": uact, "k": k,
        "nmb": nmb, "Fs": fs, "Fio": fio, "Fin": fin, "alpha": alpha, "beta": beta,
        "d": d, "b": b, "T": t_layers, "loads": loads,
        "R": n * s, "H": (d * b) // k,
    }


def parse_output(text: str) -> dict:
    lines = [line.split() for line in text.splitlines() if line.strip()]
    v, p, dd = map(int, lines[0])
    psi_line = [int(x) for x in lines[2]]
    k, psi = psi_line[0], psi_line[1:]
    assert lines[1] == ["PSI"] and lines[3] == ["MAP"], "输出必须含 PSI / MAP 段"
    idx = lines.index(["SCHEDULE"])
    grid = [[int(x) for x in row] for row in lines[4:idx]]
    sched = []
    for row in lines[idx + 1:]:
        t = int(row[0])
        for token in row[1:]:
            mb, layer, op = token.split(":")
            sched.append((int(mb), int(layer), op, t))
    return {"V": v, "P": p, "D": dd, "K": k, "psi": psi, "map": grid, "sched": sched}


# --------------------------------------------------------------------------- #
# 时长与卡组（题面 §4.1 / §4.5）
# --------------------------------------------------------------------------- #
def build(case: dict, out: dict) -> dict:
    v, p, dd = out["V"], out["P"], out["D"]
    # pin/pout：物理卡号 q = v·(P·D) + d·P + p，按「p 卡上有多少 s' 与自己共享同一张卡」取 pin
    nodes = [
        [(blk * (p * dd) + stage * p + rank) // case["S"] for rank in range(p)]
        for blk in range(v) for stage in range(dd)
    ]
    pins = {
        tuple(
            sum(1 for q2 in range(p) if q2 != rank and nodes[j][q2] == nodes[j][rank])
            for rank in range(p)
        )
        for j in range(len(nodes))
    }
    assert len(pins) == 1, f"pin 不是常量：{pins}"
    pin = pins.pop()[0]
    pout = p - 1 - pin

    durations = []
    for layer in range(case["L"]):
        load = case["loads"][layer]
        if load is None:
            base, rem = divmod(case["T"][layer], case["E"])
            load = [base + (1 if e < rem else 0) for e in range(case["E"])]
        per_rank = [0] * p
        for expert, amount in enumerate(load):
            per_rank[out["map"][layer][expert]] += amount
        m = max(per_rank)
        x_in = ceil_div(case["T"][layer] * case["H"] * (p - 1), p) if p > 1 else 0
        x = (
            max(
                ceil_div(pin * x_in, case["Bin"]) if pin else 0,
                ceil_div(pout * x_in, case["Bout"]) if pout else 0,
            )
            * case["Fio"]
            if x_in > 0
            else 0
        )
        s = case["T"][layer] * case["Fs"]
        gemm = m * case["Fin"]
        durations.append({
            "s": s, "disp": x, "gemm": gemm, "comb": x,
            "s_bwd": ceil_div(case["alpha"] * s, 10 ** 6),
            "comb_bwd": ceil_div(case["alpha"] * x, 10 ** 6),
            "gemm_dx": ceil_div(case["alpha"] * gemm, 10 ** 6),
            "gemm_dw": ceil_div(case["alpha"] * case["beta"] * gemm, 10 ** 12),
            "disp_bwd": ceil_div(case["alpha"] * x, 10 ** 6),
            "s_dw": ceil_div(case["alpha"] * case["beta"] * s, 10 ** 12),
        })

    # ψ 切分 → 卡组（V 个），block bk 属于组 bk（前 V 个）或 2V−1−bk（镜像）
    cuts = [0] + list(out["psi"]) + [case["L"]]
    group_of_layer = []
    layers_of_group = [[] for _ in range(v)]
    for block in range(len(cuts) - 1):
        group = block if block < v else 2 * v - 1 - block
        for layer in range(cuts[block], cuts[block + 1]):
            group_of_layer.append(group)
            layers_of_group[group].append(layer)
    return {"dur": durations, "m": pin, "pout": pout, "group_of": group_of_layer,
            "layers_of_group": layers_of_group}


def deps_of(layer: int, layers: int, op: str) -> list[tuple[int, str]]:
    need = [(layer, q) for q in BASE_DEPS[op]]
    if op == "s" and layer > 0:
        need.append((layer - 1, "comb"))
    if op == "s_bwd" and layer < layers - 1:
        need.append((layer + 1, "disp_bwd"))
    return need


# --------------------------------------------------------------------------- #
# 校验 + 模拟结果（题面 §4.2 / §4.6）
# --------------------------------------------------------------------------- #
def check(case: dict, out: dict, model: dict) -> dict:
    dur = model["dur"]
    errors: list[str] = []
    start: dict[tuple[int, int, str], int] = {}
    end: dict[tuple[int, int, str], int] = {}
    for mb, layer, op, t in out["sched"]:
        key = (mb, layer, op)
        if key in start:
            errors.append(f"重复操作 {mb}:{layer}:{op}")
        start[key] = t
        end[key] = t + dur[layer][op]
    total = case["nmb"] * case["L"] * len(OPS)
    if len(start) != total:
        missing = total - len(start)
        errors.append(f"操作数 {len(start)}/{total}（缺 {missing}）")
        return {"ok": False, "errors": errors}

    for (mb, layer, op), t in start.items():
        for dlayer, dop in deps_of(layer, case["L"], op):
            dep_end = end[(mb, dlayer, dop)]
            if t < dep_end:
                errors.append(f"依赖 {mb}:{layer}:{op} t={t} < {mb}:{dlayer}:{dop} end={dep_end}")

    busy: dict[tuple[int, str], list[tuple[int, int]]] = {}
    for (mb, layer, op), t in start.items():
        if dur[layer][op] <= 0:
            continue  # 零时长不占引擎、相等时刻释放
        gkey = (model["group_of"][layer], ENGINE[op])
        busy.setdefault(gkey, []).append((t, end[(mb, layer, op)]))
    for gkey, spans in busy.items():
        spans.sort()
        for (t0, e0), (t1, _e1) in zip(spans, spans[1:]):
            if t1 < e0:
                errors.append(f"引擎冲突 group={gkey[0]} {gkey[1]}: [{t0},{e0}) 与 t={t1} 重叠")

    def peak(intervals: list[tuple[int, int]]) -> int:
        events = []
        for a, b in intervals:
            events.append((a, 1))
            events.append((b, -1))
        events.sort(key=lambda item: (item[0], -item[1]))  # 同刻先开后关
        cur = best = 0
        for _t, delta in events:
            cur += delta
            best = max(best, cur)
        return best

    groups = []
    for group in range(out["V"]):
        layers = model["layers_of_group"][group]
        mexp = len(layers) * ((case["E"] // out["P"]) * case["Z"] + case["Zs"])
        comm_intervals = [
            (start[(mb, layer, op)], end[(mb, layer, op)])
            for mb in range(case["nmb"]) for layer in layers
            for op in ("disp", "comb", "comb_bwd", "disp_bwd")
        ]
        act_intervals = [
            (end[(mb, layer, "comb")], start[(mb, layer, "s_bwd")])
            for mb in range(case["nmb"]) for layer in layers
        ]
        movl = case["U"] * peak(comm_intervals)
        mact = case["Uact"] * peak(act_intervals)
        groups.append((mexp, movl, mact))
        if mexp + movl + mact > case["M"]:
            errors.append(f"内存 group={group} {mexp}+{movl}+{mact} > {case['M']}")

    comp = [
        case["nmb"] * sum(dur[layer][op] for layer in model["layers_of_group"][g] for op in OPS
                          if ENGINE[op] == "C")
        for g in range(out["V"])
    ]
    comm = [
        case["nmb"] * sum(dur[layer][op] for layer in model["layers_of_group"][g] for op in OPS
                          if ENGINE[op] == "N")
        for g in range(out["V"])
    ]
    lb = max(max(comp[g], comm[g]) for g in range(out["V"]))
    return {"ok": not errors, "errors": errors, "time": max(end.values()),
            "groups": groups, "engines": list(zip(comp, comm)), "lb": lb}


def judge_eval(name: str) -> dict:
    """对照用：只以子进程方式调用 CLI（不 import judge）。"""
    proc = subprocess.run(
        [sys.executable, "-m", "judge", "eval", f"cases/{name}.in", f"cases/{name}.out", "--json"],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        return {"ok": False, "errors": [f"judge eval 退出码 {proc.returncode}: {proc.stderr.strip()[:200]}"]}
    return json.loads(proc.stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="独立复核 7 个验收值（不 import judge）")
    parser.add_argument("--cases", nargs="+", default=["ex1", "ex2", "ex3", "ex4", "ex5", "ex6", "mini"])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    expected = json.loads((REPO / "cases/expected.json").read_text(encoding="utf-8"))
    rows, failures = [], 0
    for name in args.cases:
        case = parse_case(REPO / f"cases/{name}.in")
        out = parse_output((REPO / f"cases/{name}.out").read_text(encoding="utf-8"))
        model = build(case, out)
        mine = check(case, out, model)
        theirs = judge_eval(name)
        exp = expected[name]
        agree = (
            mine["ok"] and theirs.get("ok")
            and mine["time"] == theirs.get("time") == exp["time"]
            and mine["lb"] == theirs.get("lb") == exp["lb"]
            and mine["groups"] == [(g["mexp"], g["movl"], g["mact"]) for g in theirs.get("groups", [])]
            and mine["engines"] == [(e["comp"], e["comm"]) for e in theirs.get("engines", [])]
        )
        if not agree:
            failures += 1
        rows.append({
            "case": name, "expected": exp["time"], "independent": mine["time"],
            "judge": theirs.get("time"), "lb": mine["lb"], "judge_lb": theirs.get("lb"),
            "groups": mine["groups"], "engines": mine["engines"], "agree": agree,
            "errors": mine["errors"] + (theirs.get("errors") or []),
        })
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(f"{'case':5} {'expected':>8} {'independent':>11} {'judge':>6} {'lb':>4} {'groups':>18} {'engines':>14}  ok")
        for row in rows:
            print(f"{row['case']:5} {row['expected']:>8} {row['independent']:>11} {str(row['judge']):>6} "
                  f"{row['lb']:>4} {str(row['groups']):>18} {str(row['engines']):>14}  {row['agree']}")
            for err in row["errors"][:3]:
                print(f"       ! {err}")
        print(f"\n合计：{len(rows) - failures}/{len(rows)} 与 judge + expected.json 完全一致")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
