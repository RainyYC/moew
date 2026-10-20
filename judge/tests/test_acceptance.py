"""验收：题面 §3.2 / §7 的 7 个 Time 值必须被精确复现（CONTRACT §7）。

期望值在**两处**独立出现：本文件的 ``EXPECTED`` 常量（来自题面原文）与
``cases/expected.json``（供 CLI / 服务读取）。两者必须一致，防止夹具漂移。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from judge.core import evaluate, parse_case
from judge.core.acceptance import CASES, cases_dir, load_expected

#: 题面原文给出的 Time（CONTRACT §7 表格）。
EXPECTED: dict[str, int] = {
    "ex1": 592,
    "ex2": 4880,
    "ex3": 4000,
    "ex4": 3200,
    "ex5": 416,
    "ex6": 1744,
    "mini": 180,
}

#: CONTRACT §1 的 ``lb`` 字段示例（ex1）与各例的引擎下界。
EXPECTED_LB: dict[str, int] = {
    "ex1": 560,
    "ex2": 3200,
    "ex3": 4000,
    "ex4": 3200,
    "ex5": 320,
    "ex6": 1120,
    "mini": 140,
}


class AcceptanceValues(unittest.TestCase):
    """7 个验收值 + 夹具齐备性。"""

    def test_seven_cases_exist_and_match_expected_json(self) -> None:
        directory = cases_dir()
        expected_json = load_expected()
        self.assertEqual(tuple(EXPECTED), CASES)
        for name in CASES:
            with self.subTest(case=name):
                self.assertTrue((directory / f"{name}.in").is_file(), f"缺少 cases/{name}.in")
                self.assertTrue((directory / f"{name}.out").is_file(), f"缺少 cases/{name}.out")
                self.assertIn(name, expected_json)
                self.assertEqual(expected_json[name]["time"], EXPECTED[name])
                self.assertEqual(expected_json[name]["lb"], EXPECTED_LB[name])

    def test_every_case_reproduces_time_and_lb(self) -> None:
        directory = cases_dir()
        for name in CASES:
            with self.subTest(case=name):
                case = parse_case(directory / f"{name}.in")
                output_text = (directory / f"{name}.out").read_text(encoding="utf-8")
                result = evaluate(case, output_text)
                self.assertTrue(result["ok"], f"{name} 应判合法，errors={result['errors']}")
                self.assertEqual(result["time"], EXPECTED[name])
                self.assertEqual(result["lb"], EXPECTED_LB[name])
                self.assertEqual(result["errors"], [])

    def test_expected_json_is_valid_json(self) -> None:
        path: Path = cases_dir() / "expected.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(data), set(CASES))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
