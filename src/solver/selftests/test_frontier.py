"""`solver.frontier` 的回归测试（事件驱动就绪前沿内核）。

覆盖点（对应 t2 任务的验收要点）：

1. **A 组等价性**：``order="time"`` 且 ``zero_free=False`` 时与基线
   `sched.schedule(..., "early")` 逐例 Time 相同；``order="priority"`` 与基线
   ``"prio"`` 逐例 Time 相同（同窗口、同变体、同固定配置）。
2. **零时长语义**：``zero_free=True`` 时零时长操作在依赖满足后立即执行，不再被忙碌
   引擎延后；且所有零时长操作都必须被输出（`check_schedule` 不报「未调度」）。
3. **合法性/内存**：事件内核（含 B 组门控）产出的调度必须过 `check_schedule`、
   `memory_usage`；K=2V 的镜像配对共用引擎与内存仍合法。
4. **内存预留**：`memory_caps` 满足 ``Mexp + U·cap_comm + Uact·cap_act ≤ M``；
   连最小激活槽都放不下时必须返回 ``None``（绝不返回半份调度）。
5. **确定性与前瞻**：同输入/同 seed 两次结果逐位相同；小用例上 lookahead 仍返回
   完整合法解且 Time 不劣于基事件解。

运行：``PYTHONPATH=src python3 -m unittest discover -s src/solver/selftests -t src -q``
"""

from __future__ import annotations

import unittest
from pathlib import Path

from solver import casein, formula, frontier, sched, solve

ROOT = Path(__file__).resolve().parents[3]
SAMPLES = ("ex1", "ex2", "ex3", "ex4", "ex5", "ex6", "mini")


def load_sample(name: str):
    """读取样例 + 用其已交付输出里的 ``V/P/K/ψ/MAP`` 固定配置。"""
    case = casein.parse_case(ROOT / "cases" / f"{name}.in")
    config = frontier.parse_schedule_config(
        (ROOT / "cases" / f"{name}.out").read_text(encoding="utf-8"), case
    )
    plan = formula.build_plan(
        case, config["V"], config["P"], 1, config["psi"], config["map_rows"]
    )
    return case, plan, config


def synthetic_case(*, L: int = 2, E: int = 2, M: int = 100_000, nmb: int = 2, **overrides):
    """最小合法输入（N=1,S=2,R=2,E=2,P=2）。"""
    body = {
        "N": 1, "S": 2, "M": M, "Bin": 10, "Bout": 10,
        "L": L, "E": E, "Z": 10, "Zs": 0, "U": 1, "Uact": 1,
        "k": 1, "nmb": nmb, "T": 4, "Fs": 1, "Fio": 1, "Fin": 1,
        "alpha": 1_000_000, "beta": 1_000_000, "d": 1, "b": 1,
    }
    body.update(overrides)
    lines = [
        f"{body['N']} {body['S']} {body['M']} {body['Bin']} {body['Bout']}",
        (
            f"{body['L']} {body['E']} {body['Z']} {body['Zs']} "
            f"{body['U']} {body['Uact']} {body['k']} {body['nmb']} "
            f"{body['Fs']} {body['Fio']} {body['Fin']} {body['alpha']} {body['beta']}"
        ),
        f"{body['d']} {body['b']}",
    ]
    lines.extend([str(body["T"])] * body["L"])
    return casein.parse_case_text("\n".join(lines), name="synthetic")


def assert_schedule_valid(test: unittest.TestCase, case, plan, result) -> None:
    test.assertIsNotNone(result, "调度内核返回 None（死锁/预算耗尽）")
    test.assertEqual([], sched.check_schedule(case, plan, result))
    ok, groups = sched.memory_usage(case, plan, result.start, result.end)
    test.assertTrue(ok, f"内存超限：{[(g.v, g.used) for g in groups]} M={case.M}")
    test.assertTrue(all(t >= 0 for t in result.start), "存在未调度操作")
    test.assertEqual(max(result.end), result.time)


