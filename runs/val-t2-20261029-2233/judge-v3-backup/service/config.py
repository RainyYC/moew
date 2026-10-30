"""服务层 / CLI 的运行期配置（路径、超时、监听地址）。

不写死仓库位置：``JUDGE_RUNS_DIR`` / ``JUDGE_CASES_DIR`` 可以覆盖，``selftest`` 用它在
临时目录里跑完整语义而不污染真账本。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "REPO_ROOT",
    "CASE_TIMEOUT_SECONDS",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "DEFAULT_URL",
    "LOOPBACK_HOSTS",
    "Config",
]

#: 仓库根目录（``judge/service/config.py`` 往上三层）。
REPO_ROOT = Path(__file__).resolve().parents[2]

#: 单用例求解墙钟上限（题面 §5.4 / CONTRACT §2.2）。
CASE_TIMEOUT_SECONDS = 10.0

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3081
DEFAULT_URL = "http://127.0.0.1:3081"

#: 只允许绑回环（CONTRACT §2.0：不绑 0.0.0.0，避免绕过端口映射的第二条路）。
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


@dataclass(frozen=True)
class Config:
    """一次服务进程的配置。"""

    root: Path
    cases_dir: Path
    runs_dir: Path
    case_timeout: float = CASE_TIMEOUT_SECONDS

    @property
    def ledger_path(self) -> Path:
        return self.runs_dir / "ledger.jsonl"

    @property
    def ops_dir(self) -> Path:
        return self.runs_dir / "ops"

    @classmethod
    def from_env(
        cls,
        *,
        root: Path | None = None,
        cases_dir: Path | None = None,
        runs_dir: Path | None = None,
    ) -> "Config":
        """按 ``JUDGE_RUNS_DIR`` / ``JUDGE_CASES_DIR`` / ``JUDGE_CASE_TIMEOUT`` 构造。"""
        base = Path(root) if root is not None else REPO_ROOT
        cases = (
            Path(cases_dir)
            if cases_dir is not None
            else Path(os.environ.get("JUDGE_CASES_DIR") or (base / "cases"))
        )
        runs = (
            Path(runs_dir)
            if runs_dir is not None
            else Path(os.environ.get("JUDGE_RUNS_DIR") or (base / "runs"))
        )
        timeout = float(os.environ.get("JUDGE_CASE_TIMEOUT") or CASE_TIMEOUT_SECONDS)
        return cls(root=base, cases_dir=cases, runs_dir=runs, case_timeout=timeout)

    def case_input(self, name: str) -> Path:
        return self.cases_dir / f"{name}.in"

    def available_cases(self) -> list[str]:
        if not self.cases_dir.is_dir():
            return []
        return sorted(path.stem for path in self.cases_dir.glob("*.in"))
