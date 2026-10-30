"""判题系统顶层包。

三层结构（CONTRACT §0）：

* :mod:`judge.core`   —— 判题核心，**题面公式的唯一实现**（解析/校验/模拟/内存/Time）；
* ``judge.service``   —— HTTP 服务 + 队列 + 账本 + 切片（只调核心，不自己判合法性）；
* ``judge.cli``       —— agent 的主要入口（thin wrapper）。

``judge/`` 不得 import ``solver/`` 或 ``ui/``（CONTRACT §9）。
"""

__all__ = ["__version__"]

__version__ = "2.0.0"
