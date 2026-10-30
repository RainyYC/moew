"""判题核心（CONTRACT §0 的「唯一权威」层）。

* 题面公式只有这一份实现；``judge.service`` / ``judge.cli`` / ``ui/`` 都必须调它，
  不许自己算 ``ceil``、``Mexp/Movl/Mact`` 或跑调度器；
* 全整数运算，无 ``float`` 参与时长 / 内存；
* 纯函数：``evaluate`` 不写文件、不读时钟、不联网。

模块分工
--------
======================  ====================================================
:mod:`parse`            输入 / 输出解析（``ParseError`` → 服务层 422）
:mod:`model`            题面 §4 的公式：时长、``m_l``、``X_l``、``x_l``、``lb``
:mod:`sim`              网格 / PSI / MAP 校验、调度守恒、§4.2 模拟、结果装配
:mod:`memory`           §4.6 的三块内存（Mexp / Movl / Mact，闭区间峰值）
:mod:`evaluate`         契约入口 ``parse_case`` / ``evaluate`` / ``evaluate_detailed``
:mod:`acceptance`       ``python3 -m judge.core.acceptance``：7 个验收值
======================  ====================================================
"""

from __future__ import annotations

from .evaluate import evaluate, evaluate_detailed
from .parse import Case, Op, Output, ParseError, SchedRow, parse_case, parse_case_text, parse_output

__all__ = [
    "Case",
    "Op",
    "Output",
    "ParseError",
    "SchedRow",
    "parse_case",
    "parse_case_text",
    "parse_output",
    "evaluate",
    "evaluate_detailed",
]
