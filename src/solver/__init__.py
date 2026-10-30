"""求解器（`solution-report.md` §2 的复原）：网格枚举 + 切层 DP + LPT 放置 + 列表调度。

与判题核心的分工（CONTRACT §0 / §9）
------------------------------------
* **题面公式的判分权威只有一份，在 `judge/core`**；求解器为了排调度必须自己知道每层
  的 ``m_l`` / ``x_l`` / 十种操作时长，这是**允许的重复**，只用于生成候选与剪枝。
* 求解器**不 import `judge.core`、不读它的内部状态**；最终合法性只认
  ``python3 -m judge eval <case.in> <out> --json`` 子进程的判定（见 `solver/judgebridge.py`）。
* 两者不一致时以 judge 为准，差异记录在 `solver/NOTES.md`。
"""

__all__ = ["__version__"]

__version__ = "1.0.0"
