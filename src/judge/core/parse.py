"""输入 / 输出解析（题面 §2、§3；CONTRACT §1 的 ``ParseError`` 语义）。

分工
----
* **解析失败**（格式对不上、缺段、非整数、``mb:ℓ:op`` 结构坏掉）→ 抛
  :class:`ParseError`，服务层转 422；
* **格式可解析但映射非法**（网格、PSI、MAP 计数、调度依赖/资源/内存）→ 由
  :mod:`judge.core.sim` 返回 ``ok:false + errors[]``，服务层仍回 200。

输入解析走**按行**而非全 token 流：第 ℓ 层负载行是 ``T`` 或 ``T a_0 … a_{E-1}``；
若排版把下一层的首个 token 带到了同一行，多出的 token 顺延给下一层。全 token 流解析
无法区分 ``T`` 与负载向量（见 ``solution-report.md`` §4 第 1 条）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

__all__ = [
    "ParseError",
    "Case",
    "Op",
    "SchedRow",
    "Output",
    "parse_case",
    "parse_case_text",
    "parse_output",
]


class ParseError(ValueError):
    """输入或输出无法按题面格式解析（服务层 → 422）。"""

    def __init__(self, message: str, line: Optional[int] = None) -> None:
        self.message = message
        self.line = line
        super().__init__(f"第 {line} 行: {message}" if line is not None else message)


# --------------------------------------------------------------------------- #
# 输入：Case
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Case:
    """一个测试点的全部输入量（题面 §2）。

    行 1：``N S M Bin Bout``；行 2：``L E Z Zs U Uact k nmb Fs Fio Fin α× β×``；
    行 3：``d b``；行 4 起共 ``L`` 行层负载。

    ``loads[l]`` 为 ``None`` 表示该层负载均衡（题面要求评测器把 ``T_l`` 尽量均分给
    ``E`` 个专家），否则是长度为 ``E`` 的逐专家 slot 数元组 ``a_{l,e}``。
    """

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
    def ops_per_case(self) -> int:
        """一份完整调度的条目数（每层每 microbatch 十个操作）。"""
        return self.nmb * self.L * 10


def _ints(tokens: Sequence[str], line: Optional[int], what: str) -> list[int]:
    out: list[int] = []
    for token in tokens:
        try:
            out.append(int(token))
        except ValueError:
            raise ParseError(f"{what}: 需要整数，得到 {token!r}", line) from None
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
        raise ParseError("输入为空")

    def take(count: int, what: str) -> tuple[Optional[int], list[int]]:
        """从当前行取 ``count`` 个整数；行内多余的 token 保留给下一行。"""
        if not rows:
            raise ParseError(f"输入缺少 {what}")
        lineno, tokens = rows[0]
        if len(tokens) < count:
            raise ParseError(f"{what}: 需要 {count} 个整数，只有 {len(tokens)} 个", lineno)
        values = _ints(tokens[:count], lineno, what)
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
        raise ParseError(f"L 必须 ≥ 1，得到 {L}", body_line)
    if E < 1:
        raise ParseError(f"E 必须 ≥ 1，得到 {E}", body_line)
    if k < 1:
        raise ParseError(f"k 必须 ≥ 1，得到 {k}", body_line)
    if nmb < 1:
        raise ParseError(f"nmb 必须 ≥ 1，得到 {nmb}", body_line)
    if N < 1 or S < 1:
        raise ParseError(f"N,S 必须 ≥ 1，得到 {N},{S}", head_line)
    if Bin < 1 or Bout < 1:
        raise ParseError(f"Bin,Bout 必须 ≥ 1，得到 {Bin},{Bout}", head_line)
    if alpha_x < 0 or beta_x < 0:
        raise ParseError(f"α×,β× 必须 ≥ 0，得到 {alpha_x},{beta_x}", body_line)
    if d < 0 or b < 0:
        raise ParseError(f"d,b 必须 ≥ 0，得到 {d},{b}", db_line)

    totals: list[int] = []
    loads: list[Optional[tuple[int, ...]]] = []
    for index in range(L):
        if not rows:
            raise ParseError(f"输入缺少第 {index + 1} 个层负载行（需要 L={L} 行）")
        lineno, tokens = rows.pop(0)
        if len(tokens) == 1:
            totals.append(_ints(tokens, lineno, f"层 {index} 的 T")[0])
            loads.append(None)
            continue
        # 一行里既有本层负载向量、也可能带上了下一层的首个 token
        values = _ints(tokens, lineno, f"层 {index} 的负载行")
        totals.append(values[0])
        loads.append(tuple(values[1 : 1 + E]))
        extra = tokens[1 + E :]
        if len(tokens) < 1 + E:
            raise ParseError(
                f"层 {index} 的负载行需要 1 个（均衡）或 1+E={1 + E} 个 token，实际 {len(tokens)} 个",
                lineno,
            )
        if extra:
            rows.insert(0, (lineno, extra))

    if rows:
        lineno, tokens = rows[0]
        raise ParseError(f"输入在 L={L} 个层负载行之后还有多余内容：{' '.join(tokens[:6])}", lineno)

    for index, total in enumerate(totals):
        if total < 0:
            raise ParseError(f"层 {index} 的 T 必须 ≥ 0，得到 {total}")
        load = loads[index]
        if load is None:
            continue
        if len(load) != E:
            raise ParseError(f"层 {index} 的负载向量需要 E={E} 个数，实际 {len(load)} 个")
        if any(value < 0 for value in load):
            raise ParseError(f"层 {index} 的负载向量含负数")
        if sum(load) != total:
            raise ParseError(f"层 {index} 的负载向量之和 {sum(load)} ≠ T={total}")

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
    """读取并解析输入文件（题面 §2）。"""
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - 环境相关
        raise ParseError(f"无法读取输入文件 {file}: {exc}") from exc
    return parse_case_text(text, name=file.stem)


# --------------------------------------------------------------------------- #
# 输出：Output
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Op:
    """一个调度条目 ``mb:ℓ:op``。"""

    mb: int
    l: int
    op: str
    raw: str


@dataclass(frozen=True, slots=True)
class SchedRow:
    """调度的一行：时刻 ``t`` 与同一时刻开始的操作。"""

    t: int
    ops: tuple[Op, ...]
    line: int


@dataclass(frozen=True, slots=True)
class Output:
    """一份映射输出（题面 §3）。"""

    V: int
    P: int
    K: int
    psi: tuple[int, ...]
    map_rows: tuple[tuple[int, ...], ...]
    sched: tuple[SchedRow, ...]

    @property
    def D(self) -> int:
        """数据并行度已从题面移除；保留该属性恒为 1，供下游按 ``V·P·D=R`` 复核。"""
        return 1


def _parse_op(token: str, line: int) -> Op:
    parts = token.split(":")
    if len(parts) != 3:
        raise ParseError(f"调度条目必须是 mb:ℓ:op 三段，得到 {token!r}", line)
    try:
        mb = int(parts[0])
        layer = int(parts[1])
    except ValueError:
        raise ParseError(f"调度条目 {token!r} 的 mb/ℓ 需要整数", line) from None
    name = parts[2]
    if not name:
        raise ParseError(f"调度条目缺少操作名：{token!r}", line)
    return Op(mb=mb, l=layer, op=name, raw=token)


def parse_output(text: str) -> Output:
    """解析一份映射输出（题面 §3）。

    结构：``V P`` / ``PSI`` / ``K ψ…`` / ``MAP`` / ``L`` 行 σ / ``SCHEDULE`` /
    若干行 ``t mb:ℓ:op …``。MAP 行数与 PSI 切点数等**语义**约束留给
    :mod:`judge.core.sim` 报 ``field`` 类错误（HTTP 200 + ``ok:false``）。
    """
    rows: list[tuple[int, list[str]]] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if line:
            rows.append((lineno, line.split()))
    if not rows:
        raise ParseError("输出为空")

    pos = 0

    def marker(word: str) -> None:
        nonlocal pos
        if pos >= len(rows):
            raise ParseError(f"输出缺少 {word} 段")
        lineno, tokens = rows[pos]
        if len(tokens) != 1 or tokens[0] != word:
            raise ParseError(f"期望 {word} 标记，得到 {' '.join(tokens[:4])!r}", lineno)
        pos += 1

    lineno, tokens = rows[pos]
    pos += 1
    if len(tokens) != 2:
        raise ParseError(
            f"输出第 1 行必须是 V P 两个整数（2026-10 版题面取消了数据并行度 D），"
            f"得到 {len(tokens)} 个 token",
            lineno,
        )
    V, P = _ints(tokens, lineno, "V P")
    D = 1  # 新版网格只有 (V,P)：V·P=R，等价于固定 D=1

    marker("PSI")
    if pos >= len(rows):
        raise ParseError("输出缺少 PSI 内容行（块数与切点）")
    psi_line, psi_tokens = rows[pos]
    pos += 1
    K = _ints(psi_tokens[:1], psi_line, "PSI 行的块数 K")[0]
    psi = tuple(_ints(psi_tokens[1:], psi_line, "PSI 行的切点"))

    marker("MAP")
    map_rows: list[tuple[int, ...]] = []
    while pos < len(rows):
        row_line, row_tokens = rows[pos]
        if len(row_tokens) == 1 and row_tokens[0] == "SCHEDULE":
            break
        map_rows.append(tuple(_ints(row_tokens, row_line, "MAP 行")))
        pos += 1
    marker("SCHEDULE")

    sched: list[SchedRow] = []
    while pos < len(rows):
        row_line, row_tokens = rows[pos]
        pos += 1
        try:
            t = int(row_tokens[0])
        except ValueError:
            raise ParseError(f"调度行的时刻 t 需要整数，得到 {row_tokens[0]!r}", row_line) from None
        sched.append(
            SchedRow(
                t=t,
                ops=tuple([_parse_op(token, row_line) for token in row_tokens[1:]]),
                line=row_line,
            )
        )

    return Output(
        V=V,
        P=P,
        K=K,
        psi=psi,
        map_rows=tuple(map_rows),
        sched=tuple(sched),
    )
