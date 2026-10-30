"""负例：九类非法映射都必须被拦住，且报错可定位（``t`` + ``mb:ℓ:op`` + 分类）。

覆盖顺序与 CONTRACT §1 / 题面 §4.7 一致：

===========  ==========================================
缺操作        ``missing``
重复操作      ``duplicate``
依赖提前      ``dependency``
引擎冲突      ``engine``
内存超限      ``memory``
K 非法        ``field``（PSI）
切点非严格递增 ``field``（PSI）
MAP 计数不等  ``field``（MAP）
V·P·D≠R       ``field``（网格）
===========  ==========================================
"""

from __future__ import annotations

import re
import unittest

from judge.core import Case, evaluate, parse_case, parse_case_text
from judge.core.acceptance import cases_dir

CATEGORIES = {"missing", "duplicate", "dependency", "engine", "memory", "field"}
SCHEDULE_AT = re.compile(r"^\d+:\d+:[a-z_]+$")


def _load(name: str) -> tuple[Case, str]:
    directory = cases_dir()
    return parse_case(directory / f"{name}.in"), (directory / f"{name}.out").read_text(encoding="utf-8")


def _replace(text: str, old: str, new: str) -> str:
    assert old in text, f"夹具里找不到 {old!r}"
    return text.replace(old, new, 1)


class NegativeCases(unittest.TestCase):
    def assert_errors(self, result: dict, category: str) -> list[dict]:
        self.assertFalse(result["ok"], "非法解必须 ok=false")
        self.assertIsNone(result["time"], "非法解必须 time=null（服务端 score 亦为 null）")
        self.assertTrue(result["errors"], "非法解必须带 errors[]")
        for error in result["errors"]:
            self.assertIn("category", error)
            self.assertIn(error["category"], CATEGORIES)
            self.assertIn("t", error)
            self.assertIn("at", error)
            self.assertIn("message", error)
        matched = [error for error in result["errors"] if error["category"] == category]
        self.assertTrue(matched, f"期望 {category} 类错误，实得 {[e['category'] for e in result['errors']]}")
        return matched

    # -- 调度相关：必须给出 t 与 mb:ℓ:op --------------------------------- #

    def test_missing_op(self) -> None:
        case, text = _load("ex1")
        broken = _replace(text, "156 0:0:comb 1:0:gemm", "156 1:0:gemm")
        result = evaluate(case, broken)
        matched = self.assert_errors(result, "missing")
        self.assertIn("0:0:comb", [error["at"] for error in matched])

    def test_duplicate_op(self) -> None:
        case, text = _load("ex1")
        broken = _replace(text, "156 0:0:comb 1:0:gemm", "156 0:0:comb 0:0:comb 1:0:gemm")
        matched = self.assert_errors(evaluate(case, broken), "duplicate")
        self.assertEqual(matched[0]["at"], "0:0:comb")
        self.assertIsInstance(matched[0]["t"], int)
        self.assertIn("first_t", matched[0])

    def test_dependency_early(self) -> None:
        case, text = _load("ex1")
        # 0:0:s_bwd 原在 226（= comb 结束），提前到 220 就违反了「反向等本层前向完成」
        broken = _replace(text, "226 0:0:s_bwd 1:0:comb", "220 0:0:s_bwd 1:0:comb")
        matched = self.assert_errors(evaluate(case, broken), "dependency")
        self.assertEqual(matched[0]["at"], "0:0:s_bwd")
        self.assertEqual(matched[0]["t"], 220)
        self.assertEqual(matched[0]["depends_on"], "0:0:comb")
        self.assertEqual(matched[0]["dep_end"], 226)

    def test_engine_conflict(self) -> None:
        case, text = _load("ex1")
        # 两个 microbatch 的 s 落在同一卡组同一计算引擎的同一时刻（s 时长 16，非 0）
        broken = _replace(text, "0 0:0:s\n", "0 0:0:s 1:0:s\n")
        broken = _replace(broken, "16 0:0:disp 1:0:s", "16 0:0:disp")
        matched = self.assert_errors(evaluate(case, broken), "engine")
        self.assertEqual(matched[0]["at"], "1:0:s")
        self.assertEqual(matched[0]["t"], 0)
        self.assertEqual(matched[0]["conflicts_with"], "0:0:s")
        self.assertEqual(matched[0]["engine"], "计算")

    def test_memory_exceeded(self) -> None:
        directory = cases_dir()
        text_in = (directory / "ex1.in").read_text(encoding="utf-8")
        # M=21 < Mexp(20)+Movl(2)+Mact(1)=23
        case = parse_case_text(_replace(text_in, "1 2 39 10 1", "1 2 21 10 1"), name="ex1-tight")
        output_text = (directory / "ex1.out").read_text(encoding="utf-8")
        matched = self.assert_errors(evaluate(case, output_text), "memory")
        error = matched[0]
        self.assertEqual(error["group"], 0)
        self.assertIsInstance(error["t"], int)
        self.assertRegex(error["at"] or "", SCHEDULE_AT)
        self.assertGreater(error["mexp"] + error["movl"] + error["mact"], error["limit"])

    def test_dependency_listed_before_its_predecessor(self) -> None:
        """comb 写在 gemm 之前（跨行）：因果性分支「依赖尚未登记」。"""
        case, text = _load("ex1")
        broken = _replace(text, "86 0:0:gemm 1:0:disp", "86 0:0:comb 1:0:disp")
        broken = _replace(broken, "156 0:0:comb 1:0:gemm", "156 0:0:gemm 1:0:gemm")
        matched = self.assert_errors(evaluate(case, broken), "dependency")
        self.assertIn("0:0:comb", [error["at"] for error in matched])
        self.assertIn("0:0:gemm", [error.get("depends_on") for error in matched])

    def test_mirrored_blocks_share_one_engine_pair(self) -> None:
        """K=2V：块 0 与块 3 同属卡组 0，两块的同一个计算引擎不能重叠（题面 §4.2 第 3 条）。"""
        case = parse_case_text(SYNTHETIC_2V_IN, name="syn2v")
        broken = _replace(SYNTHETIC_2V_OUT, "14 0:3:disp 0:3:gemm", "14 0:3:disp")
        broken = _replace(broken, "2 0:0:disp 0:0:gemm", "2 0:0:disp 0:0:gemm 0:3:gemm")
        matched = self.assert_errors(evaluate(case, broken), "engine")
        self.assertEqual(matched[0]["at"], "0:3:gemm")
        self.assertEqual(matched[0]["group"], 0)
        self.assertEqual(matched[0]["conflicts_with"], "0:0:gemm")

    # -- 字段类：没有 t / mb:ℓ:op，但必须标明 section -------------------- #

    def test_grid_vp_d_neq_r(self) -> None:
        case, text = _load("ex1")
        broken = _replace(text, "1 2\nPSI", "3 2\nPSI")
        matched = self.assert_errors(evaluate(case, broken), "field")
        self.assertEqual(matched[0]["section"], "grid")
        self.assertIn("V·P·D", matched[0]["message"])

    def test_k_illegal(self) -> None:
        case, text = _load("ex6")
        broken = _replace(text, "2 2\nPSI\n2 1", "2 2\nPSI\n3 1")
        matched = self.assert_errors(evaluate(case, broken), "field")
        self.assertEqual(matched[0]["section"], "psi")
        self.assertIn("K=3", matched[0]["message"])

    def test_cutpoints_not_increasing(self) -> None:
        # 需要 K ≥ 3：用合成用例（V=2、K=2V=4、L=4），切点写成 2 1 3
        case = parse_case_text(SYNTHETIC_2V_IN, name="syn2v")
        broken = _replace(SYNTHETIC_2V_OUT, "4 1 2 3", "4 2 1 3")
        matched = self.assert_errors(evaluate(case, broken), "field")
        self.assertEqual(matched[0]["section"], "psi")
        self.assertIn("非严格递增", matched[0]["message"])

    def test_map_count_mismatch(self) -> None:
        case, text = _load("ex4")
        broken = _replace(text, "MAP\n0 1 0 1\n", "MAP\n0 0 0 1\n")
        matched = self.assert_errors(evaluate(case, broken), "field")
        self.assertEqual(matched[0]["section"], "map")
        self.assertIn("E/P", matched[0]["message"])

    def test_map_rank_out_of_range(self) -> None:
        case, text = _load("ex4")
        broken = _replace(text, "MAP\n0 1 0 1\n", "MAP\n0 1 0 2\n")
        matched = self.assert_errors(evaluate(case, broken), "field")
        self.assertEqual(matched[0]["section"], "map")


