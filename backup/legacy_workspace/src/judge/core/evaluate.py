"""CONTRACT §1 的判题核心入口（纯函数）。

```python
def parse_case(path: str) -> Case: ...
def evaluate(case: Case, output_text: str) -> dict: ...
```

``evaluate`` 的返回即 CONTRACT §1 / §3.1 的响应体：

* **纯函数**：同输入同输出，不写文件、不读时钟、不联网；
* 非法解**不抛异常**，返回 ``ok: false`` + ``errors[]``（每条带 ``t``、``at`` 与
  ``category``）；
* 解析失败抛 :class:`judge.core.parse.ParseError`（服务层转 422）；
* ``ops`` 不进这个响应（体积不可控），只通过 §3.5 的切片接口取；服务层需要落盘时
  用 :func:`evaluate_detailed` 拿到同一份 ops。
"""

from __future__ import annotations

from .parse import Case, Op, Output, ParseError, SchedRow, parse_case, parse_case_text, parse_output
from .sim import evaluate_output

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


def evaluate(case: Case, output_text: str) -> dict:
    """评估一份输出（CONTRACT §1 的响应体，不含 ``ops``）。"""
    result, _ops = evaluate_output(case, parse_output(output_text), with_ops=False)
    return result


def evaluate_detailed(case: Case, output_text: str) -> tuple[dict, list[dict]]:
    """同 :func:`evaluate`，但额外返回扁平 ``ops``（服务层写 ``runs/ops/*.jsonl``）。

    ``ops`` 每项为 ``{"t", "mb", "l", "op", "dur", "g"}``，按声明顺序（``t`` 非降）。
    调度本身非法时返回已解析出的那部分（时刻与时长仍然是题面公式算的），便于前端
    定位；调度无法模拟时（字段类错误）返回空列表。
    """
    return evaluate_output(case, parse_output(output_text))
