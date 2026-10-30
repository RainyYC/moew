"""t7 修复回归：复核 F1（依赖/引擎检查与书写行序无关）与裁定 N1（零长度通信开关）。

背景（`docs/review-judge-core.md` F1 / N1，CONTRACT §11）：

* **F1**：旧实现逐行"登记本行 → 查本行依赖"，导致同一时刻 ``t`` 的操作若被写在两行、
  且依赖方在前一行，会被误判成因果性违规。题面 §3.2 只要求 ``t`` 非降，§4.2.4 只比较
  时刻——**换行方式不能改变判定**。本文件用拆行/倒序两类等价写法锁定这一点。
* **N1**：零长度通信（``P=1`` 时 ``x=0``）默认计入 ``Movl``（保守口径）；
  ``ZERO_LEN_COMM_COUNTS`` 置 ``False`` 时应改算另一种值，且默认路径逐字节不变。

复跑：``python3 -m unittest discover -s judge/tests -q``
"""

from __future__ import annotations

import hashlib
import json
import unittest
from unittest import mock

from judge.core import Case, evaluate, memory, parse_case
from judge.core.acceptance import cases_dir

#: 题面/契约给出的验收 Time（CONTRACT §7）。
EXPECTED_TIME: dict[str, int] = {
    "ex1": 560,
    "ex2": 4880,
    "ex3": 7000,
    "ex4": 3200,
    "ex5": 416,
    "ex6": 1696,
    "mini": 164,
}

#: 默认开关下 ``evaluate()`` 结果的 sha256（``json.dumps(..., sort_keys=True,
#: separators=(",", ":"))``）。用来锁住"两趟重构 + 开关都不改变默认路径的输出"。
GOLDEN_SHA256: dict[str, str] = {
    "ex1": "886afacc55aed2e6848fc646bff5f115fabee4b3435e0a71b9a548e40e80e8dd",
    "ex2": "8669cd92c91ba4daeddc9bd38ea3623394bce8f97c7cf9a7ac0c8e0db65ec03b",
    "ex3": "efeb94015fe9af5c5ba6b45f24d9cc4e2cc6c6322451972a9a93134e4b904e49",
    "ex4": "2a116608b2bb6ef7ef9bbd8288a73f7db474ec9905d1240c141406b811ef0f10",
    "ex5": "4c9ec4fcb24004a8f831e4e8ac0c274be9fb61af838182acc1c88bc992792761",
    "ex6": "9212e82c20fa29f55aacb44f2121ca12853fccddda30290e25d5d3a5c70381c3",
    "mini": "e2ae8ae3cd1fb2bac4d37e68e164d599e698405d9edb88e94b3b9409373030aa",
}


def _load(name: str) -> tuple[Case, str]:
    directory = cases_dir()
    return parse_case(directory / f"{name}.in"), (directory / f"{name}.out").read_text(encoding="utf-8")


def _fingerprint(result: dict) -> str:
    blob = json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _layout(text: str) -> tuple[list[str], list[str]]:
    """把输出拆成「SCHEDULE 之前」与「调度行」。"""
    head: list[str] = []
    rows: list[str] = []
    for line in text.splitlines():
        if rows or line.strip() == "SCHEDULE":
            if not rows and line.strip() == "SCHEDULE":
                head.append(line)
                continue
            rows.append(line)
        else:
            head.append(line)
    return head, rows


def _split_one_op_per_line(text: str) -> str:
    """每个操作单独一行（``(t, mb, ℓ, op)`` 多重集完全不变）。"""
    head: list[str] = []
    lines: list[str] = []
    in_schedule = False
    for line in text.splitlines():
        tokens = line.split()
        if not in_schedule:
            head.append(line)
            if tokens == ["SCHEDULE"]:
                in_schedule = True
            continue
        for token in tokens[1:]:
            lines.append(f"{tokens[0]} {token}")
    return "\n".join(head + lines) + "\n"


