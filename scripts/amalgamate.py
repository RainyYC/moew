#!/usr/bin/env python3
"""Expand the ordered multi-translation-unit source set into one submission."""
import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = (ROOT / "src").resolve()
MANIFEST = SRC_ROOT / "sources.mk"
INCLUDE_DIRECTIVE = re.compile(r'^\s*#\s*include\b(.*)$')
LOCAL_INCLUDE = re.compile(
    r'^\s*#\s*include\s+"([^"]+)"\s*'
    r'(?P<comment>//.*|/\*.*\*/\s*)?$'
)
SYSTEM_INCLUDE = re.compile(r'^\s*#\s*include\s*<[^>]+>\s*(?://.*|/\*.*\*/\s*)?$')


class IncludeError(RuntimeError):
    pass


def source_paths() -> list[Path]:
    text = MANIFEST.read_text()
    match = re.search(r"^SOLVER_SOURCES\s*:=\s*\\\n(?P<body>(?:.*\\\n)*.*)$", text, re.M)
    if not match:
        raise IncludeError("src/sources.mk has no readable SOLVER_SOURCES list")
    paths = []
    for item in match.group("body").splitlines():
        item = item.strip().removesuffix("\\").strip()
        if item:
            path = (ROOT / item).resolve()
            if not path.is_file():
                raise IncludeError(f"listed source does not exist: {item}")
            try:
                path.relative_to(SRC_ROOT)
            except ValueError as exc:
                raise IncludeError(f"source escapes src/: {item}") from exc
            paths.append(path)
    if not paths:
        raise IncludeError("source list is empty")
    return paths


def expand(path: Path, emitted: set[Path]) -> str:
    path = path.resolve()
    try:
        relative = path.relative_to(SRC_ROOT)
    except ValueError as exc:
        raise IncludeError(f"project include escapes src/: {path}") from exc
    if not path.is_file():
        raise IncludeError(f"project include does not exist or is not a file: {relative}")
    if path in emitted:
        return ""
    emitted.add(path)
    chunks = [f"// BEGIN MODULE: src/{relative.as_posix()}\n"]
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        match = LOCAL_INCLUDE.match(line)
        if match:
            child = (path.parent / match.group(1)).resolve()
            try:
                child.relative_to(SRC_ROOT)
            except ValueError as exc:
                raise IncludeError(
                    f"{relative}:{line_number}: include escapes src/: {match.group(1)}"
                ) from exc
            if not child.is_file():
                raise IncludeError(
                    f"{relative}:{line_number}: missing project include: {match.group(1)}"
                )
            chunks.append(expand(child, emitted))
            if match.group("comment"):
                chunks.append(match.group("comment").rstrip() + "\n")
        elif INCLUDE_DIRECTIVE.match(line):
            if SYSTEM_INCLUDE.match(line):
                chunks.append(line + "\n")
            elif re.match(r'^\s*#\s*include\s*"', line):
                raise IncludeError(
                    f"{relative}:{line_number}: unsupported or malformed local include: {line.strip()}"
                )
            else:
                raise IncludeError(
                    f"{relative}:{line_number}: unsupported include form: {line.strip()}"
                )
        elif line.strip() != "#pragma once":
            chunks.append(line + "\n")
    chunks.append(f"// END MODULE: src/{relative.as_posix()}\n")
    return "".join(chunks)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "submission/solver.cpp")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        emitted: set[Path] = set()
        chunks = []
        for source in source_paths():
            chunks.append(f"// BEGIN TRANSLATION UNIT: src/{source.relative_to(SRC_ROOT).as_posix()}\n")
            chunks.append(expand(source, emitted))
            chunks.append(f"// END TRANSLATION UNIT: src/{source.relative_to(SRC_ROOT).as_posix()}\n")
        content = "".join(chunks)
    except (IncludeError, OSError) as exc:
        parser.error(str(exc))
    if args.check:
        if not args.output.exists() or args.output.read_text() != content:
            print(f"stale amalgamated source: {args.output}")
            return 1
        print(f"amalgamated source is current: {args.output}")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
