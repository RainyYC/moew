"""核心 API 的形状与语义细节（CONTRACT §1 / §2.5）。

这里锁定：

* ``evaluate`` 返回的键集合与 CONTRACT §1 完全一致（不含 ``ops``）；
* ``groups`` / ``engines`` 的字段与 ex1 的数值（CONTRACT §1 的响应示例）；
* ``evaluate_detailed`` 的 ops 形状（服务层 §2.5 切片接口用）；
* ``parse_case`` / ``parse_output`` 的解析细节与 ``ParseError``；
* 题面公式的几个关键点：``m_l`` 看最慢 rank、``pin/pout`` 按物理卡复核、
  内存闭区间峰值、``K=2V`` 镜像配对。
"""

from __future__ import annotations

import json
import unittest

from judge.core import Case, ParseError, evaluate, evaluate_detailed, parse_case, parse_case_text, parse_output
from judge.core.acceptance import cases_dir
from judge.core.memory import closed_peak, streamed_peaks
from judge.core.model import comm_payload, comm_time, layer_durations, layer_m, peer_counts
from judge.tests.test_negative import SYNTHETIC_2V_IN, SYNTHETIC_2V_OUT

RESULT_KEYS = {"ok", "time", "lb", "groups", "engines", "grid", "K", "psi", "errors"}


def _read(name: str) -> tuple[Case, str]:
    directory = cases_dir()
    return parse_case(directory / f"{name}.in"), (directory / f"{name}.out").read_text(encoding="utf-8")


class ResultShape(unittest.TestCase):
    def test_ex1_matches_contract_example(self) -> None:
        case, text = _read("ex1")
        result = evaluate(case, text)
        self.assertEqual(set(result), RESULT_KEYS)
        self.assertTrue(result["ok"])
        self.assertEqual(result["time"], 592)
        self.assertEqual(result["lb"], 560)  # CONTRACT §1 示例
        self.assertEqual(result["grid"], {"V": 1, "P": 2, "D": 1})
        self.assertEqual(result["K"], 1)
        self.assertEqual(result["psi"], [])
        # CONTRACT §1 示例：engines 的四个量完全一致
        self.assertEqual(
            result["engines"],
            [{"v": 0, "comp": 240, "comm": 560, "comm_first": 16, "comm_last": 576}],
        )
        group = result["groups"][0]
        self.assertEqual(set(group), {"v", "mexp", "movl", "mact", "limit"})
        self.assertEqual((group["mexp"], group["mact"], group["limit"]), (20, 1, 39))
        # 闭区间通信峰值：8 次 AllToAll 首尾相接（ex1），故 Movl = 2·U（题面 §4.6）
        self.assertEqual(group["movl"], 2)

    def test_illegal_result_shape(self) -> None:
        case, text = _read("ex1")
        broken = text.replace("156 0:0:comb 1:0:gemm", "156 1:0:gemm")
        result = evaluate(case, broken)
        self.assertEqual(set(result), RESULT_KEYS)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["time"])

    def test_ops_payload(self) -> None:
        case, text = _read("ex1")
        result, ops = evaluate_detailed(case, text)
        self.assertEqual(len(ops), case.ops_per_case)
        self.assertEqual(len(ops), 20)
        for op in ops:
            self.assertEqual(set(op), {"t", "mb", "l", "op", "dur", "g"})
            self.assertIsInstance(op["t"], int)
            self.assertIsInstance(op["dur"], int)
            self.assertIn(op["op"], {"s", "disp", "gemm", "comb", "s_bwd", "comb_bwd", "gemm_dx", "gemm_dw", "disp_bwd", "s_dw"})
        times = [op["t"] for op in ops]
        self.assertEqual(times, sorted(times), "ops 必须按声明顺序（t 非降）")
        self.assertEqual(len({(op["mb"], op["l"], op["op"]) for op in ops}), 20)
        self.assertEqual(result["time"], 592)

    def test_json_serialisable_and_deterministic(self) -> None:
        case, text = _read("ex5")
        first = evaluate(case, text)
        second = evaluate(case, text)
        self.assertEqual(first, second)
        self.assertEqual(json.loads(json.dumps(first)), first)

    def test_all_numbers_are_integers(self) -> None:
        def walk(value: object, path: str = "") -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    walk(item, f"{path}.{key}")
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    walk(item, f"{path}[{index}]")
            elif isinstance(value, bool) or value is None or isinstance(value, str):
                return
            else:
                self.assertIsInstance(value, int, f"{path} 必须是整数，得到 {type(value).__name__}")

        for name in ("ex1", "ex2", "ex3", "ex4", "ex5", "ex6", "mini"):
            with self.subTest(case=name):
                case, text = _read(name)
                walk(evaluate(case, text))