def _reverse_equal_t_groups(text: str) -> str:
    """把同一 ``t`` 的连续多行倒序（``t`` 仍非降，只是行序被打乱）。"""
    head: list[str] = []
    rows: list[str] = []
    in_schedule = False
    for line in text.splitlines():
        if not in_schedule:
            head.append(line)
            if line.split() == ["SCHEDULE"]:
                in_schedule = True
            continue
        rows.append(line)
    reordered: list[str] = []
    index = 0
    while index < len(rows):
        stamp = rows[index].split()[0]
        end = index
        while end < len(rows) and rows[end].split()[0] == stamp:
            end += 1
        reordered.extend(reversed(rows[index:end]))
        index = end
    return "\n".join(head + reordered) + "\n"


class RowOrderIndependence(unittest.TestCase):
    """F1：同一份映射的等价写法必须同判。"""

    def test_split_one_op_per_line_accepted(self) -> None:
        """split_ex1 / split_ex2 / split_ex5 / split_mini（复核报告点名的三个 + ex2）。"""
        for name in ("ex1", "ex2", "ex5", "mini"):
            with self.subTest(case=name):
                case, text = _load(name)
                split = _split_one_op_per_line(text)
                self.assertNotEqual(split, text, "夹具应真的被拆行")
                result = evaluate(case, split)
                self.assertTrue(result["ok"], f"split_{name} 应合法，errors={result['errors'][:3]}")
                self.assertEqual(result["time"], EXPECTED_TIME[name], f"split_{name} 的 Time 必须不变")
                self.assertEqual(result["errors"], [])

    def test_split_keeps_memory_groups_identical(self) -> None:
        case, text = _load("mini")
        original = evaluate(case, text)
        split = evaluate(case, _split_one_op_per_line(text))
        self.assertEqual(split["groups"], original["groups"])
        self.assertEqual(split["engines"], original["engines"])

    def test_reversed_equal_t_rows_accepted(self) -> None:
        """同一 t 的多行倒序（行内/行间顺序都打乱）仍然合法。"""
        for name in ("ex1", "ex2", "ex5", "mini"):
            with self.subTest(case=name):
                case, text = _load(name)
                shuffled = _reverse_equal_t_groups(_split_one_op_per_line(text))
                result = evaluate(case, shuffled)
                self.assertTrue(result["ok"], f"reversed_{name} 应合法，errors={result['errors'][:3]}")
                self.assertEqual(result["time"], EXPECTED_TIME[name])

    def test_real_dependency_violation_still_rejected(self) -> None:
        """防"修反"：真正把 comb 提前到 gemm 完成之前，仍必须报 dependency。"""
        case, text = _load("ex1")
        # 0:0:gemm 在 70 开始、时长 24（结束 94）；把 0:0:comb 提前到 80
        broken = text.replace("140 0:0:comb 1:0:gemm", "80 0:0:comb 1:0:gemm")
        result = evaluate(case, broken)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["time"])
        categories = {error["category"] for error in result["errors"]}
        self.assertIn("dependency", categories)
        target = [error for error in result["errors"] if error["at"] == "0:0:comb" and error["category"] == "dependency"]
        self.assertTrue(target, result["errors"][:5])
        self.assertEqual(target[0]["depends_on"], "0:0:gemm")
        self.assertEqual(target[0]["dep_end"], 94)

    def test_engine_conflict_across_rows_still_rejected(self) -> None:
        """两个同引擎的非零操作写在**同一 t 的两行**里，仍必须报 engine（F1 修复不能放过它）。"""
        case, text = _load("ex1")
        # 把 1:0:s 挪到 t=0 的**下一行**：两者都是时长 16 的计算操作，同一卡组同一引擎
        broken = text.replace("0 0:0:disp 0:0:s\n", "0 0:0:disp 0:0:s\n0 1:0:s\n")
        broken = broken.replace("16 1:0:s\n", "")
        result = evaluate(case, broken)
        self.assertFalse(result["ok"])
        engine_errors = [error for error in result["errors"] if error["category"] == "engine"]
        self.assertTrue(engine_errors, result["errors"][:5])
        self.assertEqual(engine_errors[0]["at"], "1:0:s")
        self.assertEqual(engine_errors[0]["conflicts_with"], "0:0:s")
        self.assertEqual(engine_errors[0]["t"], 0)


