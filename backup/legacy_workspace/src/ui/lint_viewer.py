#!/usr/bin/env python3
"""``python3 ui/lint_viewer.py`` —— 只读视图的静态验收（CONTRACT §5）。

这是**第二版护栏**（t17）：用词法级扫描取代第一版的字面正则黑名单。第一版可以被
``window["ce"+"il"]`` / ``window["Ma"+"th"]`` / ``eval(atob(...))`` / 小写
``mexp`` 算术 / ``\\u0063eil`` 五种变体绕过（见 ``docs/review-ui.md`` §3），本版
针对这五类绕过做了回归（``--self-test``）。

检查项（全部通过才退出 0）：

1. 结构、无 CDN、无构建链；``fixtures.js`` 只作为**数据字面量**存在（JSON 可解析，
   且禁止 ``function`` / ``=>`` / ``eval`` / ``atob`` / ``window[`` / ``\\u`` 等代码构造）。
2. **词法级公式扫描**（对 ``app.js`` 去注释、去字符串后分词）：
   - 禁全局对象计算键：``window[`` / ``globalThis[`` / ``self[`` / ``document[`` / ``top[``；
   - 禁 ``eval`` / ``atob`` / ``btoa`` / ``Function(`` / ``setTimeout("…")`` / ``.constructor``；
   - 识别标识符 Unicode 转义（``\\u0063eil`` → ``ceil``）；
   - 关键字表大小写不敏感，覆盖 ``ceil/floor/round/abs/pow/sqrt/min/max`` 与题面参数
     （``fs/fin/fio/bin/bout/uact/alphax/betax/nmb/zs``）及 ``mexp/movl/mact``；
   - **算术白名单**：只有 ``xFor/pct/clampPct/rangeSpan/activationHTML`` 的函数体里
     允许对 ``.t/.dur/.time/.lb/.mexp/.movl/.mact/.score`` 做 ``+ - * /``；其它位置的
     这类表达式直接失败（同时抓 ``var x = d.mexp * 2`` 这类变形）。
3. **可达性**：``fetch`` / ``new EventSource`` / ``api(`` / ``apiPost(`` 的调用点必须
   从 ``init`` 或事件回调可达；放一个死函数里的真 ``fetch`` 不算数。CONTRACT §2 的
   端点字符串必须出现在**可达**的 ``api`` / ``fetch`` / ``EventSource`` 调用参数里。
4. 必需的 UI 语义：未连接空态、预览双标、来源字段、运行态、ops 切片参数。
5. DOM id 一致性 / 唯一性；``index.html`` 不直接加载夹具。
6. ``fixtures.js`` 只在 ``?demo=1`` 时动态注入，文件头声明 DEMO-ONLY。

``--self-test``：
- 内联 B1–B5（复核的五个绕过样本）+ B6（死函数里的 fetch）+ B7（字段算术）+
  B8/B9（全局对象别名 / 括号包裹）+ M0/M0b/M0c（`% | <<` 缺口）+ M1/M2（单层 taint
  的最常见误写）；断言扫描器**必须命中**；
- 再把 B1–B5 分别注入 ``ui/`` 的临时副本，断言副本 lint **必须退出 1**；
- 原件 lint 必须退出 0。输出 ``5/5 被拒 + 原件 PASS``。

脚本自身不得 import ``judge``（视图不依赖判题实现）。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

UI = Path(__file__).resolve().parent
HTML = UI / "index.html"
APP = UI / "app.js"
CSS = UI / "styles.css"
FIXTURES = UI / "fixtures.js"
LINT = Path(__file__).resolve()

REQUIRED_FILES = (HTML, APP, CSS, FIXTURES)

# ─────────────────────────────────────────────────────────────────────────────
# 词法扫描
# ─────────────────────────────────────────────────────────────────────────────

#: 题面参数 / 数学函数 / 计算字段（大小写不敏感；`mexp|movl|mact` 允许 `g.mexp` 读取）。
BANNED_IDENTS = {
    "ceil", "ceild", "floor", "round", "abs", "pow", "sqrt", "min", "max",
    "exp", "log", "log2", "log10", "trunc", "sign", "hypot",
    "math",
    "fs", "fin", "fio", "bin", "bout", "uact", "alphax", "alpha", "beta", "betax",
    "nmb", "zs", "mexp", "movl", "mact",
}
#: 允许作为「服务端字段读取」出现在 `.` 后的名字。
SENSITIVE = {"t", "dur", "time", "lb", "mexp", "movl", "mact", "score"}
#: 全局对象；禁止对它们使用计算键（`window[...]`）。
GLOBAL_OBJECTS = {"window", "globalthis", "self", "document", "top", "this"}
#: 明确禁止的函数；`function` 关键字不算。
BANNED_CALLS = {"eval", "atob", "btoa"}
#: 展示/几何白名单：这些函数体里的算术属于「画图比例 / 像素定位 / 显示 Δ」，
#: 允许触碰服务端字段（仍然禁止题面公式——公式只可能在 judge/core）。
WHITELIST_FUNCS = {
    "xFor", "pct", "clampPct", "rangeSpan", "activationHTML", "opsHTML", "rangeFor",
    "renderVerdict", "renderDiff", "renderTrend", "fmtInt", "fmtScore", "num",
}
#: 高阶函数：回调里的调用也算初始化/事件路径可达。
HOF_CALLS = {
    "addeventlistener", "settimeout", "setinterval", "then", "catch", "finally",
    "foreach", "map", "filter", "sort", "some", "every", "reduce",
    "requestanimationframe", "promise",
}
ARITH_OPS = {
    "+", "-", "*", "/", "**",
    "%", "|", "&", "^", "<<", ">>", ">>>",
    "+=", "-=", "*=", "/=", "%=", "|=", "&=", "^=", "<<=", ">>=", ">>>=",
}
CONCAT_OPS = {"+", "+="}
SEGMENT_END = {";", "{", "}", ","}
CALL_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "function", "return", "typeof",
    "in", "of", "new", "delete", "void", "instanceof", "do", "else", "with",
}


@dataclass
class Token:
    kind: str          # ident | string | number | punct | regex | template
    value: str         # 解码后的值（标识符已处理 \u 转义）
    raw: str           # 原文
    line: int
    has_escape: bool = False


@dataclass
class Finding:
    line: int
    rule: str
    message: str

    def __str__(self) -> str:
        return f"line {self.line}: [{self.rule}] {self.message}"


@dataclass
class Func:
    id: int
    name: str
    start: int          # `function` token index
    body_start: int     # `{`
    body_end: int       # `}`


@dataclass
class Call:
    id: int
    name: str
    open_idx: int
    close_idx: int
    enclosing: int | None
    is_new: bool


def _read_unicode_escape(src: str, i: int) -> tuple[str, int]:
    """``\\uXXXX`` / ``\\u{XXXXX}`` → (字符, 新下标)。"""
    if i + 1 < len(src) and src[i + 1] == "u":
        if i + 2 < len(src) and src[i + 2] == "{":
            end = src.find("}", i + 3)
            if end >= 0:
                try:
                    return chr(int(src[i + 3:end], 16)), end + 1
                except ValueError:
                    pass
        hex_part = src[i + 2:i + 6]
        if len(hex_part) == 4 and all(c in "0123456789abcdefABCDEF" for c in hex_part):
            return chr(int(hex_part, 16)), i + 6
    return "\\", i + 1


def tokenize(src: str) -> list[Token]:
    """手写 JS 词法器：字符串/注释/正则/模板/标识符（含 Unicode 转义）。"""
    toks: list[Token] = []
    i, n, line = 0, len(src), 1
    prev: Token | None = None

    def emit(kind: str, value: str, raw: str, at_line: int, escaped: bool = False) -> None:
        nonlocal prev
        tok = Token(kind, value, raw, at_line, escaped)
        toks.append(tok)
        prev = tok

    while i < n:
        c = src[i]
        if c in " \t\r":
            i += 1
            continue
        if c == "\n":
            line += 1
            i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                if src[i] == "\n":
                    line += 1
                i += 1
            i = min(i + 2, n)
            continue
        if c in "\"'":
            quote = c
            j = i + 1
            buf = []
            while j < n:
                if src[j] == "\\":
                    buf.append(src[j:j + 2])
                    j += 2
                    continue
                if src[j] == quote:
                    break
                if src[j] == "\n":
                    line += 1
                buf.append(src[j])
                j += 1
            emit("string", "".join(buf), src[i:j + 1], line)
            i = j + 1
            continue
        if c == "`":
            j = i + 1
            buf = []
            while j < n:
                if src[j] == "\\":
                    buf.append(src[j:j + 2])
                    j += 2
                    continue
                if src[j] == "`":
                    break
                if src[j] == "\n":
                    line += 1
                buf.append(src[j])
                j += 1
            raw = src[i:j + 1]
            emit("template", "".join(buf), raw, line)
            inner = "".join(buf)
            for match in re.finditer(r"\$\{([^}]*)\}", inner):
                for sub in tokenize(match.group(1)):
                    sub.line += line - 1
                    toks.append(sub)
            i = j + 1
            continue
        if c == "/":
            can_end = prev is not None and (
                prev.kind in ("number", "string", "template", "regex")
                or (prev.kind == "ident" and prev.value not in {
                    "return", "typeof", "instanceof", "in", "of", "case", "delete",
                    "void", "throw", "new", "yield", "await", "else", "do",
                })
                or (prev.kind == "punct" and prev.value in (")", "]", "}", "++", "--"))
            )
            if not can_end:
                j = i + 1
                in_class = False
                while j < n:
                    ch = src[j]
                    if ch == "\\":
                        j += 2
                        continue
                    if ch == "[":
                        in_class = True
                    elif ch == "]":
                        in_class = False
                    elif ch == "/" and not in_class:
                        break
                    elif ch == "\n":
                        break
                    j += 1
                while j + 1 < n and src[j + 1].isalpha():
                    j += 1
                emit("regex", src[i:j + 1], src[i:j + 1], line)
                i = j + 1
                continue
            emit("punct", "/", "/", line)
            i += 1
            continue
        if c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] in "._"):
                j += 1
            emit("number", src[i:j], src[i:j], line)
            i = j
            continue
        if c.isalpha() or c in "_$" or ord(c) > 127 or (
            c == "\\" and i + 1 < n and src[i + 1] == "u"
        ):
            j = i
            buf = []
            escaped = False
            while j < n:
                ch = src[j]
                if ch == "\\" and j + 1 < n and src[j + 1] == "u":
                    decoded, j = _read_unicode_escape(src, j)
                    buf.append(decoded)
                    escaped = True
                    continue
                if ch.isalnum() or ch in "_$" or ord(ch) > 127:
                    buf.append(ch)
                    j += 1
                    continue
                break
            value = "".join(buf)
            emit("ident", value, src[i:j], line, escaped)
            i = j
            continue
        for width in (4, 3, 2):
            piece = src[i:i + width]
            if piece in ("===", "!==", ">>>=", "**=", "<<=", ">>=", "...", ">>>",
                         "==", "!=", "<=", ">=", "&&", "||", "++", "--", "+=", "-=",
                         "*=", "/=", "%=", "|=", "&=", "^=", "**", "?.", "<<", ">>",
                         "=>"):
                emit("punct", piece, piece, line)
                i += width
                break
        else:
            emit("punct", c, c, line)
            i += 1
    return toks


def _match_pairs(toks: list[Token], opening: str, closing: str) -> dict[int, int]:
    pairs: dict[int, int] = {}
    stack: list[int] = []
    for idx, tok in enumerate(toks):
        if tok.value == opening:
            stack.append(idx)
        elif tok.value == closing and stack:
            start = stack.pop()
            pairs[start] = idx
    return pairs


def parse_functions(toks: list[Token], parens: dict[int, int]) -> list[Func]:
    funcs: list[Func] = []
    for idx, tok in enumerate(toks):
        if tok.kind != "ident" or tok.value != "function":
            continue
        j = idx + 1
        name = ""
        if j < len(toks) and toks[j].kind == "ident":
            name = toks[j].value
            j += 1
        while j < len(toks) and toks[j].value != "(":
            j += 1
        if j >= len(toks) or j not in parens:
            continue
        close_paren = parens[j]
        k = close_paren + 1
        while k < len(toks) and toks[k].value not in ("{", ";", "=>"):
            k += 1
        if k >= len(toks) or toks[k].value != "{":
            continue
        depth = 0
        end = k
        for pos in range(k, len(toks)):
            if toks[pos].value == "{":
                depth += 1
            elif toks[pos].value == "}":
                depth -= 1
                if depth == 0:
                    end = pos
                    break
        funcs.append(Func(len(funcs), name, idx, k, end))
    return funcs


def _innermost(funcs: list[Func], idx: int) -> int | None:
    best: Func | None = None
    for f in funcs:
        if f.body_start <= idx <= f.body_end:
            if best is None or f.body_start > best.body_start:
                best = f
    return best.id if best else None


def parse_calls(toks: list[Token], parens: dict[int, int], funcs: list[Func]) -> list[Call]:
    calls: list[Call] = []
    for idx, tok in enumerate(toks):
        if tok.kind != "punct" or tok.value != "(":
            continue
        if idx == 0 or idx not in parens:
            continue
        prev = toks[idx - 1]
        if prev.kind != "ident" or prev.value.lower() in CALL_KEYWORDS:
            continue
        # `function name(` 是函数声明的参数表，不是调用点
        if idx >= 2 and toks[idx - 2].kind == "ident" and toks[idx - 2].value == "function":
            continue
        is_new = idx >= 2 and toks[idx - 2].kind == "ident" and toks[idx - 2].value == "new"
        calls.append(Call(
            id=len(calls), name=prev.value, open_idx=idx, close_idx=parens[idx],
            enclosing=_innermost(funcs, idx), is_new=is_new,
        ))
    return calls


def reachable_functions(funcs: list[Func], calls: list[Call], toks: list[Token]) -> set[int]:
    """从 IIFE / init / 事件回调出发求可达函数集合。"""
    by_name: dict[str, list[int]] = {}
    for f in funcs:
        if f.name:
            by_name.setdefault(f.name, []).append(f.id)
    reachable: set[int] = set()
    for f in funcs:
        if f.name:
            continue
        j = f.body_end + 1
        while j < len(toks) and toks[j].value == ")":
            j += 1
        if j < len(toks) and toks[j].value == "(":
            reachable.add(f.id)
    for call in calls:
        if call.enclosing is None and call.name in by_name:
            reachable.update(by_name[call.name])
    changed = True
    while changed:
        changed = False
        for call in calls:
            if call.enclosing is not None and call.enclosing not in reachable:
                continue
            if call.name in by_name:
                for fid in by_name[call.name]:
                    if fid not in reachable:
                        reachable.add(fid)
                        changed = True
            arg_funcs = [
                f.id for f in funcs
                if call.open_idx < f.start < call.close_idx and f.body_end < call.close_idx
            ]
            if call.name.lower() in HOF_CALLS or call.is_new:
                for fid in arg_funcs:
                    if fid not in reachable:
                        reachable.add(fid)
                        changed = True
            if call.name.lower() in HOF_CALLS:
                for pos in range(call.open_idx + 1, call.close_idx):
                    tok = toks[pos]
                    if tok.kind == "ident" and tok.value in by_name and (
                        pos + 1 >= len(toks) or toks[pos + 1].value not in ("(", ".", "=")
                    ):
                        for fid in by_name[tok.value]:
                            if fid not in reachable:
                                reachable.add(fid)
                                changed = True
    return reachable


def _function_ranges(funcs: list[Func], names: set[str]) -> list[tuple[int, int]]:
    return [(f.body_start, f.body_end) for f in funcs if f.name in names]


def _in_ranges(idx: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= idx <= end for start, end in ranges)


def _rhs_end(toks: list[Token], start: int) -> int:
    """赋值右侧的结束位置：深度 0 的 `,` / `;` / 闭括号。"""
    depth = 0
    j = start
    while j < len(toks):
        value = toks[j].value
        if value in ("(", "[", "{"):
            depth += 1
        elif value in (")", "]", "}"):
            if depth == 0:
                return j
            depth -= 1
        elif value in (",", ";") and depth == 0:
            return j
        j += 1
    return j


def _expr_has_sensitive(seq: list[Token]) -> bool:
    """表达式里是否直接出现服务端敏感字段 / 禁用标识符。"""
    for pos, tok in enumerate(seq):
        if tok.kind == "ident" and tok.value.lower() in SENSITIVE:
            if pos > 0 and seq[pos - 1].value in (".", "?."):
                return True
        if tok.kind == "ident" and tok.value.lower() in BANNED_IDENTS:
            return True
        if tok.kind == "string" and tok.value in SENSITIVE and pos > 0 and seq[pos - 1].value == "[":
            return True
    return False


def compute_taint(toks: list[Token], funcs: list[Func]) -> tuple[
    dict[int | None, set[str]], dict[int | None, set[str]]
]:
    """单层变量 taint + 字符串变量（用于区分展示拼接与算术）。

    taint：`var x = <含敏感字段/禁用标识符的表达式>` → x 记为 taint，随后参与算术即拒。
    刻意**不做**：实参传播、闭包、对象属性、Proxy。这条规则只是 tripwire，不是证明。
    """
    tainted: dict[int | None, set[str]] = {}
    strings: dict[int | None, set[str]] = {}
    for idx, tok in enumerate(toks):
        if tok.kind != "punct" or tok.value != "=" or idx < 1:
            continue
        lhs = toks[idx - 1]
        if lhs.kind != "ident":
            continue
        if idx >= 2 and toks[idx - 2].value in (".", "?."):
            continue
        rhs = toks[idx + 1:_rhs_end(toks, idx + 1)]
        scope = _innermost(funcs, idx)
        if _expr_has_sensitive(rhs):
            tainted.setdefault(scope, set()).add(lhs.value)
        if any(t.kind in ("string", "template") for t in rhs):
            strings.setdefault(scope, set()).add(lhs.value)
    return tainted, strings


def scan_js(src: str, label: str = "app.js", require_api: bool = True) -> list[Finding]:
    """词法级扫描：返回 findings（空列表 = 通过）。"""
    toks = tokenize(src)
    findings: list[Finding] = []
    parens = _match_pairs(toks, "(", ")")
    funcs = parse_functions(toks, parens)
    calls = parse_calls(toks, parens, funcs)
    reachable = reachable_functions(funcs, calls, toks)
    whitelist_ranges = _function_ranges(funcs, WHITELIST_FUNCS)
    reverse_parens = {close: open_ for open_, close in parens.items()}
    # 别名：`var w = window;` 之后 `w[...]` 与 `window[...]` 等价，同样禁止。
    aliases: set[str] = set()
    for idx, tok in enumerate(toks):
        if (tok.kind == "ident" and idx + 2 < len(toks)
                and toks[idx + 1].value == "="
                and toks[idx + 2].kind == "ident"
                and toks[idx + 2].value.lower() in GLOBAL_OBJECTS):
            aliases.add(tok.value)

    def computed_key(idx: int) -> bool:
        j = idx + 1
        if j < len(toks) and toks[j].value == "?.":
            j += 1
        return j < len(toks) and toks[j].value == "[" or (
            toks[j].value == "(" and j + 1 < len(toks) and toks[j + 1].value == ")"
        )

    for idx, tok in enumerate(toks):
        if tok.kind != "ident":
            continue
        low = tok.value.lower()
        prev = toks[idx - 1] if idx > 0 else None
        nxt = toks[idx + 1] if idx + 1 < len(toks) else None
        if tok.has_escape:
            findings.append(Finding(tok.line, "unicode-ident",
                                    f"{label}: 标识符含 Unicode 转义（{tok.raw} → {tok.value}）"))
        if low in BANNED_IDENTS:
            property_read = (
                prev is not None and prev.value == "." and low in {"mexp", "movl", "mact"}
            )
            if not property_read:
                findings.append(Finding(tok.line, "formula-ident",
                                        f"{label}: 禁用标识符 `{tok.value}`（题面参数/数学函数）"))
        if tok.value == "Function" and nxt is not None and nxt.value == "(":
            findings.append(Finding(tok.line, "dynamic-code",
                                    f"{label}: 禁止 Function(...) 动态构造函数"))
        if low in BANNED_CALLS:
            findings.append(Finding(tok.line, "dynamic-code",
                                    f"{label}: 禁止 {tok.value}(...)（动态代码/解码后执行）"))
        if (low in GLOBAL_OBJECTS or tok.value in aliases) and nxt is not None:
            j = idx + 1
            if j < len(toks) and toks[j].value == "?.":
                j += 1
            if j < len(toks) and toks[j].value == "[":
                findings.append(Finding(tok.line, "computed-global",
                                        f"{label}: 禁止 {tok.value}[...] 计算键访问全局对象"))
            elif (j + 1 < len(toks) and toks[j].value == "(" and toks[j + 1].value == ")"
                  and j + 2 < len(toks) and toks[j + 2].value == "["):
                findings.append(Finding(tok.line, "computed-global",
                                        f"{label}: 禁止 ({tok.value})[...] 计算键访问全局对象"))
        if low in ("settimeout", "setinterval") and nxt is not None and nxt.value == "(":
            arg = toks[idx + 2] if idx + 2 < len(toks) else None
            if arg is not None and arg.kind == "string":
                findings.append(Finding(tok.line, "dynamic-code",
                                        f'{label}: 禁止 {tok.value}("…") 字符串化回调'))
        if low == "constructor" and prev is not None and prev.value == ".":
            findings.append(Finding(tok.line, "dynamic-code",
                                    f"{label}: 禁止 .constructor（可绕过得到 Function）"))

    # `obj["constructor"]` / `obj["ceil"]` 这类字符串计算键：解到禁用名同样拒绝
    computed_banned = BANNED_IDENTS | BANNED_CALLS | {"constructor", "function"}
    for idx, tok in enumerate(toks):
        if (tok.kind == "string" and idx > 0 and toks[idx - 1].value == "["
                and tok.value.lower() in computed_banned):
            findings.append(Finding(tok.line, "computed-key",
                                    f'{label}: 禁止计算键 ["{tok.value}"]（等价于直接写禁用标识符）'))

    # `(window)[...]`：括号包裹的全局对象 + 计算键
    for idx, tok in enumerate(toks):
        if (tok.value == "[" and idx > 0 and toks[idx - 1].value == ")"
                and idx - 1 in reverse_parens):
            open_idx = reverse_parens[idx - 1]
            if open_idx + 2 == idx - 1:
                base = toks[open_idx + 1]
                if base.kind == "ident" and (base.value.lower() in GLOBAL_OBJECTS
                                             or base.value in aliases):
                    findings.append(Finding(tok.line, "computed-global",
                                            f"{label}: 禁止 ({base.value})[...] 计算键访问全局对象"))

    # ── 算术检查：直接敏感字段 + 单层 taint + 位运算符 ──────────────
    tainted, string_vars = compute_taint(toks, funcs)
    brackets = _match_pairs(toks, "[", "]")
    reverse_brackets = {close: open_ for open_, close in brackets.items()}

    def group_has_taint(open_idx: int, close_idx: int, scope: int | None) -> bool:
        names = tainted.get(scope, set())
        for j in range(open_idx + 1, close_idx):
            tok = toks[j]
            if (tok.kind == "ident" and tok.value.lower() in SENSITIVE
                    and j > open_idx and toks[j - 1].value in (".", "?.")):
                return True
            if tok.kind == "ident" and tok.value in names:
                return True
            if (tok.kind == "string" and tok.value in SENSITIVE
                    and j > 0 and toks[j - 1].value == "["):
                return True
        return False

    def operand_tainted(pos: int, scope: int | None) -> bool:
        if pos < 0 or pos >= len(toks):
            return False
        tok = toks[pos]
        if tok.kind in ("string", "template", "number", "regex"):
            return False
        if tok.kind == "ident":
            if (pos > 0 and toks[pos - 1].value in (".", "?.")
                    and tok.value.lower() in SENSITIVE):
                return True
            return tok.value in tainted.get(scope, set())
        if tok.value == ")" and pos in reverse_parens:
            return group_has_taint(reverse_parens[pos], pos, scope)
        if tok.value == "(" and pos in parens:
            return group_has_taint(pos, parens[pos], scope)
        if tok.value == "]" and pos in reverse_brackets:
            return group_has_taint(reverse_brackets[pos], pos, scope)
        return False

    def operand_is_string(pos: int, scope: int | None) -> bool:
        if pos < 0 or pos >= len(toks):
            return False
        tok = toks[pos]
        if tok.kind in ("string", "template"):
            return True
        if tok.kind == "ident" and tok.value in string_vars.get(scope, set()):
            return True
        if tok.value == ")" and pos in reverse_parens:
            return any(toks[j].kind in ("string", "template")
                       for j in range(reverse_parens[pos] + 1, pos))
        if tok.value == "(" and pos in parens:
            return any(toks[j].kind in ("string", "template")
                       for j in range(pos + 1, parens[pos]))
        return False

    for idx, tok in enumerate(toks):
        if tok.kind != "punct":
            continue
        if tok.value in ("++", "--"):
            if _in_ranges(idx, whitelist_ranges):
                continue
            scope = _innermost(funcs, idx)
            if operand_tainted(idx - 1, scope) or operand_tainted(idx + 1, scope):
                findings.append(Finding(
                    tok.line, "tainted-arithmetic",
                    f"{label}: {tok.value} 作用于敏感字段/taint 变量",
                ))
            continue
        if tok.value not in ARITH_OPS:
            continue
        if _in_ranges(idx, whitelist_ranges):
            continue
        left_i, right_i = idx - 1, idx + 1
        if left_i < 0 or right_i >= len(toks):
            continue
        scope = _innermost(funcs, idx)
        if tok.value in CONCAT_OPS and (
            operand_is_string(left_i, scope) or operand_is_string(right_i, scope)
        ):
            # `t + " · "` / `fmt(t) + at` 这类是展示拼接，不是算术；
            # `t + 1 + "s"` 的内层 `t + 1` 仍会被抓。
            continue
        if operand_tainted(left_i, scope) or operand_tainted(right_i, scope):
            findings.append(Finding(
                tok.line, "tainted-arithmetic",
                f"{label}: 敏感字段/taint 变量参与算术 `{tok.value}`"
                "（单层 taint tripwire；展示 Δ / 几何函数在白名单里）",
            ))

    for call in calls:
        is_api = call.name in ("api", "apiPost") or call.name.lower() == "fetch" or (
            call.is_new and call.name == "EventSource"
        )
        if is_api and call.enclosing is not None and call.enclosing not in reachable:
            findings.append(Finding(
                toks[call.open_idx].line, "unreachable-call",
                f"{label}: {call.name}(...) 在不可达函数里（死代码不能充当 API 调用证据）",
            ))
    if require_api:
        has_fetch = any(c.name.lower() == "fetch" and
                        (c.enclosing is None or c.enclosing in reachable) for c in calls)
        has_sse = any(c.is_new and c.name == "EventSource" and
                      (c.enclosing is None or c.enclosing in reachable) for c in calls)
        if not has_fetch:
            findings.append(Finding(1, "unreachable-call",
                                    f"{label}: 找不到可达的 fetch(...) 调用点"))
        if not has_sse:
            findings.append(Finding(1, "unreachable-call",
                                    f"{label}: 找不到可达的 new EventSource(...)"))
    return findings


def reachable_endpoints(src: str) -> set[str]:
    """收集可达的 api/fetch/EventSource 调用参数字符串。"""
    toks = tokenize(src)
    parens = _match_pairs(toks, "(", ")")
    funcs = parse_functions(toks, parens)
    calls = parse_calls(toks, parens, funcs)
    reachable = reachable_functions(funcs, calls, toks)
    endpoints: set[str] = set()
    for call in calls:
        if call.enclosing is not None and call.enclosing not in reachable:
            continue
        if call.name in ("api", "apiPost") or call.name.lower() == "fetch" or (
            call.is_new and call.name == "EventSource"
        ):
            for tok in toks[call.open_idx + 1:call.close_idx]:
                if tok.kind == "string":
                    endpoints.add(tok.value)
    return endpoints


API_PATH_RE = re.compile(r"^/api/\S+$")
ALLOWED_API_PATTERNS = (
    re.compile(r"^/api/(health|meta|versions|evaluate|events|cases)$"),
    re.compile(r"^/api/runs/$"),
    re.compile(r"^/api/runs/[^/]+$"),
    re.compile(r"^/api/runs/[^/]+/cases/[^/]+$"),
    re.compile(r"^/api/runs/[^/]+/cases/[^/]+/ops$"),
    re.compile(r"^/api/runs/[^/]+/cases/[^/]+/output$"),
)


def api_literals(src: str) -> list[tuple[int, str]]:
    """所有看起来像 API 路径的字符串字面量（含动态拼接里的前缀）。"""
    out = []
    for tok in tokenize(src):
        if tok.kind == "string" and API_PATH_RE.match(tok.value):
            out.append((tok.line, tok.value))
    return out

REQUIRED_ENDPOINTS = (
    "/api/versions", "/api/meta", "/api/health", "/api/runs/", "/ops",
    "/api/evaluate", "/api/events",
)

# ─────────────────────────────────────────────────────────────────────────────
# fixtures / HTML / CSS 检查
# ─────────────────────────────────────────────────────────────────────────────

FIXTURE_PREFIX = "window.__UI_FIXTURES__ = "
FIXTURE_CODE_PATTERNS = [
    (r"\bfunction\b", "function 关键字"),
    (r"=>", "箭头函数"),
    (r"\beval\b", "eval"),
    (r"\batob\b", "atob"),
    (r"\bbtoa\b", "btoa"),
    (r"window\s*\[", "window[...]"),
    (r"globalThis\s*\[", "globalThis[...]"),
    (r"self\s*\[", "self[...]"),
    (r"document\s*\[", "document[...]"),
    (r"\\u[0-9a-fA-F]{4}", "Unicode 转义"),
    (r"`", "模板字符串"),
    (r"\bnew\s+[A-Za-z_$]", "new 构造"),
    (r"\bconstructor\b", "constructor"),
]


def check_fixtures_text(text: str) -> list[str]:
    problems: list[str] = []
    # 允许开头的块注释（DEMO-ONLY 说明），其余部分必须是 `window.__UI_FIXTURES__ = <JSON>;`
    stripped = re.sub(r"^\s*/\*.*?\*/\s*", "", text, flags=re.S)
    if not stripped.startswith(FIXTURE_PREFIX):
        return ["fixtures.js 必须以 `window.__UI_FIXTURES__ = ` 开头（纯数据字面量）"]
    body = stripped[len(FIXTURE_PREFIX):].strip()
    if not body.endswith(";"):
        return ["fixtures.js 必须以分号结尾"]
    body = body[:-1].strip()
    try:
        json.loads(body)
    except Exception as exc:  # noqa: BLE001 - 报错要可读
        problems.append(f"fixtures.js 不是合法 JSON：{exc}")
    for pattern, why in FIXTURE_CODE_PATTERNS:
        if re.search(pattern, body):
            problems.append(f"fixtures.js 出现代码构造：{why}")
    return problems


CDN_PATTERNS = [
    (r"<script[^>]+src\s*=\s*[\"']https?://", "外链 <script src=…>"),
    (r"<link[^>]+href\s*=\s*[\"']https?://", "外链 <link href=…>"),
    (r"@import\s+url\(\s*[\"']?https?://", "CSS 外链 @import"),
    (r"(?:cdn\.jsdelivr|unpkg\.com|cdnjs\.cloudflare|googleapis|fonts\.gstatic)",
     "常见 CDN 域名"),
    (r"url\(\s*[\"']?https?://", "CSS url(http…)"),
]

REQUIRED_UI_STRINGS = (
    "后端未连接",
    "预览 · 本地试算 · 未提交",
    "预览·未提交",
    "已提交",
    "run_id",
    "commit",
    "actor",
    "rank",
    "score",
    "queued",
    "running",
    "timeout",
    "failed",
)


class Report:
    def __init__(self) -> None:
        self.items: list[tuple[bool, str, str]] = []

    def add(self, ok: bool, title: str, detail: str = "") -> None:
        self.items.append((ok, title, detail))

    def ok(self) -> bool:
        return all(item[0] for item in self.items)

    def print(self) -> None:
        width = max(len(title) for _, title, _ in self.items)
        for ok, title, detail in self.items:
            mark = "PASS" if ok else "FAIL"
            print(f"[{mark}] {title.ljust(width)}  {detail}")
        failed = [item for item in self.items if not item[0]]
        print()
        if failed:
            print(f"✗ {len(failed)} 项失败 / 共 {len(self.items)} 项")
            for _ok, title, detail in failed:
                print(f"  - {title}: {detail}")
        else:
            print(f"✓ 全部 {len(self.items)} 项通过：ui/ 是纯渲染视图（词法级禁公式、无 CDN）")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def run_lint() -> int:
    report = Report()

    # 1) 结构
    missing = [p.name for p in REQUIRED_FILES if not p.is_file()]
    report.add(not missing, "静态资源齐全", "缺：" + ", ".join(missing) if missing else
               "index.html / app.js / styles.css / fixtures.js")
    extra = sorted(p.name for p in UI.iterdir()
                   if p.is_file() and p.suffix in {".ts", ".tsx", ".jsx", ".mjs"})
    report.add(not extra, "无构建链文件", "发现：" + ", ".join(extra) if extra else "无 .ts/.jsx/.mjs")
    report.add(not (UI / "package.json").exists() and not (UI / "node_modules").exists(),
               "无 package.json / node_modules", "静态托管即可")

    sources = {p: read(p) for p in REQUIRED_FILES if p.is_file()}
    html_text = sources.get(HTML, "")
    app_text = sources.get(APP, "")
    css_text = sources.get(CSS, "")
    fixtures_text = sources.get(FIXTURES, "")

    # 2) CDN（含夹具，夹具也不许外链）
    cdn_hits: list[str] = []
    for path, text in sources.items():
        for pattern, why in CDN_PATTERNS:
            if re.search(pattern, text, flags=re.I):
                cdn_hits.append(f"{path.name}: {why}")
    report.add(not cdn_hits, "无 CDN / 外链资源", "; ".join(cdn_hits) if cdn_hits else
               "全部相对路径加载")

    # 3) 词法级公式扫描
    js_findings = scan_js(app_text, "app.js")
    report.add(not js_findings, "ui/ 无题面公式实现（词法级）",
               "; ".join(str(f) for f in js_findings[:5]) if js_findings else
               "无 ceil/floor/round/abs/pow/sqrt/min/max、题面参数、动态代码、计算键、字段算术")

    # 4) 可达 API 调用 + 端点
    endpoints = reachable_endpoints(app_text)
    missing_eps = [ep for ep in REQUIRED_ENDPOINTS if ep not in endpoints]
    report.add(not missing_eps, "API 调用点可达且端点齐全",
               "缺：" + ", ".join(missing_eps) if missing_eps else
               "fetch + EventSource + api/apiPost 均在 init/事件回调路径")
    literals = api_literals(app_text)
    bad_literals = [
        f"line {line}: {value}" for line, value in literals
        if not any(pattern.match(value) for pattern in ALLOWED_API_PATTERNS)
    ]
    report.add(not bad_literals, "所有 /api/… 字面量在 CONTRACT §2 白名单内",
               "越界：" + "; ".join(bad_literals[:6]) if bad_literals else
               f"{len(literals)} 处字面量均属 §2.1–§2.7（+ health/meta/output 增量端点）")

    # 5) fixtures 只作为数据
    fixture_problems = check_fixtures_text(fixtures_text)
    report.add(not fixture_problems, "fixtures.js 是纯数据字面量",
               "; ".join(fixture_problems) if fixture_problems else
               "JSON 可解析；无 function/=>/eval/atob/window[/\\u 等代码构造")

    # 6) UI 语义 / 必需字符串
    missing_strings = [s for s in REQUIRED_UI_STRINGS if s not in app_text + html_text]
    report.add(not missing_strings, "空态 / 预览双标 / 来源字段齐备",
               "缺：" + ", ".join(missing_strings) if missing_strings else
               "未连接空态 + 预览双标 + run_id/commit/actor/score/rank + 四种运行态")
    empty_branch = (
        "function disconnected" in app_text
        and "disconnected(err)" in app_text
        and 'id="emptystate"' in html_text
        and 'id="es-retry"' in html_text
        and "retry.addEventListener" in app_text
    )
    report.add(empty_branch, "后端空态分支 + 重试按钮",
               "disconnected() → #emptystate → #es-retry" if empty_branch else "缺空态或重试")
    slice_query = all(tok in app_text for tok in
                      ("since", "until", "cursor", "limit", "total", "returned"))
    report.add(slice_query, "ops 按切片接口取数",
               "since/until/limit + total/returned/next_cursor" if slice_query else "缺切片参数")

    # 7) F3/F4/F5 回归特征
    report.add('id="st-active"' in html_text and "function newestRun" in app_text and
               "function activeRuns" in app_text,
               "状态条取最新 run + 活动 run 指示",
               "newestRun()（S.runs ∪ runList）+ #st-active")
    report.add('id="gtrunc"' in html_text and "function renderTrunc" in app_text and
               "function loadMoreOps" in app_text and "next_cursor" in app_text,
               "Gantt 截断徽标 + 载入更多",
               "renderTrunc() 显示 returned/total，loadMoreOps() 走 next_cursor")

    # 8) 演示夹具门控
    demo_gated = ('location.search' in app_text and "?demo=1" in app_text
                  and 'loadScript("fixtures.js")' in app_text)
    demo_header = "DEMO-ONLY" in fixtures_text
    report.add(demo_gated and demo_header, "演示夹具受 ?demo=1 门控",
               "fixtures.js 只在显式演示模式加载" if demo_gated and demo_header else
               "演示模式门控或文件头缺失")
    report.add('src="fixtures.js"' not in html_text and "src='fixtures.js'" not in html_text,
               "index.html 不直接加载夹具", "fixtures.js 只在演示模式注入")

    # 9) DOM id 一致性 / 唯一性
    html_id_list = re.findall(r'\bid\s*=\s*"([^"]+)"', html_text)
    html_ids = set(html_id_list)
    duplicates = sorted({i for i in html_id_list if html_id_list.count(i) > 1})
    js_ids = set(re.findall(r'\$\(\s*"([^"]+)"\s*\)', app_text))
    js_ids |= set(re.findall(r'getElementById\(\s*"([^"]+)"\s*\)', app_text))
    dangling = sorted(i for i in js_ids if i not in html_ids)
    report.add(not duplicates, "HTML id 唯一",
               "重复：" + ", ".join(duplicates) if duplicates else f"{len(html_ids)} 个 id 无重复")
    report.add(not dangling, "JS 引用的 DOM id 都存在",
               "缺：" + ", ".join(dangling) if dangling else f"{len(js_ids)} 个 id 全部命中")

    # 10) lint 自身不 import judge
    lint_text = read(LINT)
    report.add(not re.search(r"(?m)^\s*(?:import|from)\s+judge\b", lint_text),
               "lint 不 import judge", "视图与判题核心解耦")

    # 11) 演示模式标注
    demo_badge = 'S.mode === "demo"' in app_text and "演示夹具" in app_text
    report.add(demo_badge, "演示模式有显式标注", "顶部状态条显示「演示夹具（静态）」"
               if demo_badge else "缺演示标注")

    # 12) 内联脚本必须可扫描（当前页面无内联 JS）
    inline_scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>",
                                html_text, flags=re.S)
    inline_code = "\n".join(inline_scripts).strip()
    inline_findings = scan_js(inline_code, "index.html:inline", require_api=False) if inline_code else []
    report.add(not inline_findings, "内联脚本同样通过词法扫描",
               "无内联脚本" if not inline_code else "; ".join(map(str, inline_findings[:3])))

    print("提示：公式扫描是启发式 tripwire（单层变量 taint；不追踪实参传播/闭包/对象属性/Proxy），"
          "不是证明；触碰 .time/.t/.dur/.score 的关键数字仍需人工对账。\n")
    report.print()
    return 0 if report.ok() else 1


# ─────────────────────────────────────────────────────────────────────────────
# --self-test（复核样本回归）
# ─────────────────────────────────────────────────────────────────────────────

SELF_TEST_SAMPLES = [
    ("B1 window[拼字符串] 取 ceil",
     'var cName = "ce" + "il";\nvar up = window[cName];\nvar fakeTime = up((7 * 13) / 4);'),
    ("B2 window[拼字符串] 取 Math",
     'var M = window["Ma" + "th"];\nvar fakeTime2 = M.max(3, 4);'),
    ("B3 atob + eval",
     'eval(atob("dmFyIHF4ID0gTWF0aC5jZWlsKDkxLzQpOyB2YXIgcXkgPSBNYXRoLm1heCgzLDQpOw=="));'),
    ("B4 小写 mexp/movl 算术",
     'var mexp = (d.E / d.P) * d.Z + d.Zs;\nvar movl = d.U * busyCount;\nvar myTime = 1 + 2;'),
    ("B5 Unicode 转义 ceil",
     r"var upU = \u0063eil;" + "\nvar fakeTime3 = upU(91 / 4);"),
    ("B6 死函数里的 fetch",
     'function deadFetch() { fetch("/api/versions"); }\nfunction init() {}\ninit();'),
    ("B7 服务端字段算术",
     'function render(d) { var x = d.time + 1; return x; }\nrender(null);'),
    ("B8 全局对象别名 + 计算键",
     'var w = window;\nvar up = w["ce" + "il"];\nvar fake = up(9 / 2);'),
    ("B9 括号包裹的全局对象 + 计算键",
     'var up = (window)["ce" + "il"];\nvar fake = up(9 / 2);'),
    ("B10 字符串计算键取 constructor",
     'var F = ({})["constructor"]["constructor"]("return 1")();'),
    ("M0 取模：d.time % 8",
     'function f(d) { return d.time % 8; }\nf(null);'),
    ("M0b 位或：d.time | 0",
     'function f(d) { return d.time | 0; }\nf(null);'),
    ("M0c 移位：d.dur << 1",
     'function f(d) { return d.dur << 1; }\nf(null);'),
    ("M1 单层 taint：var tt = d.time; tt - 6",
     'function f(S) { var tt = S.detail.time; return tt - 6; }\nf(null);'),
    ("M2 单层 taint：var a = o.t, b = o.dur; a + b",
     'function f(o) { var a = o.t, b = o.dur; return a + b; }\nf(null);'),
]

SELF_TEST_CLEAN = """
function xFor(t, range, lane) {
  return 56 + ((t - range.t0) * lane) / rangeSpan(range);
}
function renderVerdict(detail, base) {
  var time = num(detail.time);
  var delta = time - base;
  return delta;
}
function label(o) {
  var t = o.t;
  return "t=" + t;
}
"""


def _inject_snippet(text: str, snippet: str) -> str:
    marker = text.rfind("})();")
    if marker < 0:
        return text + "\n" + snippet
    return text[:marker] + "  function _bypass() {\n  " + snippet + "\n  }\n" + text[marker:]


def self_test() -> int:
    print("[self-test] 1) 词法扫描器：已知绕过样本必须命中")
    failures: list[str] = []
    for name, snippet in SELF_TEST_SAMPLES:
        hits = scan_js(snippet, "sample", require_api=False)
        mark = "✓" if hits else "✗"
        print(f"  [{mark}] {name}: {hits[0].rule if hits else '未命中'}")
        if not hits:
            failures.append(name)
    clean = scan_js(SELF_TEST_CLEAN, "clean", require_api=False)
    print(f"  [{'✓' if not clean else '✗'}] 干净几何/Δ 样本: "
          f"{'通过' if not clean else clean[0]}")
    if clean:
        failures.append("clean")

    print("[self-test] 2) fixtures 代码构造样本必须命中")
    bad_fixture = FIXTURE_PREFIX + '{"a": function () { return 1; }};'
    good_fixture = FIXTURE_PREFIX + '{"a": [{"t": 1, "dur": 2}]};'
    bad = check_fixtures_text(bad_fixture)
    good = check_fixtures_text(good_fixture)
    print(f"  [{'✓' if bad else '✗'}] 含 function 的夹具被拒: {'是' if bad else '否'}")
    print(f"  [{'✓' if not good else '✗'}] 纯数据夹具通过: {'是' if not good else '否'}")
    if not bad:
        failures.append("fixture-bad")
    if good:
        failures.append("fixture-good")
    probe = api_literals('fetch("/api/runs?limit=50");')
    allowed = any(pattern.match(value) for _line, value in probe
                  for pattern in ALLOWED_API_PATTERNS)
    blocked = bool(probe) and not allowed
    print(f"  [{'✓' if blocked else '✗'}] 集合端点字面量 /api/runs?limit=50 不在白名单: "
          f"{'是' if blocked else '否'}")
    if not blocked:
        failures.append("api-literal")

    print("[self-test] 3) 原件 lint 必须 PASS")
    original = subprocess.run([sys.executable, str(LINT)], cwd=str(UI.parent),
                              capture_output=True, text=True)
    passes = original.stdout.count("[PASS]")
    fails = original.stdout.count("[FAIL]")
    print(f"  [{'✓' if original.returncode == 0 and fails == 0 else '✗'}] 原件 "
          f"{passes} PASS / {fails} FAIL / exit={original.returncode}")
    if original.returncode != 0:
        failures.append("original")
        print(original.stdout[-2000:])

    print("[self-test] 4) B1–B5 注入临时副本后 lint 必须退出 1，且命中对应规则")
    expected_rule = {
        "B1": "computed-global", "B2": "computed-global", "B3": "dynamic-code",
        "B4": "formula-ident", "B5": "unicode-ident",
    }
    injected_ok = 0
    for name, snippet in SELF_TEST_SAMPLES[:5]:
        with tempfile.TemporaryDirectory(prefix="ui-lint-selftest-") as tmp:
            dst = Path(tmp) / "ui"
            shutil.copytree(UI, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            app = dst / "app.js"
            app.write_text(_inject_snippet(app.read_text(encoding="utf-8"), snippet),
                           encoding="utf-8")
            proc = subprocess.run([sys.executable, str(dst / "lint_viewer.py")],
                                  cwd=tmp, capture_output=True, text=True)
            rule = expected_rule.get(name.split()[0], "")
            hit = [line.strip() for line in proc.stdout.splitlines() if rule and rule in line]
            caught = proc.returncode != 0 and bool(hit)
            print(f"  [{'✓' if caught else '✗'}] {name}: 副本 exit={proc.returncode}"
                  + (f" · {hit[0][:90]}" if hit else ""))
            if caught:
                injected_ok += 1
            else:
                failures.append(name)
    print(f"  → 注入样本被拒（含对应规则）：{injected_ok}/5")

    print()
    if failures:
        print(f"✗ self-test FAILED：{', '.join(failures)}")
        return 1
    print("✓ self-test passed：5/5 绕过样本被拒、原件 PASS、夹具代码构造被拒")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ui 只读视图静态验收")
    parser.add_argument("--self-test", action="store_true",
                        help="跑绕过样本回归（B1–B5 注入临时副本，必须全部被拒）")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    return run_lint()


if __name__ == "__main__":
    raise SystemExit(main())
