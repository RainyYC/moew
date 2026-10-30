"""评分优化项（2026-10-30，``runs/score-impl-20261030``）的回归。

| 用例 | 保护的改动 | 断言 |
| --- | --- | --- |
| ``b13-increasing-nmb``（76 op） | 探窗的 ``nmb/k`` 锚点 | 探窗会探到 ``W ≈ nmb/5``，最终 Time 不高于只探 ``nmb, nmb/8, nmb/32`` |
| ``compute-dominated``（``B=0``，段长 ≫ nmb） | 探窗后其余变体只在大窗口上试 | 最终 Time ≤ 填充界 ×2（`prio` 小窗口会到 30×lb） |
| ``nmb2-l64`` | :func:`solver.solve.v_candidates` | V 候选含小 V；最终解**不**是 V=vmax 的 32.5× 填充 |
| ``nmb=1000`` 大用例 | :func:`solver.solve._modes_for` + ``EARLY_MAX_OPS`` | 出堆模式只有 ``prio`` |
| 任意电池用例 | :func:`solver.solve.enumerate_configs` 的 P 门槛 | 被门槛跳过的 P 的边角下界 ≥ 保留配置的最小 ``lb×填充`` |
| ``bigcases/battery/b13`` | 全部改动 | Time ≤ 4.63265e16（不劣于 2026-10-30 基线），墙钟 < 9.5 s |

夹具用 `casein.parse_case_text` 现场生成（小规模，单测不需要读 bigcases/ 的大文件）。
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from solver import casein, solve  # noqa: E402

BATTERY_B13 = _ROOT / "bigcases" / "battery" / "b13-balanced-compute.in"


def make_case(
    *,
    N: int = 1,
    S: int = 64,
    M: int = 1 << 31,
    Bin: int = 200000,
    Bout: int = 20000,
    L: int = 8,
    E: int = 8,
    Z: int = 65536,
    Zs: int = 1024,
    U: int = 65536,
    Uact: int = 65536,
    k: int = 4,
    nmb: int = 16,
    Fs: int = 1000,
    Fio: int = 1000,
    Fin: int = 1000,
    alpha: int = 500000,
    beta: int = 250000,
    d: int = 100,
    b: int = 16,
    T=1_000_000,
    load=None,
    name: str = "<test>",
) -> casein.Case:
    """拼一个题面 §2 格式的输入并解析成 ``Case``。

    ``load=None`` 时每层按 ``T`` 均分到 ``E`` 个专家；给整数则每个专家取该值（调用方负责让
    ``load·E == T``）；给列表则直接作为该层负载向量。``Bin``/``Bout``/``Fio``/``k``/``d``/``b``
    决定通信量：把 ``k`` 设成 ≥ ``d·b`` 使 ``H = ⌊d·b/k⌋ = 0`` ⇒ ``X = 0``、``x = 0``，
    即"计算主导"形态。
    """
    totals = [T] * L if isinstance(T, int) else list(T)
    lines = [
        f"{N} {S} {M} {Bin} {Bout}",
        f"{L} {E} {Z} {Zs} {U} {Uact} {k} {nmb} {Fs} {Fio} {Fin} {alpha} {beta}",
        f"{d} {b}",
    ]
    for total in totals:
        if isinstance(load, (list, tuple)):
            per_e = list(load)
        elif load is not None:
            per_e = [load] * E
        else:  # 均衡：按 T 均分（解析器要求 Σa = T）
            base, extra = divmod(total, E)
            per_e = [base + (1 if index < extra else 0) for index in range(E)]
        lines.append(" ".join([str(total)] + [str(value) for value in per_e]))
    return casein.parse_case_text("\n".join(lines) + "\n", name=name)


class ProbeRegressionTest(unittest.TestCase):
    """探窗锚点与"变体只在大窗口上试"。"""

    def test_probe_targets_reach_fifths(self) -> None:
        """``nmb=102, V=8``：探窗目标必须覆盖 ``nmb/5``（b13 的最优窗口），而不是只有 nmb/8。"""
        case = make_case(L=8, nmb=102, E=64, S=64)
        configs, pmaps = solve.enumerate_configs(case)
        plan = solve._plan(case, pmaps[configs[0].P], configs[0])
        targets = solve._probe_targets(case, plan)
        self.assertIn(102 // 8, targets, "旧锚点 nmb/8 必须保留（b11 靠它）")
        self.assertTrue(any(abs(t - 102 // 5) <= 2 for t in targets), f"没探到 nmb/5：{targets}")

    def test_compute_dominated_keeps_filling_bound(self) -> None:
        """``B=0``（x=0、算力主导）：最终 Time 必须接近填充界 ``(nmb+V-1)·seg``。

        b12 的教训：`prio` 在小窗口（W≈nmb/5）上是 30×lb。修复后探窗只用
        "比已探窗口更大"的窗口扫变体，不能被小窗口带走。
        """
        case = make_case(L=8, nmb=16, E=64, S=64, k=10**6, T=1_000_000)
        self.assertEqual(case.H, 0, "夹具应让通信载荷为 0（x=0，计算主导）")
        solution = solve.solve_case(case, budget=4.0)
        self.assertIsNotNone(solution)
        fill = (case.nmb + solution.V - 1) / case.nmb
        self.assertLessEqual(solution.time, solution.lb * fill * 2,
                             f"被小窗口的 prio 带偏：Time={solution.time} lb={solution.lb}")


class VCandidatesTest(unittest.TestCase):
    """隐藏点（nmb ≪ L）的 V 候选。"""

    def test_small_nmb_gets_small_v(self) -> None:
        case = make_case(L=64, nmb=2, E=8, S=64)
        vmax = min(case.L, 64, case.R)
        cands = solve.v_candidates(case, 1)
        self.assertEqual(cands[0], vmax, "首选必须仍是 vmax（电池用例不受影响）")
        self.assertTrue(any(v <= vmax // 4 for v in cands), f"小 V 候选缺失：{cands}")
        solution = solve.solve_case(case, budget=4.0)
        self.assertIsNotNone(solution)
        self.assertLess(solution.V, vmax, f"仍然选了 V={solution.V}（填充 (nmb+V-1)/nmb 爆炸）")

    def test_large_nmb_unchanged(self) -> None:
        case = make_case(L=64, nmb=1000, E=8, S=64)
        self.assertEqual(solve.v_candidates(case, 1), [min(case.L, 64, case.R)])

    def test_single_card(self) -> None:
        case = make_case(N=1, S=1, L=64, nmb=2, E=4)
        self.assertEqual(solve.v_candidates(case, 1), [1])


class EarlyGuardTest(unittest.TestCase):
    """大用例禁用 ``early``（单次 21.6 s 会撞穿 10 s 时限 ⇒ 该点 0 分）。"""

    def test_early_disabled_for_huge_cases(self) -> None:
        case = make_case(L=64, nmb=1000, E=4, S=64)
        self.assertGreater(case.n_ops, solve.EARLY_MAX_OPS)
        configs, pmaps = solve.enumerate_configs(case)
        plan = solve._plan(case, pmaps[configs[0].P], configs[0])
        for big in (False, True):
            self.assertEqual(solve._modes_for(case, plan, big), ("prio",))

    def test_early_allowed_for_mid_cases(self) -> None:
        case = make_case(L=16, nmb=64, E=8, S=16)
        self.assertLessEqual(case.n_ops, solve.EARLY_MAX_OPS)
        configs, pmaps = solve.enumerate_configs(case)
        plan = solve._plan(case, pmaps[configs[0].P], configs[0])
        self.assertIn("early", solve._modes_for(case, plan, False))


class PGateTest(unittest.TestCase):
    """P 门槛只剪"不可能更好"的 P（纯省时，不改最优）。"""

    def test_gate_never_hides_a_contender(self) -> None:
        case = make_case(L=16, nmb=64, E=4, S=64)
        configs, _pmaps = solve.enumerate_configs(case)
        kept = {config.P for config in configs}
        best_key = min(config.lb * max(1, case.nmb + config.V - 1) // case.nmb
                       for config in configs)
        for P in solve.p_candidates(case):
            if P in kept or case.R % P:
                continue
            info = solve._pmap(case, P)
            quick = case.nmb * max(
                case.L * sum(case.T) * case.Fs,
                sum(sum(row[i] for i in (1, 3, 5, 8)) for row in info.durations),
            )
            self.assertGreaterEqual(quick, best_key,
                                    f"P={P} 的边角下界 {quick} 可能优于已保留解 {best_key}")


@unittest.skipUnless(BATTERY_B13.exists(), "需要 bigcases/battery/b13-balanced-compute.in")
class BatteryB13Test(unittest.TestCase):
    """b13：探窗锚点在真实大用例上不退化。"""

    def test_b13_does_not_regress(self) -> None:
        case = casein.parse_case(BATTERY_B13)
        started = time.monotonic()
        solution = solve.solve_case(case, budget=7.0)
        self.assertIsNotNone(solution)
        self.assertLess(time.monotonic() - started, 9.5)
        self.assertLessEqual(solution.time, 46_326_548_000_000_000,
                             "b13 比 2026-10-30 基线更差（探窗顺序 / 预算分配回退）")


if __name__ == "__main__":
    unittest.main()