class ZeroLengthCommSwitch(unittest.TestCase):
    """N1：`ZERO_LEN_COMM_COUNTS` 默认保守计入，关掉只改 `Movl`。"""

    def test_default_results_byte_identical(self) -> None:
        self.assertTrue(memory.ZERO_LEN_COMM_COUNTS, "默认必须是保守口径（计入）")
        for name in EXPECTED_TIME:
            with self.subTest(case=name):
                case, text = _load(name)
                self.assertEqual(_fingerprint(evaluate(case, text)), GOLDEN_SHA256[name])

    def test_default_counts_zero_length_transfers(self) -> None:
        case, text = _load("ex5")  # P=1 ⇒ 所有通信时长为 0
        result = evaluate(case, text)
        self.assertEqual([group["movl"] for group in result["groups"]], [2, 2])
        self.assertEqual(result["time"], 416)

    def test_disabled_switch_changes_movl_only(self) -> None:
        case, text = _load("ex5")
        with mock.patch.object(memory, "ZERO_LEN_COMM_COUNTS", False):
            disabled = evaluate(case, text)
        enabled = evaluate(case, text)
        self.assertEqual([group["movl"] for group in enabled["groups"]], [2, 2])
        self.assertEqual([group["movl"] for group in disabled["groups"]], [0, 0])
        # 只影响 Movl：Mexp/Mact/Time/合法性都不变
        self.assertEqual([group["mexp"] for group in disabled["groups"]], [40, 40])
        self.assertEqual([group["mact"] for group in disabled["groups"]], [2, 1])
        self.assertEqual(disabled["time"], enabled["time"])
        self.assertTrue(disabled["ok"])

    def test_disabled_switch_on_mini(self) -> None:
        case, text = _load("mini")  # comb 在 180 结束、comb_bwd/disp_bwd 在 180 开始
        with mock.patch.object(memory, "ZERO_LEN_COMM_COUNTS", False):
            disabled = evaluate(case, text)
        self.assertEqual(disabled["groups"][0]["movl"], 1)
        self.assertEqual(disabled["time"], 164)
        self.assertTrue(disabled["ok"])

    def test_activation_zero_length_is_never_skipped(self) -> None:
        """激活区间 [comb 结束, s_bwd 开始] 的闭区间是题面 §4.6 要求的，不受开关影响。"""
        case, text = _load("mini")
        enabled = evaluate(case, text)
        with mock.patch.object(memory, "ZERO_LEN_COMM_COUNTS", False):
            disabled = evaluate(case, text)
        self.assertEqual(enabled["groups"][0]["mact"], 1)
        self.assertEqual(disabled["groups"][0]["mact"], 1)

    def test_closed_peak_zero_length_parameter(self) -> None:
        self.assertEqual(memory.closed_peak([(5, 5, "a")]), (1, 5, "a"))
        self.assertEqual(memory.closed_peak([(5, 5, "a")], count_zero_length=False), (0, None, None))
        # 非零区间不受影响
        self.assertEqual(memory.closed_peak([(0, 10, "a"), (10, 20, "b")], count_zero_length=False)[0], 2)

    def test_streamed_peaks_honours_switch(self) -> None:
        # 同一时刻（t=5）两个零长度传输 + 之后一段普通传输
        stream = [(0, 5, 5, "z1"), (0, 5, 5, "z2"), (0, 12, 20, "a")]
        self.assertEqual(memory.streamed_peaks(stream, 1)[0][0], 2)
        with mock.patch.object(memory, "ZERO_LEN_COMM_COUNTS", False):
            self.assertEqual(memory.streamed_peaks(stream, 1)[0][0], 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
