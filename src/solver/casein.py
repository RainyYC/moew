"""测试点输入解析（题面 §2）。

与 `judge/core/parse.py` 的输入解析保持逐字段一致，但**独立实现**：求解器不 import
判题核心（CONTRACT §9）。格式细节以题面为准：

    第 1 行  N S M Bin Bout
    第 2 行  L E Z Zs U Uact k nmb Fs Fio Fin α× β×
    第 3 行  d b
    第 4 行起 L 行：T_l 或 T_l a_{l,0} … a_{l,E−1}

按行解析（而不是全 token 流）：负载向量允许把下一层的首个 token 带到同一行，多余的
token 顺延给下一行（`solution-report.md` §4 第 1 条）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class InputError(ValueError):
    """输入无法按题面格式解析。"""


@dataclass(frozen=True)
class Case:
    """一个测试点的全部输入量（题面 §2）。"""

    name: str
    N: int
    S: int
    M: int
    Bin: int
    Bout: int
    L: int
    E: int
    Z: int
    Zs: int
    U: int
    Uact: int
    k: int
    nmb: int
    Fs: int
    Fio: int
    Fin: int
    alpha_x: int
    beta_x: int
    d: int
    b: int
    T: tuple[int, ...]
    loads: tuple[Optional[tuple[int, ...]], ...]

    # -- 派生量 ------------------------------------------------------------
    @property
    def R(self) -> int:
        """总卡数 R = N·S。"""
        return self.N * self.S

    @property
    def H(self) -> int:
        """每 slot 发往一个对端的载荷字节数 H = ⌊d·b/k⌋（题面 §2 第 3 行）。"""
        return (self.d * self.b) // self.k

    @property
    def n_ops(self) -> int:
        """一份完整调度的条目数（每层每 microbatch 十个操作）。"""
        return self.nmb * self.L * 10


def _ints(tokens: list[str], what: str) -> list[int]:
    out: list[int] = []
    for token in tokens:
        try:
            out.append(int(token))
        except ValueError:
            raise InputError(f"{what}: 需要整数，得到 {token!r}") from None
    return out


def parse_case_text(text: str, name: str = "<inline>") -> Case:
    """解析一个测试点的输入文本。"""
    rows: list[tuple[int, list[str]]] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        rows.append((lineno, line.split()))
    if not rows:
        raise InputError("输入为空")

    def take(count: int, what: str) -> tuple[int, list[int]]:
        if not rows:
            raise InputError(f"输入缺少 {what}")
        lineno, tokens = rows[0]
        if len(tokens) < count:
            raise InputError(f"第 {lineno} 行：{what} 需要 {count} 个整数，只有 {len(tokens)} 个")
        values = _ints(tokens[:count], what)
        if len(tokens) == count:
            rows.pop(0)
        else:
            rows[0] = (lineno, tokens[count:])
        return lineno, values

    head_line, head = take(5, "第 1 行 N S M Bin Bout")
    body_line, body = take(13, "第 2 行 L E Z Zs U Uact k nmb Fs Fio Fin α× β×")
    db_line, db = take(2, "第 3 行 d b")

    N, S, M, Bin, Bout = head
    (L, E, Z, Zs, U, Uact, k, nmb, Fs, Fio, Fin, alpha_x, beta_x) = body
    d, b = db

    if L < 1:
        raise InputError(f"第 {body_line} 行：L 必须 ≥ 1，得到 {L}")
    if E < 1:
        raise InputError(f"第 {body_line} 行：E 必须 ≥ 1，得到 {E}")
    if k < 1:
        raise InputError(f"第 {body_line} 行：k 必须 ≥ 1，得到 {k}")
    if nmb < 1:
        raise InputError(f"第 {body_line} 行：nmb 必须 ≥ 1，得到 {nmb}")
    if N < 1 or S < 1:
        raise InputError(f"第 {head_line} 行：N,S 必须 ≥ 1，得到 {N},{S}")
    if Bin < 1 or Bout < 1:
        raise InputError(f"第 {head_line} 行：Bin,Bout 必须 ≥ 1，得到 {Bin},{Bout}")
    if alpha_x < 0 or beta_x < 0:
        raise InputError(f"第 {body_line} 行：α×,β× 必须 ≥ 0")
    if d < 0 or b < 0:
        raise InputError(f"第 {db_line} 行：d,b 必须 ≥ 0")

    totals: list[int] = []
    loads: list[Optional[tuple[int, ...]]] = []
    for index in range(L):
        if not rows:
            raise InputError(f"输入缺少第 {index + 1} 个层负载行（需要 L={L} 行）")
        lineno, tokens = rows.pop(0)
        if len(tokens) == 1:
            totals.append(_ints(tokens, f"层 {index} 的 T")[0])
            loads.append(None)
            continue
        values = _ints(tokens, f"层 {index} 的负载行")
        if len(values) < 1 + E:
            raise InputError(
                f"第 {lineno} 行：层 {index} 的负载行需要 1 个（均衡）或 1+E={1 + E} 个 token，"
                f"实际 {len(values)} 个"
            )
        totals.append(values[0])
        loads.append(tuple(values[1 : 1 + E]))
        extra = tokens[1 + E :]
        if extra:
            rows.insert(0, (lineno, extra))

    if rows:
        lineno, tokens = rows[0]
        raise InputError(f"第 {lineno} 行：L={L} 个层负载行之后还有多余内容 {' '.join(tokens[:6])!r}")

    for index, total in enumerate(totals):
        if total < 0:
            raise InputError(f"层 {index} 的 T 必须 ≥ 0，得到 {total}")
        load = loads[index]
        if load is None:
            continue
        if any(value < 0 for value in load):
            raise InputError(f"层 {index} 的负载向量含负数")
        if sum(load) != total:
            raise InputError(f"层 {index} 的负载向量之和 {sum(load)} ≠ T={total}")

    return Case(
        name=name,
        N=N,
        S=S,
        M=M,
        Bin=Bin,
        Bout=Bout,
        L=L,
        E=E,
        Z=Z,
        Zs=Zs,
        U=U,
        Uact=Uact,
        k=k,
        nmb=nmb,
        Fs=Fs,
        Fio=Fio,
        Fin=Fin,
        alpha_x=alpha_x,
        beta_x=beta_x,
        d=d,
        b=b,
        T=tuple(totals),
        loads=tuple(loads),
    )


def parse_case(path: str | Path) -> Case:
    """读取并解析一个测试点输入文件。"""
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as exc:
        raise InputError(f"无法读取输入文件 {file}: {exc}") from exc
    return parse_case_text(text, name=file.stem)
