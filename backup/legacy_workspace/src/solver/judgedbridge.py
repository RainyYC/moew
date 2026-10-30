"""与判题核心的唯一交互通道：``python3 -m judge eval <case.in> <out> --json`` 子进程。

CONTRACT §9 的纪律：``solver/`` 可以调 ``python3 -m judge eval``（子进程），但**不得 import
`judge/core`、不得读它的内部状态**。本模块因此只用 ``subprocess`` + 解析 stdout 的 JSON，
并且**只把 judge 的判定当作对错依据**：求解器自己算的 Time 只用于搜索排序。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

__all__ = ["JudgeError", "judge_eval", "judge_command"]

#: 仓库根目录（`solver/` 的上一级）：子进程的 cwd，保证 ``python3 -m judge`` 找得到包。
ROOT = Path(__file__).resolve().parents[2]  # src/solver/judgedbridge.py → 仓库根


class JudgeError(RuntimeError):
    """判题核心的 CLI 不可用，或输出无法解析成 §3.1 的响应体。"""


def judge_command(case_in: str | Path, out_file: str | Path) -> list[str]:
    """构造 judge CLI 调用（CONTRACT §4）。"""
    return [sys.executable, "-m", "judge", "eval", str(case_in), str(out_file), "--json"]


def _extract_json(text: str) -> Optional[dict]:
    """从 stdout 里尽力取出响应体 JSON（容忍人类可读摘要混在前后）。"""
    stripped = text.strip()
    if not stripped:
        return None
    try:
        value = json.loads(stripped)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    for line in reversed(stripped.splitlines()):
        candidate = line.strip()
        if candidate.startswith("{") and candidate.endswith("}"):
            try:
                value = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first >= 0 and last > first:
        try:
            value = json.loads(stripped[first : last + 1])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            return None
    return None


def judge_eval(case_in: str | Path, out_file: str | Path, timeout: float = 300.0) -> dict:
    """调用 ``python3 -m judge eval`` 并返回 ``{ok, time, lb, groups, engines, grid, K, psi, errors}``。

    附加两个字段：``_exit``（子进程退出码，0=合法 / 1=映射非法 / 2=解析错误）与
    ``_stderr``（便于定位：CLI 缺失时会明确报 ``No module named judge.__main__``）。
    """
    command = judge_command(case_in, out_file)
    try:
        proc = subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - 单例 10s 预算内不会发生
        raise JudgeError(f"judge eval 超时（{timeout}s）：{' '.join(command)}") from exc
    payload = _extract_json(proc.stdout)
    if payload is None:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        tail = " | ".join(detail[-4:]) if detail else "（无输出）"
        raise JudgeError(
            "judge CLI 不可用或输出无法解析成 JSON："
            f"{' '.join(command)}\n退出码={proc.returncode} 输出={tail}"
        )
    payload["_exit"] = proc.returncode
    payload["_stderr"] = proc.stderr.strip()
    return payload
