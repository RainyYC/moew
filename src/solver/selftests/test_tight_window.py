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

ROOT = Path(__file__).resolve().parents[3]  # src/solver/selftests/… → 仓库根
sys.path.insert(0, str(ROOT))

from solver import casein, solve, sched  # noqa: E402
from tools.gen_big import build_case, _layer_skew  # noqa: E402

MIB = 1024 * 1024
T = 1_000_000_000


def tight_case_text(memory_kib: int = 60) -> str:
    """2026-10 版：``V·P=R`` 且 ``V≤L``，所以 V=64 的形状要求 ``R=64·P``。

    取 ``N=8, S=16 → R=128``、``P=2 → V=64``、``L=64``，这样每个卡组只有 1 层，
    与真实大用例（b06）同形。`M` 越小，按 `Mact` 推出来的窗口上限越小。
    """
    import random

    rng = random.Random(3)
    return build_case(
        N=8,
        S=16,
        L=64,
        E=64,
        nmb=32,
        layers=[_layer_skew(T, 64, rng) for _ in range(64)],
        Z=1024,
        Zs=0,
        U=1,
        Uact=1024,
        M=memory_kib * 1024,
    )


class TightWindowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path("/tmp/_tight_window_case.in")
        self.path.write_text(tight_case_text(60), encoding="utf-8")
        self.loose_path = Path("/tmp/_loose_window_case.in")
        self.loose_path.write_text(tight_case_text(4096), encoding="utf-8")
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
        self.assertLess(early.time, prio.time, "early 应当优于 prio")
        self.assertLess(
            early.time * 1.5,
            prio.time,
            "被压窗口时 early 应当显著优于 prio（旧实现在这里是 12.8×lb vs 5.4×lb）",
        )

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

    def test_window_candidates_are_bounded(self) -> None:
        """`nmb` 大时不能把 W 逐个枚举（否则上千个候选，预算全花在 W≈nmb 上）。"""
        import random as _random

        from tools.gen_big import build_case as _build

        rng = _random.Random(5)
        text = _build(
            N=4, S=16, L=16, E=64, nmb=1000,
            layers=[_layer_skew(T, 64, rng) for _ in range(16)],
            Z=1 * MIB, Zs=64 * 1024, M=64 * MIB,
        )
        path = Path("/tmp/_window_candidates_big.in")
        path.write_text(text, encoding="utf-8")
        big_case = casein.parse_case(path)
        configs, pmaps = solve.enumerate_configs(big_case)
        cfg = configs[0]
        plan = solve._plan(big_case, pmaps[cfg.P], cfg)
        for big in (False, True):
            windows = sched.window_candidates(big_case, plan, big=big)
            self.assertLessEqual(len(windows), 32, f"big={big} 的窗口候选太多：{len(windows)}")
            self.assertIn(1, windows, "必须包含 W=1")

    def test_best_window_is_probed_early(self) -> None:
        """小窗口往往更好（b11：W≈nmb/8 是 1.00×lb，W=nmb 只有 1.26×lb），
        所以探测顺序必须让小窗口先跑（它们也更便宜）。"""
        import random as _random

        from tools.gen_big import build_case as _build

        rng = _random.Random(3)
        text = _build(
            N=4, S=16, L=4, E=64, nmb=1000,
            layers=[_layer_skew(T, 64, rng) for _ in range(4)],
            Z=1 * MIB, Zs=64 * 1024, M=64 * MIB,
        )
        path = Path("/tmp/_probe_order.in")
        path.write_text(text, encoding="utf-8")
        case = casein.parse_case(path)
        configs, pmaps = solve.enumerate_configs(case)
        cfg = configs[0]
        plan = solve._plan(case, pmaps[cfg.P], cfg)
        windows = sched.window_candidates(case, plan, big=False)
        probe = []
        for frac in (1, 8, 32):
            target = max(1, case.nmb // frac)
            pick = min(windows, key=lambda w: abs(w - target))
            if pick not in probe:
                probe.append(pick)
        # 探测用的三个窗口里，最小的那个必须已经接近下界 —— 否则"先探小窗口"就没有依据
        self.assertGreaterEqual(len(probe), 2)
        small = sched.schedule(case, plan, min(probe), sched.VARIANTS[0], "early")
        self.assertIsNotNone(small)
        self.assertLessEqual(
            small.time, max(1, plan.lb) * 1.2, f"最小窗口 {min(probe)} 的 Time/lb 超过 1.2"
        )

    def test_solver_returns_near_lb(self) -> None:
        """端到端：内存宽松时求解器要拿到接近下界的解。"""
        case = casein.parse_case(self.loose_path)
        solution = solve.solve_case(case, budget=4.0)
        self.assertIsNotNone(solution, "应当总能找到合法解")
        ratio = solution.time / max(1, solution.lb)
        # 结构下限：V 级流水线灌 nmb 个 microbatch，填充代价是 (nmb+V-1)/nmb
        fill = (case.nmb + solution.V - 1) / case.nmb
        self.assertLessEqual(
            ratio, fill * 1.15, f"求解器 Time/lb={ratio:.2f} 超过结构下限 {fill:.2f} 的 1.15 倍"
        )

    def test_very_tight_memory_needs_comm_gap(self) -> None:
        """内存紧到 `gap=0` 永远不合法时，必须靠"通信插空隙"救回来。

        这条例子来自随机压力测试（fuzz）：`Mexp+Movl+Mact` 在 `gap=0` 下必然超，
        只有给通信引擎插 1 个时间单位的空隙才压得住峰值。曾经因为"空灵救援"只写在
        回退分支、而回退又只剩零点几秒，出现过**其实有解却返回无解**（直接 0 分）。
        """
        text = "\n".join(
            [
                "8 1 1467296 200000 1",
                "1 256 1024 1048576 262144 1024 2 32 7 100 1 1000000 1000000",
                "65536 2",
                "1000000",
            ]
        ) + "\n"
        path = Path("/tmp/_tight_gap_case.in")
        path.write_text(text, encoding="utf-8")
        case = casein.parse_case(path)
        solution = solve.solve_case(case, budget=4.0)
        self.assertIsNotNone(solution, "内存虽紧但有解，不能返回无解")
        for group in solution.groups:
            self.assertLessEqual(group.used, case.M)

    def test_fill_gaps_improves_deferred_branches(self) -> None:
        """延后权重梯度旁支并回填计算空隙，应缩短同一优先级的调度。"""
        case = casein.parse_case(self.loose_path)
        configs, pmaps = solve.enumerate_configs(case)
        cfg = configs[0]
        plan = solve._plan(case, pmaps[cfg.P], cfg)
        priority = [
            (int(op in (7, 9)), mb + (layer if op < 4 else 2 * case.L - layer), op)
            for mb in range(case.nmb)
            for layer in range(case.L)
            for op in range(10)
        ]
        plain = sched.schedule(
            case, plan, case.nmb, sched.VARIANTS[0], "prio",
            priority=priority, fill_gaps=False,
        )
        filled = sched.schedule(
            case, plan, case.nmb, sched.VARIANTS[0], "prio",
            priority=priority, fill_gaps=True,
        )
        self.assertIsNotNone(plain)
        self.assertIsNotNone(filled)
        self.assertLess(filled.time, plain.time)
        self.assertEqual(sched.check_schedule(case, plan, filled), [])
        ok, groups = sched.memory_usage(case, plan, filled.start, filled.end)
        self.assertTrue(ok)
    def test_solution_is_legal(self) -> None:
        solution = solve.solve_case(self.case, budget=3.0)
        self.assertIsNotNone(solution)
        for group in solution.groups:
            self.assertLessEqual(group.used, self.case.M, "内存必须不超上限")



if __name__ == "__main__":
    unittest.main()
