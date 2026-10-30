#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实验候选入口：**显式启用** frontier 路线，供 `tools/frontier_bench.py --solver` 调用。

生产入口 `src/solver/solve_all.py` 默认关闭 frontier；本包装器只用于 t4/t5 的同预算对照，
保证“候选批次”确实走了新路线，而不是误把旧默认路径当候选：

    python3 tools/frontier_candidate.py <case.in> <out> --budget 7.6

等价于 `solve_all.py <case.in> <out> --budget 7.6 --frontier --frontier-mode B`。
可用环境变量 `FRONTIER_MODE=A|B|C|auto` 切换消融组（默认 B）。
stdout/退出码与 `solve_all.py` 单例模式完全一致；stderr 额外保留
`[frontier] enabled=… hits=… stop=…` 一行，供对照工具归档实际命中与停止原因。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from solver import solve_all  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    mode = os.environ.get("FRONTIER_MODE", "B")
    if mode not in ("A", "B", "C", "auto"):
        print(f"[frontier-candidate] 非法 FRONTIER_MODE={mode!r}", file=sys.stderr)
        return 2
    # 单例模式：solve_all 识别 argv[0] 为输入路径；选项放后面即可。
    return solve_all.main(raw + ["--frontier", "--frontier-mode", mode])


if __name__ == "__main__":
    sys.exit(main())