class Formulas(unittest.TestCase):
    def test_m_looks_at_slowest_rank(self) -> None:
        directory = cases_dir()
        case = parse_case(directory / "ex2.in")
        layer0 = (0, 1, 0, 1)
        layer1 = (0, 1, 1, 0)
        self.assertEqual(layer_m(case, 0, 2, layer0), 4)  # 均衡层 8/2
        self.assertEqual(layer_m(case, 1, 2, layer1), 6)  # 偏斜层：{6,0} 与 {1,1}
        # gemm = m·Fin = 6·4 = 24，与题面 §7.2 一致
        self.assertEqual(layer_durations(case, 1, layer_m(case, 1, 2, layer1), 0)[2], 24)

    def test_map_placement_changes_gemm(self) -> None:
        directory = cases_dir()
        case = parse_case(directory / "ex4.in")  # 负载 (3,3,2,2)
        self.assertEqual(layer_m(case, 0, 2, (0, 1, 0, 1)), 5)  # 热点分散 => gemm 20
        self.assertEqual(layer_m(case, 0, 2, (0, 0, 1, 1)), 6)  # 热点同 rank => gemm 24

    def test_peer_counts_from_physical_cards(self) -> None:
        directory = cases_dir()
        ex1 = parse_case(directory / "ex1.in")  # N=1,S=2
        self.assertEqual(peer_counts(ex1, V=1, P=2, D=1), (1, 0))  # P|S：节点内
        ex3 = parse_case(directory / "ex3.in")  # N=2,S=2
        self.assertEqual(peer_counts(ex3, V=1, P=2, D=2), (1, 0))
        self.assertEqual(peer_counts(ex3, V=1, P=4, D=1), (1, 2))  # S|P：跨节点
        ex5 = parse_case(directory / "ex5.in")
        self.assertEqual(peer_counts(ex5, V=2, P=1, D=1), (0, 0))  # P=1：无对端

    def test_comm_payload_and_time(self) -> None:
        directory = cases_dir()
        ex1 = parse_case(directory / "ex1.in")  # T=8,H=16,P=2
        self.assertEqual(ex1.H, 16)
        self.assertEqual(comm_payload(ex1, 0, 2), 64)  # ⌈8·16·1/2⌉
        self.assertEqual(comm_time(ex1, 64, 1, 0), 70)  # ⌈64/10⌉·10
        ex3 = parse_case(directory / "ex3.in")
        # §4.4（2026-10 修订）：X 是**每个对端**的字节数 ⌈T·H/P⌉，不是发给所有对端的总量。
        # 旧版题面把它写成 ⌈T·H·(P-1)/P⌉，再乘 pin/pout 会重复计费；P=2 时两式相同，
        # 所以六个样例掩盖了这个差别。P=4 时：X=24，x=max(⌈24/10⌉,⌈2·24/1⌉)·100=4800。
        self.assertEqual(comm_payload(ex3, 0, 4), 24)  # ⌈12·8/4⌉
        self.assertEqual(comm_time(ex3, 24, 1, 2), 4800)  # max(⌈24/10⌉,⌈48/1⌉)·100
        ex5 = parse_case(directory / "ex5.in")
        self.assertEqual(comm_payload(ex5, 0, 1), 0)  # P=1：没有对端，X 约定为 0
        self.assertEqual(comm_time(ex5, 0, 0, 0), 0)

    def test_backward_durations_use_single_ceiling(self) -> None:
        directory = cases_dir()
        ex5 = parse_case(directory / "ex5.in")  # α=1, β=0.5
        durations = layer_durations(ex5, 0, m=8, x=0)
        # s=16 gemm=48 s_bwd=16 comb_bwd=0 gemm_dx=48 gemm_dw=24 disp_bwd=0 s_dw=8
        self.assertEqual(durations, (16, 0, 48, 0, 16, 0, 48, 24, 0, 8))

    def test_lower_bound_formula(self) -> None:
        case, text = _read("ex5")
        result = evaluate(case, text)
        # 每个卡组一层：计算 16+48+16+48+24+8=160，通信 0，nmb=2 => 320
        self.assertEqual(result["lb"], 320)


