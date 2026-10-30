"""``python3 -m judge.core.acceptance``：7 个验收值（CONTRACT §7）的精确复现。

跑法（仓库根目录）::

    python3 -m judge.core.acceptance

逐例打印 ``expected`` / ``actual``，全部相等且 ``ok:true`` 时退出码 0，否则 1。
``cases/expected.json`` 是期望值的唯一出处（题面 §3.2、§7.1–§7.6）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .evaluate import evaluate, parse_case

__all__ = ["CASES", "cases_dir", "expected_path", "load_expected", "run", "main"]

#: 验收顺序（与 CONTRACT §7 表格一致）。
CASES: tuple[str, ...] = ("ex1", "ex2", "ex3", "ex4", "ex5", "ex6", "mini")


def cases_dir() -> Path:
    """``<repo>/cases``（按本文件位置推，不依赖 cwd）。"""
    # src/judge/core/acceptance.py → parents[3] 才是仓库根（cases/ 在根下）
    return Path(__file__).resolve().parents[3] / "cases"


def expected_path() -> Path:
    return cases_dir() / "expected.json"


def load_expected() -> dict[str, dict]:
    """读取 ``cases/expected.json``。"""
    with expected_path().open(encoding="utf-8") as handle:
        return json.load(handle)


def _passed(item: dict) -> bool:
    """单例是否通过：合法 + Time 相等 + （若声明了）lb 相等。"""
    return bool(
        item["ok"]
        and item["actual"] == item["expected"]
        and (item["expected_lb"] is None or item["lb"] == item["expected_lb"])
    )


def run(verbose: bool = True) -> tuple[bool, list[dict]]:
    """跑全部验收用例。

    返回 ``(全部通过?, 每例结果)``；每例结果形如
    ``{"case","expected","actual","ok","lb","expected_lb","errors"}``。
    """
    expected = load_expected()
    directory = cases_dir()
    results: list[dict] = []
    all_ok = True
    for name in CASES:
        entry = expected.get(name)
        if entry is None:
            results.append(
                {
                    "case": name,
                    "expected": None,
                    "actual": None,
                    "ok": False,
                    "lb": None,
                    "expected_lb": None,
                    "errors": [f"cases/expected.json 缺少 {name}"],
                }
            )
            all_ok = False
            continue
        case = parse_case(directory / f"{name}.in")
        output_text = (directory / f"{name}.out").read_text(encoding="utf-8")
        result = evaluate(case, output_text)
        expected_time = entry["time"]
        actual_time = result["time"]
        expected_lb = entry.get("lb")
        same = result["ok"] and actual_time == expected_time
        if expected_lb is not None:
            same = same and result["lb"] == expected_lb
        all_ok = all_ok and same
        results.append(
            {
                "case": name,
                "expected": expected_time,
                "actual": actual_time,
                "ok": result["ok"],
                "lb": result["lb"],
                "expected_lb": expected_lb,
                "errors": result["errors"],
            }
        )
    if verbose:
        for item in results:
            mark = "PASS" if _passed(item) else "FAIL"
            lb_text = "" if item["expected_lb"] is None else f" lb={item['lb']}(期望 {item['expected_lb']})"
            print(
                f"{mark} {item['case']:<5s} expected={item['expected']} actual={item['actual']}"
                f" ok={item['ok']}{lb_text}"
            )
            for error in item["errors"][:3]:
                print(f"       - [{error['category']}] t={error['t']} at={error['at']} {error['message']}")
        total = len(results)
        passed = sum(1 for item in results if _passed(item))
        tail = "" if passed == total else " —— 有失败"
        print(f"\n验收：{passed}/{total} 例通过{tail}")
    return all_ok, results


def main() -> int:
    ok, _results = run(verbose=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