# --------------------------------------------------------------------------- #
# 合成用例：V=2、K=2V=4（镜像配对），反向系数为 0，便于手算
# --------------------------------------------------------------------------- #

SYNTHETIC_2V_IN = """\
1 2 100 10 1
4 2 10 0 1 1 1 2 1 1 1 0 0
1 1
2
2
2
2
"""

_BACKWARD_ROW = " ".join(
    f"{mb}:{layer}:{op}"
    for mb in range(2)
    for layer in range(4)
    for op in ("s_bwd", "comb_bwd", "gemm_dx", "gemm_dw", "disp_bwd", "s_dw")
)

_FORWARD_ROWS: list[str] = []
_clock = 0
for _mb in range(2):
    for _layer in range(4):
        _FORWARD_ROWS.append(f"{_clock} {_mb}:{_layer}:s")
        _FORWARD_ROWS.append(f"{_clock + 2} {_mb}:{_layer}:disp {_mb}:{_layer}:gemm")
        _clock += 2
        _FORWARD_ROWS.append(f"{_clock + 2} {_mb}:{_layer}:comb")
        _clock += 2

SYNTHETIC_2V_OUT = (
    "2 1\nPSI\n4 1 2 3\nMAP\n0 0\n0 0\n0 0\n0 0\nSCHEDULE\n"
    + "\n".join(_FORWARD_ROWS)
    + f"\n{_clock + 2} {_BACKWARD_ROW}\n"
)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
