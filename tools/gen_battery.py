#!/usr/bin/env python3
"""生成"大样例"电池：在题面 §6 的范围内把各个角落都扫一遍。

官方 6 个样例的规模被刻意压到可手算（`R≤4, L≤2, E≤4, nmb=2`，最多 40 条 op），
而 §6 允许的上限是 `R≤512, L≤64, E≤512, nmb≤10^3`，即**单次运行 64 万条 op**。
本脚本按上限附近造用例，每组只变一个维度，便于定位求解器在哪类实例上吃力。

产物：`data/battery/*.in` + `MANIFEST.md`（每例变了哪个维度）。

用法：
    python3 tools/gen_battery.py            # 生成
    python3 tools/gen_battery.py --list     # 只看清单
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from gen_big import MIB, build_case, _layer_balanced, _layer_skew

OUT = Path(__file__).resolve().parent.parent / "data" / "battery"
T = 1_000_000_000  # §6：T_ℓ ≤ 1e9，且须是 k 的倍数
T_LOW = 900_000_000  # §6：max T/min T ≤ 1.2


def layers_balanced(count: int, T_value: int = T) -> list[str]:
    return [_layer_balanced(T_value)] * count


def layers_skew(count: int, E: int, seed: int = 7, alpha: float = 1.2) -> list[str]:
    rng = random.Random(seed)
    return [_layer_skew(T, E, rng, alpha=alpha) for _ in range(count)]


def layers_mixed(count: int, E: int, seed: int = 9) -> list[str]:
    """1/3 均衡、1/3 普通偏斜、1/3 极端偏斜（1/64 的专家吃掉几乎全部负载）。"""
    rng = random.Random(seed)
    out: list[str] = []
    for layer in range(count):
        if layer < count // 3:
            out.append(_layer_balanced(T))
        elif layer < 2 * count // 3:
            out.append(_layer_skew(T, E, rng, alpha=1.5))
        else:
            hot_count = max(1, E // 64)
            rest = E - hot_count
            share = (T * 3) // 4 // hot_count
            other = (T - share * hot_count) // max(1, rest)
            row = [share] * hot_count + [other] * rest
            row[0] += T - sum(row)
            out.append(" ".join([str(T)] + [str(v) for v in row]))
    return out


#: name -> (kwargs for build_case, 一句话说明)
CASES: dict[str, tuple[dict, str]] = {
    # —— 基线：最大规模、内存宽松（于是 P=1，退化成纯计算问题）
    "b01-loose": (
        dict(N=32, S=16, L=64, E=512, nmb=102, layers=layers_skew(64, 512), M=2 * 1024 * MIB),
        "R=512 L=64 E=512 nmb=102，内存宽松 → 期望 P=1",
    ),
    # —— 同一负载，逐步收紧内存，逼 P 变大
    "b02-m512": (
        dict(N=32, S=16, L=64, E=512, nmb=102, layers=layers_skew(64, 512), M=512 * MIB),
        "同上，M=512MiB",
    ),
    "b03-m256": (
        dict(N=32, S=16, L=64, E=512, nmb=102, layers=layers_skew(64, 512), M=256 * MIB),
        "同上，M=256MiB（P≈4）",
    ),
    "b04-m96": (
        dict(N=32, S=16, L=64, E=512, nmb=102, layers=layers_skew(64, 512), M=96 * MIB),
        "同上，M=96MiB（P≈8，接近内存下限）",
    ),
    # —— 把 nmb 拉到上限：单次 64 万条 op
    "b05-maxmb": (
        dict(N=32, S=16, L=64, E=512, nmb=1000, layers=layers_balanced(64), M=2 * 1024 * MIB),
        "nmb=1000 → **64 万条 op**，内存宽松",
    ),
    "b06-maxmb-tight": (
        dict(N=32, S=16, L=64, E=512, nmb=1000, layers=layers_skew(64, 512), M=256 * MIB),
        "nmb=1000 + M=256MiB（最坏组合）",
    ),
    # —— 偏斜负载（影响 m_ℓ，只影响计算）
    "b07-mixed": (
        dict(N=32, S=16, L=64, E=512, nmb=1000, layers=layers_mixed(64, 512), M=512 * MIB),
        "1/3 均衡 + 1/3 偏斜 + 1/3 极端偏斜，nmb=1000",
    ),
    # —— 带宽极端：跨节点极窄
    "b08-narrow": (
        dict(N=32, S=16, L=64, E=512, nmb=256, layers=layers_skew(64, 512), M=256 * MIB),
        "Bout=1（跨节点极窄），迫使 P 留在节点内",
    ),
    # —— 小 E：专家数少，放置自由度低
    "b09-small-e": (
        dict(N=4, S=16, L=64, E=4, nmb=1000, layers=layers_balanced(64), M=1024 * MIB),
        "E=4、R=64、nmb=1000 → 64 万条 op，无放置自由度",
    ),
    # —— 高 k：H 变小，通信量下降
    "b10-high-k": (
        dict(N=32, S=16, L=64, E=512, nmb=512, layers=layers_skew(64, 512),
             k=64, M=256 * MIB),
        "k=64（H=⌊d·b/k⌋ 很小）→ 通信不再是瓶颈",
    ),
    # —— 短层数、多 stage：V 受限
    "b11-short-l": (
        dict(N=32, S=16, L=4, E=512, nmb=1000, layers=layers_skew(4, 512), M=256 * MIB),
        "L=4、nmb=1000 → V≤4，流水线深度不足",
    ),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, (kwargs, note) in CASES.items():
        if name == "b08-narrow":
            text = build_case(**kwargs)
            head, rest = text.split("\n", 1)
            parts = head.split()
            parts[4] = "1"  # Bout = 1
            text = " ".join(parts) + "\n" + rest
        else:
            text = build_case(**kwargs)
        path = OUT / f"{name}.in"
        if not args.list:
            path.write_text(text, encoding="utf-8")
        lines = text.splitlines()
        l2 = lines[1].split()
        L, E, nmb = int(l2[0]), int(l2[1]), int(l2[7])
        ops = L * nmb * 10
        rows.append((name, L, E, nmb, ops, int(lines[0].split()[2]), note))

    manifest = ["# 大样例电池（MANIFEST）", "",
                "官方样例最多 40 条 op；本目录按题面 §6 的上限造用例。", "",
                "| 用例 | L | E | nmb | ops | M | 变动的维度 |",
                "| --- | --- | --- | --- | --- | --- | --- |"]
    for name, L, E, nmb, ops, M, note in rows:
        mib = M / MIB
        mtext = f"{mib:.0f} MiB" if mib >= 1 else f"{M / 1024:.0f} KiB"
        manifest.append(f"| `{name}.in` | {L} | {E} | {nmb} | {ops:,} | {mtext} | {note} |")
    manifest.append("")
    (OUT / "MANIFEST.md").write_text("\n".join(manifest) + "\n", encoding="utf-8")

    for name, L, E, nmb, ops, M, note in rows:
        print(f"{name:16s} L={L:2d} E={E:3d} nmb={nmb:4d} ops={ops:7d}  {note}")
    print(f"\n→ {OUT}/  （共 {len(rows)} 个）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
