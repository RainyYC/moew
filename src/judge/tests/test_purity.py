"""纯函数 / 全整数 / 单向依赖（CONTRACT §1、§6、§9）。

三个硬要求，用 AST 静态检查 + 运行时打桩双重把关：

1. ``evaluate`` 不写文件、不读时钟、不联网（覆盖 CONTRACT §1 的纯函数要求）；
2. 时长 / 内存全整数：``judge/core`` 里没有真除法 ``/``、没有 float 字面量；
3. ``judge/`` 不 import ``solver/`` 与 ``ui/``（单向依赖，公式只有一份实现）。
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest import mock

from judge.core import evaluate, parse_case
from judge.core.acceptance import cases_dir

JUDGE_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = JUDGE_ROOT / "core"
CORE_MODULES = sorted(CORE_ROOT.glob("*.py")) + [JUDGE_ROOT / "__init__.py"]
#: 参与时长 / 内存计算的模块（`acceptance.py` 是 CLI 外壳，其中的 `/` 是 pathlib 拼接）。
MATH_MODULES = [CORE_ROOT / name for name in ("parse.py", "model.py", "memory.py", "sim.py", "evaluate.py", "__init__.py")]

#: 会破坏纯函数性质的 import（时钟、随机、网络、子进程、线程）。
FORBIDDEN_IMPORTS = {
    "time",
    "datetime",
    "random",
    "secrets",
    "socket",
    "subprocess",
    "urllib",
    "http",
    "ftplib",
    "shutil",
    "tempfile",
    "threading",
    "multiprocessing",
    "asyncio",
}
#: 写文件的调用名（读文件只能出现在 ``parse_case`` 里，由 parse.py 承担）。
FORBIDDEN_CALLS = {"write_text", "write_bytes", "mkdir", "unlink", "rmdir", "rename", "replace"}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


class IntegerOnly(unittest.TestCase):
    def test_no_true_division(self) -> None:
        for path in MATH_MODULES:
            for node in ast.walk(_tree(path)):
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                    self.fail(f"{path.name}:{node.lineno} 使用了真除法 /（会产生 float）")
                if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Div):
                    self.fail(f"{path.name}:{node.lineno} 使用了真除法 /=")

    def test_no_float_literals(self) -> None:
        for path in MATH_MODULES:
            for node in ast.walk(_tree(path)):
                if isinstance(node, ast.Constant) and isinstance(node.value, float):
                    self.fail(f"{path.name}:{node.lineno} 出现 float 字面量 {node.value!r}")

    def test_no_float_conversion(self) -> None:
        for path in MATH_MODULES:
            for node in ast.walk(_tree(path)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float":
                    self.fail(f"{path.name}:{node.lineno} 调用了 float()")


class PureFunctions(unittest.TestCase):
    def test_core_imports_nothing_time_or_network(self) -> None:
        for path in CORE_MODULES:
            imported = _imported_roots(_tree(path))
            offenders = imported & FORBIDDEN_IMPORTS
            self.assertFalse(offenders, f"{path.name} 引入了 {sorted(offenders)}")

    def test_no_file_writes_in_core(self) -> None:
        for path in CORE_MODULES:
            for node in ast.walk(_tree(path)):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                    self.assertNotIn(name, FORBIDDEN_CALLS, f"{path.name}:{node.lineno} 调用了 {name}()")

    def test_no_solver_or_ui_imports_anywhere_in_judge(self) -> None:
        for path in sorted(JUDGE_ROOT.rglob("*.py")):
            imported = _imported_roots(_tree(path))
            self.assertFalse(
                imported & {"solver", "ui"},
                f"{path.relative_to(JUDGE_ROOT)} 引入了 {sorted(imported & {'solver', 'ui'})}",
            )

    def test_evaluate_needs_no_file_io_and_no_clock(self) -> None:
        case = parse_case(cases_dir() / "ex1.in")
        output_text = (cases_dir() / "ex1.out").read_text(encoding="utf-8")

        def boom(*args: object, **kwargs: object) -> None:
            raise AssertionError("evaluate() 不允许访问文件或时钟")

        with (
            mock.patch("builtins.open", boom),
            mock.patch.object(Path, "open", boom),
            mock.patch.object(Path, "read_text", boom),
            mock.patch.object(Path, "write_text", boom),
            mock.patch("time.time", boom),
            mock.patch("time.monotonic", boom),
            mock.patch("time.perf_counter", boom),
        ):
            result = evaluate(case, output_text)
        self.assertTrue(result["ok"])
        self.assertEqual(result["time"], 560)

    def test_evaluate_same_input_same_output(self) -> None:
        case = parse_case(cases_dir() / "ex2.in")
        text = (cases_dir() / "ex2.out").read_text(encoding="utf-8")
        first = evaluate(case, text)
        for _ in range(3):
            self.assertEqual(evaluate(case, text), first)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