class MemoryModel(unittest.TestCase):
    def test_closed_interval_peak(self) -> None:
        # 首尾相接算两块（题面 §4.6）
        self.assertEqual(closed_peak([(0, 10, "a"), (10, 20, "b")])[0], 2)
        # 留出一个时间单位就只算一块
        self.assertEqual(closed_peak([(0, 9, "a"), (10, 20, "b")])[0], 1)
        # 零时长通信在它那一个时刻也算占用
        self.assertEqual(closed_peak([(5, 5, "a")])[0], 1)
        self.assertEqual(closed_peak([]), (0, None, None))

    def test_activation_interval_is_closed(self) -> None:
        # 前向恰好在反向开始时结束，该时刻仍持有激活
        self.assertEqual(closed_peak([(0, 5, "a"), (5, 5, "b")])[0], 2)

    def test_streamed_peaks_matches_closed_peak(self) -> None:
        per_group = {
            0: [(0, 10), (10, 20), (20, 30), (25, 25), (40, 40)],
            1: [(5, 5), (5, 6), (7, 9)],
            2: [],
            3: [(0, 0), (0, 0), (3, 4)],
        }
        stream = sorted(
            ((group, start, end, (group, start, end)) for group, items in per_group.items() for start, end in items),
            key=lambda item: item[1],
        )
        fast = streamed_peaks(stream, 4)
        for group, items in per_group.items():
            slow = closed_peak([(start, end, (group, start, end)) for start, end in items])
            self.assertEqual(fast[group][0], slow[0], f"卡组 {group} 的峰值不一致")
            self.assertEqual(fast[group][1], slow[1])


class Parsing(unittest.TestCase):
    def test_output_parse_errors(self) -> None:
        cases = {
            "缺 MAP": "1 2\nPSI\n1\n",
            "缺 SCHEDULE": "1 2\nPSI\n1\nMAP\n0 1\n",
            "条目非三段": "1 2\nPSI\n1\nMAP\n0 1\nSCHEDULE\n0 0:0\n",
            "条目非整数": "1 2\nPSI\n1\nMAP\n0 1\nSCHEDULE\n0 x:0:s\n",
            "网格非整数": "one 2 1\nPSI\n1\n",
            "空输出": "",
        }
        for what, text in cases.items():
            with self.subTest(what=what):
                with self.assertRaises(ParseError):
                    parse_output(text)

    def test_input_parse_errors(self) -> None:
        with self.assertRaises(ParseError):
            parse_case_text("1 2 39 10 1\n1 2 20 0 1 1 1 2 2 10 6 1000000 1000000\n8 2\n")
        with self.assertRaises(ParseError):
            # 负载向量之和 ≠ T
            parse_case_text("1 2 39 10 1\n1 2 20 0 1 1 1 2 2 10 6 1000000 1000000\n8 2\n8 3 3\n")
        with self.assertRaises(ParseError):
            parse_case("/nonexistent/case.in")

    def test_input_load_vector_can_spill_to_next_line(self) -> None:
        text = "1 4 79 10 1\n2 4 20 0 1 1 1 2 0 100 4 1000000 1000000\n8 1\n8 6 1 1 0 8\n"
        case = parse_case_text(text, name="spill")
        self.assertEqual(case.T, (8, 8))
        self.assertEqual(case.loads, ((6, 1, 1, 0), None))

    def test_layer_without_vector_splits_evenly(self) -> None:
        case = parse_case_text("1 4 79 10 1\n1 4 20 0 1 1 1 2 0 100 4 1000000 1000000\n8 1\n10\n")
        from judge.core.model import layer_slots

        self.assertEqual(layer_slots(case, 0), (3, 3, 2, 2))


class MirroredBlocks(unittest.TestCase):
    """``K = 2V``：一个卡组持有两块，两块的层共用一个卡组（题面 §3.1/§4.2）。"""

    def test_k_2v_positive(self) -> None:
        case = parse_case_text(SYNTHETIC_2V_IN, name="syn2v")
        result = evaluate(case, SYNTHETIC_2V_OUT)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["K"], 4)
        self.assertEqual(result["psi"], [1, 2, 3])
        self.assertEqual(len(result["groups"]), 2)
        # 镜像配对：卡组 0 持块 0 与块 3（层 0、3），卡组 1 持块 1 与块 2（层 1、2）
        for engine in result["engines"]:
            self.assertEqual(engine["comp"], 2 * 2 * (2 + 2))  # nmb × 2 层 × (s+gemm)
        # 手算：最后一个前向 comb 在 t=32，全部零时长反向条目挂在 t=34
        self.assertEqual(result["time"], 34)
        self.assertEqual(result["lb"], 2 * 8)  # nmb × 每卡组计算量 8


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