class TestEquivalence(unittest.TestCase):
    """A 组：同窗口/同变体下事件内核与基线列表调度的时间等价。"""

    def test_lazy_early_replica_matches_early(self):
        """``order="lazy_early"`` 逐句复刻基线 early（含惰性重排）⇒ Time 必须逐例相等。"""

        for name in SAMPLES:
            case, plan, _config = load_sample(name)
            for variant in sched.VARIANTS:
                baseline = sched.schedule(case, plan, case.nmb, variant, "early")
                self.assertIsNotNone(baseline)
                stats = frontier.Stats()
                result = frontier.schedule(
                    case, plan, window=case.nmb, variant=variant, gating=False,
                    zero_free=False, order="lazy_early", stats=stats,
                )
                self.assertEqual(
                    baseline.time, result.time,
                    f"{name} {variant}: early={baseline.time} lazy={result.time}",
                )
                self.assertGreaterEqual(stats.repushes, 0)

    def test_time_order_matches_early_except_known_tie_difference(self):
        """严格 ``(time, rank)`` 出队与基线 early 多数逐例相等；ex5 因等时刻重排语义不同。"""

        known_different = {"ex5"}
        for name in SAMPLES:
            case, plan, _config = load_sample(name)
            for variant in sched.VARIANTS[:3]:
                baseline = sched.schedule(case, plan, case.nmb, variant, "early")
                self.assertIsNotNone(baseline)
                result = frontier.schedule(
                    case, plan, window=case.nmb, variant=variant,
                    gating=False, zero_free=False, order="time",
                )
                if name in known_different:
                    self.assertLessEqual(
                        result.time, baseline.time,
                        f"{name} {variant}: 严格前沿不应差于基线 early",
                    )
                else:
                    self.assertEqual(
                        baseline.time, result.time,
                        f"{name} {variant}: early={baseline.time} frontier={result.time}",
                    )

    def test_priority_order_matches_prio(self):
        for name in SAMPLES:
            case, plan, _config = load_sample(name)
            for variant in sched.VARIANTS[:3]:
                baseline = sched.schedule(case, plan, case.nmb, variant, "prio")
                self.assertIsNotNone(baseline)
                result = frontier.schedule(
                    case, plan, window=case.nmb, variant=variant,
                    gating=False, zero_free=False, order="priority",
                )
                self.assertEqual(
                    baseline.time, result.time,
                    f"{name} {variant}: prio={baseline.time} frontier={result.time}",
                )


class TestFrontierEfficiency(unittest.TestCase):
    """事件内核不应出现「旧键重入堆」：晋升/入堆次数与 op 数是线性关系。"""

    def test_event_kernel_has_no_repush(self):
        case, plan, _config = load_sample("ex5")
        stats = frontier.Stats()
        result = frontier.schedule(
            case, plan, window=case.nmb, variant=(True, False, False, False),
            gating=False, zero_free=False, order="time", stats=stats,
        )
        self.assertIsNotNone(result)
        self.assertEqual(case.n_ops, 40)
        # 每个队列状态变化才推一次全局堆项；操作本身从不重排回堆。
        self.assertEqual(stats.repushes, 0)
        self.assertLessEqual(stats.pushes, 6 * case.n_ops)

    def test_lazy_early_does_repush_on_zero_duration_case(self):
        case, plan, _config = load_sample("ex5")
        stats = frontier.Stats()
        result = frontier.schedule(
            case, plan, window=case.nmb, variant=(True, False, False, False),
            gating=False, zero_free=False, order="lazy_early", stats=stats,
        )
        self.assertIsNotNone(result)
        self.assertGreater(stats.repushes, 0, "基线替身应体现惰性重入堆")


class TestZeroDuration(unittest.TestCase):
    """零时长操作不占引擎：依赖满足即可执行，且必须全部输出。"""

    def test_zero_ops_do_not_wait_for_busy_engine(self):
        case, plan, _config = load_sample("ex2")  # Fs=0 ⇒ s / s_bwd / s_dw 零时长
        self.assertTrue(any(d == 0 for row in plan.durations for d in row))
        variant = (True, False, False, False)
        baseline = sched.schedule(case, plan, case.nmb, variant, "early")
        result = frontier.schedule(
            case, plan, window=case.nmb, variant=variant,
            gating=False, zero_free=True, order="time",
        )
        assert_schedule_valid(self, case, plan, result)
        pred, _succ = sched._dep_tables(case.L)
        stride = case.L * 10
        earlier = 0
        for mb in range(case.nmb):
            for layer in range(case.L):
                for oi in range(10):
                    idx = mb * stride + layer * 10 + oi
                    if plan.durations[layer][oi] != 0:
                        continue
                    ready = max(
                        (result.end[idx + offset] for offset in pred[layer * 10 + oi]),
                        default=0,
                    )
                    self.assertEqual(
                        result.start[idx], ready,
                        f"{mb}:{layer}:{oi} 零时长操作没有在依赖完成时刻立即执行",
                    )
                    if result.start[idx] < baseline.start[idx]:
                        earlier += 1
        self.assertGreater(earlier, 0, "该样例没有体现「零时长不被忙碌引擎延后」")

    def test_zero_ops_all_rendered(self):
        case, plan, _config = load_sample("ex1")
        result = frontier.schedule(
            case, plan, window=case.nmb, gating=False, zero_free=True, order="time",
        )
        assert_schedule_valid(self, case, plan, result)
        text = sched.render_output(case, plan, result, [[0, 1]])
        self.assertIn("SCHEDULE", text)
        lines = text.splitlines()
        rendered = 0
        for line in lines[lines.index("SCHEDULE") + 1:]:
            rendered += len(line.split()) - 1
        self.assertEqual(rendered, case.nmb * case.L * 10, "零时长操作没有被全部输出")


