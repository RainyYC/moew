"""服务层：HTTP + 队列 + 账本 + CLI 的共享实现。

* :mod:`.config`   —— 路径 / 超时 / 监听地址（``JUDGE_RUNS_DIR`` 等可覆盖）；
* :mod:`.ledger`   —— ``runs/ledger.jsonl`` 只追加 + ``fsync`` + ``flock``，ops 另存 jsonl；
* :mod:`.queue`    —— 队列与 worker（10 s/例超时 kill、幂等、状态机）；
* :mod:`.sse`      —— 事件总线（``run.queued/running/done/failed/timeout``）；
* :mod:`.server`   —— stdlib ``ThreadingHTTPServer``，只绑回环；
* :mod:`.selftest` —— 临时端口起服务，跑一遍 CONTRACT §2 的全部语义。

**合法性判定只调 ``judge.core``**：这一层不实现任何题面公式（CONTRACT §0 铁律）。
"""

from __future__ import annotations

__all__ = ["config", "ledger", "queue", "server", "sse"]
