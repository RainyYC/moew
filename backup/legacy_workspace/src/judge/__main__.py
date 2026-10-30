"""``python3 -m judge <子命令>`` 的入口（CLI 实现在 :mod:`judge.cli`）。"""

from __future__ import annotations

import sys

from judge.cli import main

if __name__ == "__main__":
    sys.exit(main())
