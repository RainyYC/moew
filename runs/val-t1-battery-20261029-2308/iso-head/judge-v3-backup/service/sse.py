"""SSE 事件总线（CONTRACT §2.7）。

事件类型：``run.queued / run.running / run.done / run.failed / run.timeout``，每条带
``run_id`` 与进度（``done`` / ``total``）。实现是一个线程安全的多订阅者广播：
worker 线程 ``publish``，每个 ``GET /api/events`` 请求各自 ``subscribe`` 一个队列。
"""

from __future__ import annotations

import json
import queue
import threading

__all__ = ["EventBus", "format_sse"]

#: 每个订阅者的缓冲上限（慢客户端丢事件而不是拖死 worker）。
SUBSCRIBER_CAPACITY = 4096


def format_sse(event: dict) -> bytes:
    """一条 SSE 帧（``event: <type>`` + ``data: <json>``）。"""
    kind = str(event.get("type") or "message")
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"event: {kind}\ndata: {payload}\n\n".encode("utf-8")


class EventBus:
    """运行状态广播。"""

    def __init__(self, history: int = 128) -> None:
        self._lock = threading.Lock()
        self._subscribers: set[queue.Queue] = set()
        self._history: list[dict] = []
        self._history_limit = history

    def subscribe(self) -> queue.Queue:
        channel: queue.Queue = queue.Queue(maxsize=SUBSCRIBER_CAPACITY)
        with self._lock:
            self._subscribers.add(channel)
        return channel

    def unsubscribe(self, channel: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(channel)

    def publish(self, event: dict) -> None:
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._history_limit:
                del self._history[: len(self._history) - self._history_limit]
            channels = list(self._subscribers)
        for channel in channels:
            try:
                channel.put_nowait(event)
            except queue.Full:  # pragma: no cover - 慢客户端
                continue

    def recent(self, limit: int = 20) -> list[dict]:
        with self._lock:
            return list(self._history[-limit:])

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)
