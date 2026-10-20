"""账本（CONTRACT §3）：``runs/ledger.jsonl`` 只追加 + ``fsync`` + ``flock``。

* 一行一次运行；**只增不改**（修正错误版本用新 run，不编辑旧行）；
* 追加时 ``flock(LOCK_EX)`` 保护 + ``write/flush/fsync``，落盘后才算这笔运行存在；
* 读取时 ``flock(LOCK_SH)`` 拿一致快照；
* ``ops`` 另存 ``runs/ops/<run_id>/<case>.jsonl``（每行一个 op），账本只存路径；
* 版本聚合（``/api/versions`` 与 ``judge ls``）也从这里读，避免出现第二份数字。
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import re
import threading
from array import array
from bisect import bisect_left
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

from .config import Config

__all__ = [
    "Ledger",
    "OPS_CACHE_LIMIT",
    "compute_versions",
    "geometric_score",
]

_RUN_ID = re.compile(r"^r-(\d+)$")

#: ops 解析缓存最多常驻几份文件。64 万条 ≈ 19 MB/份，4 份封顶，避免内存无界增长。
OPS_CACHE_LIMIT = 4


def _as_int(value: object) -> int:
    """把 ops 字段夹成 int（服务写入的一定是 int；坏行按 0 处理，不影响分页）。"""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


@dataclass
class _OpsTable:
    """一份 ``ops`` jsonl 的**列式**表示（字节级解析一次，之后整份常驻缓存）。

    列式存的是 int 数组而不是 64 万个 dict：64 万条约 19 MB（vs 展开成 dict 的数百 MB），
    分页时只把当页的 ``limit`` 条（≤ 20000）还原成 dict。
    """

    path: Path
    mtime_ns: int
    size: int
    names: list[str]
    t: array
    mb: array
    layer: array
    op_index: array
    dur: array
    group: array
    sorted_by_t: bool

    @property
    def length(self) -> int:
        return len(self.t)

    def op(self, index: int) -> dict:
        """还原成 CONTRACT §2.5 的 op 字段（键名/类型不变）。"""
        return {
            "t": self.t[index],
            "mb": self.mb[index],
            "l": self.layer[index],
            "op": self.names[self.op_index[index]],
            "dur": self.dur[index],
            "g": self.group[index],
        }


def _load_ops_table(path: Path, mtime_ns: int, size: int) -> _OpsTable:
    """把 ops jsonl 解析成列式表（每个文件只做一次）。"""
    names: list[str] = []
    name_index: dict[str, int] = {}
    stamps = array("q")
    mb_values = array("i")
    layer_values = array("i")
    op_indexes = array("i")
    durations = array("q")
    groups = array("i")
    sorted_by_t = True
    previous = -1
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                op = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(op, dict):
                continue
            stamp = op.get("t")
            if not isinstance(stamp, int) or isinstance(stamp, bool):
                continue  # 坏行跳过（账本/ops 只追加，不改历史）
            name = op.get("op")
            name = name if isinstance(name, str) else ""
            position = name_index.get(name)
            if position is None:
                position = len(names)
                names.append(name)
                name_index[name] = position
            if stamp < previous:
                sorted_by_t = False
            previous = stamp
            stamps.append(stamp)
            mb_values.append(_as_int(op.get("mb")))
            layer_values.append(_as_int(op.get("l")))
            op_indexes.append(position)
            durations.append(_as_int(op.get("dur")))
            groups.append(_as_int(op.get("g")))
    return _OpsTable(
        path=path,
        mtime_ns=mtime_ns,
        size=size,
        names=names,
        t=stamps,
        mb=mb_values,
        layer=layer_values,
        op_index=op_indexes,
        dur=durations,
        group=groups,
        sorted_by_t=sorted_by_t,
    )


def _in_window(stamp: int, since: Optional[int], until: Optional[int]) -> bool:
    if since is not None and stamp < since:
        return False
    if until is not None and stamp >= until:
        return False
    return True


def _slice_table(
    table: _OpsTable,
    *,
    since: Optional[int],
    until: Optional[int],
    group: Optional[int],
    mb: Optional[int],
    limit: int,
    cursor: int,
) -> dict:
    """从列式表里切一页（``since`` 含、``until`` 不含、``cursor`` = 过滤结果 offset）。"""
    limit = max(0, limit)
    cursor = max(0, cursor)
    if table.sorted_by_t:
        low = 0 if since is None else bisect_left(table.t, since)
        high = table.length if until is None else bisect_left(table.t, until)
        window = range(low, high)
    else:  # pragma: no cover - 服务写出的 ops 天然按 t 非降；外部坏文件退回线性过滤
        window = range(table.length)
    if table.sorted_by_t and group is None and mb is None:
        total = len(window)
        indices: Iterable[int] = window[cursor : cursor + limit]
    else:
        selected = [
            index
            for index in window
            if _in_window(table.t[index], since, until)
            and (group is None or table.group[index] == group)
            and (mb is None or table.mb[index] == mb)
        ]
        total = len(selected)
        indices = selected[cursor : cursor + limit]
    ops = [table.op(index) for index in indices]
    return {
        "total": total,
        "returned": len(ops),
        "next_cursor": None if not ops else (cursor + len(ops) if cursor + len(ops) < total else None),
        "ops": ops,
    }


class Ledger:
    """``runs/ledger.jsonl`` 的读写与 ops 落盘。"""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.runs_dir = config.runs_dir
        self.path = config.ledger_path
        #: ops 解析结果缓存：文件路径 → 列式表（``mtime``/``size`` 变化即失效）。
        self._ops_cache: "OrderedDict[str, _OpsTable]" = OrderedDict()
        self._ops_lock = threading.Lock()

    # -- 基础设施 ---------------------------------------------------------
    def ensure(self) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def relpath(self, path: Path) -> str:
        """账本里存的路径：优先相对 ``runs/`` 的父目录（即 ``runs/ops/…``）。"""
        for base in (self.runs_dir.parent, self.runs_dir, self.config.root):
            try:
                return str(path.relative_to(base))
            except ValueError:
                continue
        return str(path)

    def resolve(self, stored: str) -> Path:
        """把账本里的路径还原成实际文件路径。"""
        candidate = Path(stored)
        if candidate.is_absolute():
            return candidate
        for base in (self.runs_dir.parent, self.runs_dir, self.config.root):
            resolved = base / candidate
            if resolved.exists() or resolved.parent.exists():
                return resolved
        return self.config.root / candidate

    # -- 追加 / 读取 -------------------------------------------------------
    def append(self, row: dict) -> None:
        """追加一行运行记录（``flock`` + ``fsync``，写完才返回）。"""
        self.ensure()
        line = json.dumps(row, ensure_ascii=False) + "\n"
        with self.path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def rows(self) -> list[dict]:
        """读全部账本行（``flock(LOCK_SH)`` 一致快照；坏行跳过，不改历史）。"""
        self.ensure()
        collected: list[dict] = []
        with self.path.open("r", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
            try:
                for line in handle:
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        row = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(row, dict):
                        collected.append(row)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return collected

    def count(self) -> int:
        return len(self.rows())

    def next_id(self) -> str:
        """下一个 ``r-NNNN``（按已有账本行推进，跨重启不撞号）。"""
        highest = 0
        for row in self.rows():
            match = _RUN_ID.match(str(row.get("run_id") or ""))
            if match:
                highest = max(highest, int(match.group(1)))
        return f"r-{highest + 1:04d}"

    # -- ops --------------------------------------------------------------
    def write_ops(self, run_id: str, case: str, ops: Sequence[dict]) -> Optional[str]:
        """把 ops 写成 jsonl，返回账本里要存的路径（无 ops 时返回 ``None``）。"""
        if not ops:
            return None
        directory = self.runs_dir / "ops" / run_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{case}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for op in ops:
                handle.write(json.dumps(op, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        with self._ops_lock:
            self._ops_cache.pop(str(path.resolve()), None)
        return self.relpath(path)

    def read_ops_slice(
        self,
        stored_path: str,
        *,
        since: Optional[int] = None,
        until: Optional[int] = None,
        group: Optional[int] = None,
        mb: Optional[int] = None,
        limit: int = 5000,
        cursor: int = 0,
    ) -> dict:
        """按 ``since/until/group/mb`` 过滤后切片（CONTRACT §2.5）。

        ``since``/``until`` 按 ``t`` 过滤，区间为**半开** ``[since, until)``；``cursor`` 是
        过滤结果里的偏移量；``total`` 是该过滤条件的总数，``returned`` 是本页条数。

        性能：整份 ops 只解析一次（列式表进内存，``mtime``/``size`` 变化即失效），之后每页
        只做「``t`` 二分定位窗口 + 组/``mb`` 过滤 + 当页还原」，不再每请求整文件
        ``json.loads``。64 万条实测：首请求 ≈1.3 s、后续每页 ≈10 ms（原来 1.27 s/页）。
        """
        path = self.resolve(stored_path)
        if not path.is_file():
            return {"total": 0, "returned": 0, "next_cursor": None, "ops": []}
        table = self._ops_table(path)
        if table is None:  # pragma: no cover - 读不了的 ops 当空
            return {"total": 0, "returned": 0, "next_cursor": None, "ops": []}
        return _slice_table(
            table, since=since, until=until, group=group, mb=mb, limit=limit, cursor=cursor
        )

    def _ops_table(self, path: Path) -> Optional[_OpsTable]:
        """取（或建）某份 ops 的列式缓存；``mtime``/``size`` 变了就重建。"""
        try:
            stat = path.stat()
        except OSError:  # pragma: no cover
            return None
        key = str(path.resolve())
        with self._ops_lock:
            cached = self._ops_cache.get(key)
            if cached is not None and cached.mtime_ns == stat.st_mtime_ns and cached.size == stat.st_size:
                self._ops_cache.move_to_end(key)
                return cached
        try:
            table = _load_ops_table(path, stat.st_mtime_ns, stat.st_size)
        except OSError:  # pragma: no cover
            return None
        with self._ops_lock:
            self._ops_cache[key] = table
            self._ops_cache.move_to_end(key)
            while len(self._ops_cache) > OPS_CACHE_LIMIT:
                self._ops_cache.popitem(last=False)
        return table


def geometric_score(cases: dict[str, dict]) -> Optional[float]:
    """``score = 各用例 time/base 的几何平均``（CONTRACT §2.6 / 题面 §5.3）。

    任一用例非法、缺 ``base`` 或时间为空 → ``None``（版本仍然出现在列表里）。
    """
    if not cases:
        return None
    logs: list[float] = []
    for entry in cases.values():
        if not entry.get("ok"):
            return None
        time_value = entry.get("time")
        base = entry.get("base")
        if not isinstance(time_value, int) or not isinstance(base, int) or base <= 0 or time_value < 0:
            return None
        if time_value == 0:
            return 0.0
        logs.append(math.log(time_value / base))
    return round(math.exp(sum(logs) / len(logs)), 6)


def compute_versions(rows: Iterable[dict], bases: dict[str, int]) -> list[dict]:
    """把账本行聚合成 ``/api/versions`` 的版本表（按 rank 升序，``null`` 排最后）。"""
    entries: list[dict] = []
    for row in rows:
        cases: dict[str, dict] = {}
        for item in row.get("cases") or []:
            if not isinstance(item, dict) or "case" not in item:
                continue
            name = str(item["case"])
            cases[name] = {
                "time": item.get("time"),
                "base": bases.get(name),
                "ok": bool(item.get("ok")),
            }
        ok = bool(cases) and all(entry["ok"] for entry in cases.values())
        score = geometric_score(cases) if ok else None
        entries.append(
            {
                "version": row.get("version") or "?",
                "commit": row.get("commit") or "?",
                "run_id": row.get("run_id"),
                "score": score,
                "rank": None,
                "ok": ok,
                "cases": cases,
                "state": row.get("state") or ("done" if ok else "failed"),
                "actor": row.get("actor"),
                "origin": row.get("origin"),
                "created_at": row.get("created_at"),
                "notes": row.get("notes") or "",
            }
        )
    entries.sort(
        key=lambda entry: (
            entry["score"] is None,
            entry["score"] if entry["score"] is not None else 0.0,
            str(entry["created_at"] or ""),
            str(entry["run_id"] or ""),
        )
    )
    for index, entry in enumerate(entries, 1):
        entry["rank"] = index
    return entries
