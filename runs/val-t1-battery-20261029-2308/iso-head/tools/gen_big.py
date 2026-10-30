#!/usr/bin/env python3
"""生成大规模（题面范围内）测试输入，用于压测判题器 / 服务层 / 求解器。

用法：
    python3 tools/gen_big.py --out bigcases

产物（都在 out 目录下，默认 bigcases/）：
    big-wide.in     N=32 S=16 (R=512), L=64, E=512, nmb=102, 负载均衡      → ops ≈ 65 280
    big-skew.in     同上规模，逐层 Zipf 偏斜（负载向量）                    → 同上
    big-mixed.in    同上规模，一半均衡一半偏斜 + T 取上限附近               → 同上
    big-small-nmb.in L=64 E=512 但 nmb=2                                    → ops ≈ 1 280
    stress-ops.in   **超出题面范围**（nmb=1000），只为压测 ops 切片接口      → ops ≈ 640 000

题面范围（problem-fixed.md §6）：N≤32, S≤16, R≤512, E≤512, L≤64, k≤64,
nmb≤103 且为偶数, Ts≤1e9, d≤2^16, b∈{1,2,4}, V≤64。

本脚本只保证"输入本身合法"（各字段在范围内、负载向量求和等于 T），
不保证对每个规模都存在内存可行解——`big-*` 系列已按 M 选得足够大。
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

MIB = 1024 * 1024
GIB = 1024 * MIB


def _line1(N: int, S: int, M: int, Bin: int, Bout: int) -> str:
    return f"{N} {S} {M} {Bin} {Bout}"


def _line2(
    L: int,
    E: int,
    Z: int,
    Zs: int,
    U: int,
    Uact: int,
    k: int,
    nmb: int,
    Fs: int,
    Fio: int,
    Fin: int,
    ax: int,
    bx: int,
) -> str:
    return f"{L} {E} {Z} {Zs} {U} {Uact} {k} {nmb} {Fs} {Fio} {Fin} {ax} {bx}"


def _zipf_weights(E: int, rng: random.Random, alpha: float = 1.15) -> list[float]:
    raw = [1.0 / (rank**alpha) for rank in range(1, E + 1)]
    rng.shuffle(raw)  # 打散，避免"永远专家 0 最热"
    return raw


def _layer_balanced(T: int) -> str:
    return str(T)


def _layer_skew(T: int, E: int, rng: random.Random, alpha: float = 1.15) -> str:
    """把 T 个 slot 分给 E 个专家：Zipf 权重取整，余数补给权重最大的几个。"""
    weights = _zipf_weights(E, rng, alpha)
    total_w = sum(weights)
    raw = [T * w / total_w for w in weights]
    slots = [int(value) for value in raw]
    remainder = T - sum(slots)
    order = sorted(range(E), key=lambda e: (-(raw[e] - slots[e]), e))
    for i in range(remainder):
        slots[order[i % E]] += 1
    return " ".join([str(T)] + [str(v) for v in slots])


def build_case(
    *,
    N: int,
    S: int,
    L: int,
    E: int,
    nmb: int,
    layers: list[str],
    Z: int = MIB,
    Zs: int = 64 * 1024,
    U: int = 256 * 1024,      # ≤ 2^18（§6）
    Uact: int = 256 * 1024,   # ≤ 2^18（§6）
    k: int = 4,
    d: int = 65536,
    b: int = 2,
    Fs: int = 7,
    Fio: int = 10_000,
    Fin: int = 9,
    ax: int = 1_000_000,
    bx: int = 1_000_000,
    M: int | None = None,
) -> str:
    R = N * S
    if M is None:
        # 取 V=8,P=16 时的 Mexp 的 4 倍，留出 Movl/Mact 余量
        per_group_layers = (L + 7) // 8
        mexp = per_group_layers * ((E // 16) * Z + Zs)
        M = max(mexp * 4, 2 * GIB)
    lines = [
        _line1(N, S, M, 200_000, 20_000),
        _line2(L, E, Z, Zs, U, Uact, k, nmb, Fs, Fio, Fin, ax, bx),
        f"{d} {b}",
        *layers,
    ]
    return "\n".join(lines) + "\n"


def gen_all(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20261020)
    T = 1_000_000_000  # §6：T_l ≤ 1e9，且必须是 k 的倍数（k=4 ⇒ 1e9 可被整除）
    T_low = 900_000_000  # §6：max T_l / min T_l ≤ 1.2
    N, S, L, E = 32, 16, 64, 512
    nmb = 102

    written: list[Path] = []

    def emit(name: str, text: str) -> None:
        path = out_dir / f"{name}.in"
        path.write_text(text, encoding="utf-8")
        written.append(path)

    # 1) 全均衡
    emit(
        "big-wide",
        build_case(N=N, S=S, L=L, E=E, nmb=nmb, layers=[_layer_balanced(T)] * L),
    )

    # 2) 逐层偏斜（每层偏斜方向不同）
    emit(
        "big-skew",
        build_case(
            N=N,
            S=S,
            L=L,
            E=E,
            nmb=nmb,
            layers=[
                _layer_skew(T if layer % 3 else T_low, E, rng, alpha=1.1 + 0.1 * (layer % 3))
                for layer in range(L)
            ],
        ),
    )

    # 3) 混合：前 1/3 均衡、中间 1/3 偏斜、后 1/3 极端（90% 集中在前 8 个专家）
    mixed: list[str] = []
    for layer in range(L):
        if layer < L // 3:
            mixed.append(_layer_balanced(T))
        elif layer < 2 * L // 3:
            mixed.append(_layer_skew(T, E, rng, alpha=1.4))
        else:
            hot = [0] * E
            share = T // (E // 64)  # 1/64 的专家吃掉几乎全部
            hot = [share] * (E // 64) + [max(0, (T - share * (E // 64)) // (E - E // 64))] * (
                E - E // 64
            )
            delta = T - sum(hot)
            hot[0] += delta
            mixed.append(" ".join([str(T)] + [str(v) for v in hot]))
    emit("big-mixed", build_case(N=N, S=S, L=L, E=E, nmb=nmb, layers=mixed))

    # 4) 同规模但 nmb 最小值（测"层多、mb 少"的形态）
    emit(
        "big-small-nmb",
        build_case(N=N, S=S, L=L, E=E, nmb=2, layers=[_layer_skew(T, E, rng) for _ in range(L)]),
    )

    # 4b) 内存受限：M=256MiB 迫使 P≥4（P=1/2 的 Mexp 放不下），让 AllToAll 真正参与
    emit(
        "big-tight",
        build_case(
            N=N,
            S=S,
            L=L,
            E=E,
            nmb=nmb,
            layers=[_layer_skew(T, E, rng, alpha=1.2) for _ in range(L)],
            M=256 * MIB,
        ),
    )

    # 5) 超出题面范围的切片压测（nmb=1000 → ops≈64 万），仅用于 ops 接口性能
    emit(
        "stress-ops",
        build_case(N=N, S=S, L=L, E=E, nmb=1000, layers=[_layer_balanced(T)] * L),
    )

    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="bigcases", help="输出目录（默认 bigcases/）")
    args = ap.parse_args()
    out_dir = Path(args.out)
    paths = gen_all(out_dir)
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        layer_count = int(lines[1].split()[0])
        nmb = int(lines[1].split()[7])
        print(f"{path}  L={layer_count} nmb={nmb}  预计 ops≈{layer_count * nmb * 10:,}")
    print(f"\n共生成 {len(paths)} 个输入 → {out_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
