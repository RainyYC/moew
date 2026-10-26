"""回归测试：内存紧 → 窗口被压小 → 调度器不能退化成"分批推进"。

背景：`prio` 出堆（按方向/mb/层排序）在窗口小于 `nmb` 时会把所有前向挤成一批、
反向再挤成一批，64 个卡组的并行度掉到 2 个，实测 b06（64 万条 op）慢 **29 倍**
（1.57e17 vs 5.4e15）。改成"窗口被压小时优先用 `early` 出堆"后恢复到 1.09×lb。

本测试用一个小规模夹具复现同一形态（`nmb=32`、窗口上限 13）：
`prio` 单独跑约 5.1×lb，`early` 约 1.4×lb。因此断言 `Time/lb ≤ 2.0` 既能容忍正常波动，
又能在有人把 `early` 去掉时立刻失败。

运行：
    python3 -m unittest discover -s solver/selftests -t . -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from solver import casein, solve, sched  # noqa: E402
from tools.gen_big import build_case, _layer_skew  # noqa: E402

MIB = 1024 * 1024
T = 1_000_000_000


def tight_case_text() -> str:
    import random

    rng = random.Random(3)
    return build_case(
        N=4,
        S=16,
        L=8,
        E=64,
        nmb=32,
        layers=[_layer_skew(T, 64, rng) for _ in range(8)],
        Z=1 * MIB,
        Zs=64 * 1024,
        M=20 * MIB,
    )


class TightWindowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path("/tmp/_tight_window_case.in")
        self.path.write_text(tight_case_text(), encoding="utf-8")
        self.case = casein.parse_case(self.path)

    def test_window_is_actually_capped(self) -> None:
        """夹具必须真的把窗口压到 nmb 以下，否则这个测试什么都没测。"""
        configs, pmaps = solve.enumerate_configs(self.case)
        self.assertTrue(configs, "夹具应当至少有一个可行配置")
        cfg = configs[0]
        plan = solve._plan(self.case, pmaps[cfg.P], cfg)
        cap = solve._window_cap(self.case, plan)
        self.assertIsNotNone(cap)
        self.assertLess(cap, self.case.nmb, "窗口没有被压小，夹具失效")

    def test_early_mode_beats_prio_when_capped(self) -> None:
        """被压窗口时 `early` 必须显著优于 `prio`（这是修复的核心依据）。"""
        configs, pmaps = solve.enumerate_configs(self.case)
        cfg = configs[0]
        plan = solve._plan(self.case, pmaps[cfg.P], cfg)
        cap = solve._window_cap(self.case, plan)
        window = min(cap or self.case.nmb, self.case.nmb)
        prio = sched.schedule(self.case, plan, window, sched.VARIANTS[0], "prio")
        early = sched.schedule(self.case, plan, window, sched.VARIANTS[0], "early")
        self.assertIsNotNone(prio)
        self.assertIsNotNone(early)
        self.assertLess(early.time, prio.time, "early 应当不劣于 prio")
        ratio = early.time / max(1, plan.lb)
        self.assertLessEqual(ratio, 2.0, f"early 的 Time/lb={ratio:.2f} 超过 2.0")

    def test_mode_order_for_big_cases(self) -> None:
        """大用例（n_ops>120k）也要在被压窗口时优先用 `early`。

        这条直接测决策函数，所以不需要真的跑 64 万条 op 的调度。
        """
        from tools.gen_big import build_case as _build

        import random as _random

        rng = _random.Random(11)
        text = _build(
            N=4, S=16, L=16, E=64, nmb=1000,
            layers=[_layer_skew(T, 64, rng) for _ in range(16)],
            Z=1 * MIB, Zs=64 * 1024, M=20 * MIB,
        )
        path = Path("/tmp/_tight_window_big.in")
        path.write_text(text, encoding="utf-8")
        big_case = casein.parse_case(path)
        self.assertGreater(big_case.n_ops, 120_000, "夹具必须落在 big 分支")
        configs, pmaps = solve.enumerate_configs(big_case)
        cfg = configs[0]
        plan = solve._plan(big_case, pmaps[cfg.P], cfg)
        cap = solve._window_cap(big_case, plan)
        self.assertLess(cap, big_case.nmb, "大夹具的窗口也应当被压小")
        self.assertEqual(solve._modes_for(big_case, plan, True)[0], "early")

    def test_solver_returns_near_lb(self) -> None:
        """端到端：求解器在小预算下也要拿到接近下界的解，不能退化 5 倍。"""
        solution = solve.solve_case(self.case, budget=3.0)
        self.assertIsNotNone(solution, "应当总能找到合法解")
        ratio = solution.time / max(1, solution.lb)
        self.assertLessEqual(ratio, 2.0, f"求解器 Time/lb={ratio:.2f} 超过 2.0")

    def test_solution_is_legal(self) -> None:
        solution = solve.solve_case(self.case, budget=3.0)
        self.assertIsNotNone(solution)
        for group in solution.groups:
            self.assertLessEqual(group.used, self.case.M, "内存必须不超上限")


if __name__ == "__main__":
    unittest.main()
