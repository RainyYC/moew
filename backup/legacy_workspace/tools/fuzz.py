#!/usr/bin/env python3
"""随机压力测试：在题面 §6 的范围内随机造用例，找出求解器的未知缺口。

检查三件事：
1. **是否超时**（>10 s 硬上限 → 该测试点 0 分）；
2. **是否合法**（交给 `judge.core.evaluate` 判定）；
3. **离下界多远**（`Time / lb`，lb 是题面 §4.2 第 3 条的引擎工作量下界）。

只看这三条，不做最优性判定（最优判定要靠 CP-SAT，且只适合小用例）。

用法：
    python3 tools/fuzz.py [--count 12] [--seed 1] [--time-limit 60]
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from judge.core.evaluate import evaluate  # noqa: E402
from judge.core.parse import parse_case  # noqa: E402
from solver import casein, solve  # noqa: E402

MIB = 1024 * 1024
GIB = 1024 * MIB


def divisors_of(n: int) -> list[int]:
    return [d for d in range(1, n + 1) if n % d == 0]


def random_case(rng: random.Random, index: int) -> tuple[str, dict]:
    """按 §6 的范围随机生成一个输入文本。"""
    # 集群
    N = rng.choice([1, 2, 4, 8, 16, 32])
    S = rng.choice([1, 2, 4, 8, 16])
    R = N * S
    # 模型
    L = rng.choice([1, 2, 4, 8, 16, 32, 64])
    E = rng.choice([3, 4, 8, 16, 32, 64, 128, 256, 512])
    k = rng.choice([1, 2, 4, 8, 16, 32, 64])
    nmb = rng.choice([2, 4, 8, 16, 64, 128, 512, 1000])
    # 时间系数
    Fs = rng.choice([0, 1, 7])
    Fio = rng.choice([10, 100, 10_000])
    Fin = rng.choice([1, 4, 9])
    ax = rng.choice([0, 500_000, 1_000_000, 2_000_000])
    bx = rng.choice([0, 500_000, 1_000_000, 2_000_000])
    # 内存与缓冲（§6：U, Uact ≤ 2^18）
    U = rng.choice([1, 1024, 256 * 1024])
    Uact = rng.choice([1, 1024, 256 * 1024])
    Z = rng.choice([1024, MIB, 4 * MIB, 16 * MIB])
    Zs = rng.choice([0, 64 * 1024, MIB])
    # 带宽（§6：1 ≤ Bout ≤ Bin ≤ 2e5）
    Bin = rng.choice([20_000, 200_000])
    Bout = rng.choice([1, 2_000, 20_000])
    # 隐层
    d = rng.choice([256, 2048, 2 ** 16])
    b = rng.choice([1, 2, 4])

    # 每层 T：k 的倍数，且 max/min ≤ 1.2
    base_slots = rng.choice([64, 1024, 100_000, 1_000_000, 10_000_000])
    base = max(k, (base_slots // k) * k)
    if base <= 0:
        base = k
    layers: list[str] = []
    for layer in range(L):
        T = base
        if rng.random() < 0.4:
            T = max(k, ((int(base * rng.uniform(0.84, 1.0))) // k) * k)
        # 偏斜：按 Zipf 权重分配
        if rng.random() < 0.6 and E > 1:
            weights = [1.0 / (rank + 1) ** rng.uniform(0.5, 1.6) for rank in range(E)]
            total = sum(weights)
            slots = [int(T * w / total) for w in weights]
            slots[0] += T - sum(slots)
            layers.append(" ".join([str(T)] + [str(v) for v in slots]))
        else:
            layers.append(str(T))

    # M：取"最小驻留量"的 1.05–6 倍，保证可行但可能很紧
    best_residency = None
    for P in divisors_of(E):
        if not (P <= S and S % P == 0) and not (S and P % S == 0):
            continue
        if R % P:
            continue
        for V in divisors_of(R // P):
            if V > L:
                continue
            residency = math.ceil(L / V) * ((E // P) * Z + Zs)
            best_residency = residency if best_residency is None else min(best_residency, residency)
    if best_residency is None:
        best_residency = L * (E * Z + Zs)
    M = int(best_residency * rng.uniform(1.05, 6.0))
    M = max(M, best_residency)

    text = "\n".join(
        [
            f"{N} {S} {M} {Bin} {Bout}",
            f"{L} {E} {Z} {Zs} {U} {Uact} {k} {nmb} {Fs} {Fio} {Fin} {ax} {bx}",
            f"{d} {b}",
            *layers,
        ]
    ) + "\n"
    meta = dict(index=index, N=N, S=S, R=R, L=L, E=E, k=k, nmb=nmb, Z=Z, M=M,
                ops=L * nmb * 10, Bin=Bin, Bout=Bout, U=U, Uact=Uact)
    return text, meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--count", type=int, default=12)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--time-limit", type=float, default=60.0)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    out_dir = Path("data/battery/fuzz")
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for index in range(args.count):
        text, meta = random_case(rng, index)
        path = out_dir / f"f{index:02d}.in"
        path.write_text(text, encoding="utf-8")
        case = casein.parse_case(path)
        started = time.monotonic()
        solution = solve.solve_case(case, budget=8.0)
        elapsed = time.monotonic() - started
        if solution is None:
            rows.append((index, meta, elapsed, None, None, "无解"))
            print(f"f{index:02d} ops={meta['ops']:7d} {elapsed:5.1f}s  无合法解", flush=True)
            continue
        # 直接拿 Solution 已经渲染好的文本判题
        text_out = solution.text
        (out_dir / f"f{index:02d}.out").write_text(text_out, encoding="utf-8")
        judge_case = parse_case(path)
        result = evaluate(judge_case, text_out)
        ratio = solution.time / max(1, solution.lb)
        flag = ""
        if elapsed > 10:
            flag += " 超时!"
        if not result.get("ok"):
            flag += " 非法!"
        if ratio > 3:
            flag += " 差距大!"
        rows.append((index, meta, elapsed, ratio, result.get("ok"), flag))
        print(
            f"f{index:02d} ops={meta['ops']:7d} R={meta['R']:3d} L={meta['L']:2d} "
            f"E={meta['E']:3d} nmb={meta['nmb']:4d} {elapsed:5.1f}s "
            f"Time/lb={ratio:5.2f} ok={result.get('ok')}{flag}",
            flush=True,
        )

    bad = [r for r in rows if r[5] and r[5].strip()]
    print(f"\n合计 {len(rows)} 例，异常 {len(bad)} 例")
    for r in bad:
        print(f"  f{r[0]:02d} {r[5]}  meta={r[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