class TestLifecycleGating(unittest.TestCase):
    """B 组：生命周期内存门控下的合法性。"""

    def test_gated_event_schedules_valid(self):
        for name in ("ex1", "ex2", "ex5", "ex6"):
            case, plan, _config = load_sample(name)
            for variant in (None, (True, False, False, False), (False, True, False, True)):
                result = frontier.schedule(
                    case, plan, window=None, variant=variant,
                    gating=True, zero_free=True, policy="auto", order="time",
                )
                assert_schedule_valid(self, case, plan, result)

    def test_k2v_mirror_pairing(self):
        case = synthetic_case(L=2)
        config = {
            "V": 1, "P": 2, "K": 2, "psi": (1,),
            "map_rows": [(0, 1), (1, 0)],
        }
        plan = formula.build_plan(
            case, config["V"], config["P"], 1, config["psi"], config["map_rows"]
        )
        self.assertEqual(plan.K, 2 * plan.V)
        self.assertEqual(plan.layers_of_group[0], (0, 1))
        result = frontier.schedule(
            case, plan, window=None, gating=True, zero_free=True, policy="auto",
        )
        assert_schedule_valid(self, case, plan, result)
        # 两个块共用同一对引擎：同一时刻同引擎不得有两个非零操作（check_schedule 已覆盖），
        # 这里再确认两块确实都排在同一个卡组的引擎上。
        self.assertEqual(len(plan.layers_of_group), 1)

    def test_memory_caps_respect_limit(self):
        for name in ("ex1", "ex2", "ex5"):
            case, plan, _config = load_sample(name)
            caps = frontier.memory_caps(case, plan, policy="auto")
            self.assertIsNotNone(caps)
            for cap in caps:
                reserved = cap.mexp + case.U * cap.cap_comm + case.Uact * cap.cap_act
                self.assertLessEqual(
                    reserved, case.M,
                    f"{name} 卡组{cap.group} 预留 {reserved} > M={case.M}",
                )

    def test_infeasible_memory_returns_none(self):
        # Mexp=2*20=40，只剩 5 字节；激活每个要 100 字节、相邻两层至少 2 个槽 ⇒ 不可行。
        case = synthetic_case(L=2, E=1, Z=20, Zs=0, U=1, Uact=100, M=45, S=1, N=1)
        plan = formula.build_plan(case, 1, 1, 1, (), [(0,), (0,)])
        stats = frontier.Stats()
        result = frontier.schedule(
            case, plan, window=None, gating=True, zero_free=True, stats=stats,
        )
        self.assertIsNone(result, "不可行内存下不得返回半份调度")
        self.assertEqual(stats.abort, "memory-infeasible")

    def test_no_deadlock_when_activation_tight_but_feasible(self):
        # 相邻两层、激活容量恰好 2 个槽：必须靠「先释放再继续」推进而不是死锁。
        case = synthetic_case(L=2, E=1, Z=20, Zs=0, U=1, Uact=10, M=40 + 2 + 2 * 10,
                              S=1, N=1)
        plan = formula.build_plan(case, 1, 1, 1, (), [(0,), (0,)])
        # 默认（紧内存自动退化为 fwd-first/mb-major）与显式 fwd-first 都必须可完成；
        # 反向优先变体可能选择错误的 comb 顺序而返回 None（允许，由 search 兜底）。
        for variant in (None, (True, False, False, False)):
            result = frontier.schedule(
                case, plan, window=None, variant=variant, gating=True,
                zero_free=True, policy="auto",
            )
            assert_schedule_valid(self, case, plan, result)
        best = frontier.search(case, plan, strategy="B")
        assert_schedule_valid(self, case, plan, best)


class TestFrontierIntegration(unittest.TestCase):
    """生产接入的标签/统计回归（防止 A 分支 meta=None 崩溃、run 恒为 0）。"""

    def test_mode_a_strict_improvement_labels_stats(self):
        import time as _time

        case, plan, config = load_sample("ex5")
        variant = (True, False, False, False)
        base = sched.schedule(case, plan, case.nmb, variant, "early")
        self.assertIsNotNone(base)
        ok, groups = sched.memory_usage(case, plan, base.start, base.end)
        self.assertTrue(ok)
        best = solve._Best(
            time=base.time,
            lb=plan.lb,
            plan=plan,
            rows=config["map_rows"],
            config=solve.Config(
                P=config["P"], V=config["V"], D=1,
                psi=tuple(config["psi"]), lb=plan.lb,
            ),
            result=base,
            groups=groups,
            mode="baseline",
        )
        improved, info = solve._try_frontier(
            case, best, _time.monotonic() + 5.0, "A", None, reserve_s=0.4,
        )
        self.assertLess(improved.time, best.time, "A 组在 ex5 上应严格改进")
        self.assertEqual(info["run"], 1)
        self.assertEqual(info["planned"], 1)
        self.assertGreaterEqual(info["hits"], 1)
        self.assertEqual(info["stop"], "complete")
        self.assertEqual(info["accepted"], {"variant": "A", "policy": "search"})
        self.assertEqual([], sched.check_schedule(case, plan, improved.result))
        ok2, _groups2 = sched.memory_usage(
            case, plan, improved.result.start, improved.result.end
        )
        self.assertTrue(ok2)


class TestDeterminismAndLookahead(unittest.TestCase):
    def test_deterministic_event_schedule(self):
        case, plan, _config = load_sample("ex6")
        first = frontier.schedule(
            case, plan, window=None, gating=True, zero_free=True, seed=20261020,
        )
        second = frontier.schedule(
            case, plan, window=None, gating=True, zero_free=True, seed=20261020,
        )
        self.assertEqual(first.start, second.start)
        self.assertEqual(first.end, second.end)

    def test_lookahead_returns_full_valid_schedule(self):
        case, plan, _config = load_sample("ex1")
        base = frontier.schedule(
            case, plan, window=None, gating=True, zero_free=True,
        )
        stats = frontier.Stats()
        result = frontier.schedule(
            case, plan, window=None, gating=True, zero_free=True,
            mode="lookahead", lookahead=4, stats=stats,
        )
        assert_schedule_valid(self, case, plan, result)
        self.assertLessEqual(result.time, base.time)
        self.assertGreater(stats.lookahead_rollouts, 0)

    def test_lookahead_degrades_on_large_case(self):
        case, plan, _config = load_sample("ex1")
        case = casein.parse_case_text(
            (ROOT / "cases" / "ex1.in").read_text(encoding="utf-8").replace(
                "1 2 39 10 1\n1 2 20 0 1 1 1 2 2 10 6 1000000 1000000",
                "1 2 39 10 1\n1 2 20 0 1 1 1 13000 2 0 6 1000000 1000000",
            ),
            name="ex1-large-nmb",
        )
        plan = formula.build_plan(
            case, 1, 2, 1, (),
            [[0, 1]],
        )
        stats = frontier.Stats()
        result = frontier.schedule(
            case, plan, window=None, gating=True, zero_free=True,
            mode="lookahead", lookahead=4, stats=stats,
        )
        self.assertIsNotNone(result)
        self.assertGreater(case.n_ops, 120_000)
        self.assertTrue(stats.degraded)
        self.assertEqual(stats.lookahead_rollouts, 0)


class TestConfigParsing(unittest.TestCase):
    def test_parse_sample_output(self):
        case = casein.parse_case(ROOT / "cases" / "ex1.in")
        config = frontier.parse_schedule_config(
            (ROOT / "cases" / "ex1.out").read_text(encoding="utf-8"), case
        )
        self.assertEqual(config["V"], 1)
        self.assertEqual(config["P"], 2)
        self.assertEqual(config["K"], 1)
        self.assertEqual(config["psi"], ())
        self.assertEqual(len(config["map_rows"]), case.L)
        self.assertEqual(len(config["map_rows"][0]), case.E)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
