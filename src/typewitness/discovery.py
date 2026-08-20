from __future__ import annotations

import fnmatch
import io
import os
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, Optional, Sequence, Tuple

from typewitness.errors import FilesystemError
from typewitness.models import AnalysisError, SourceFile
from typewitness.project import Project

DEFAULT_EXCLUDES: Tuple[str, ...] = tuple(
    sorted(
        (
            ".git",
            ".mypy_cache",
            ".venv",
            "__pycache__",
            "build",
            "dist",
            "node_modules",
        )
    )
)

DEFAULT_MAX_FILE_BYTES = 1_048_576
MAX_MAX_FILE_BYTES = 4_194_304
MAX_LINE_COUNT = 100_000

_PYTHON_SUFFIXES = (".py", ".pyi")


@dataclass(frozen=True)
class ReadSourceResult:
    source: Optional[SourceFile]
    error: Optional[AnalysisError]


def discover_paths(
    project: Project,
    inputs: Sequence[Path | str],
    excludes: Sequence[str],
) -> Tuple[Path, ...]:
    effective_inputs = list(inputs) if inputs else [project.root]
    discovered: set[str] = set()
    ordered: list[Path] = []
    normalized_excludes = tuple(_normalize_exclude_pattern(pattern) for pattern in excludes)

    for raw in effective_inputs:
        absolute, is_symlink_input = _resolve_input(project, raw)
        if is_symlink_input:
            raise FilesystemError(f"symlink inputs are not supported: {raw}")
        if absolute.is_file():
            if _is_python_file(absolute):
                _add_path(
                    project,
                    absolute,
                    discovered,
                    ordered,
                    excludes=normalized_excludes,
                )
        elif absolute.is_dir():
            _walk_directory(project, absolute, discovered, ordered, normalized_excludes)
        else:
            raise FilesystemError(f"input path does not exist: {raw}")

    return tuple(ordered)


def _resolve_input(project: Project, raw: Path | str) -> Tuple[Path, bool]:
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    is_symlink_input = candidate.is_symlink()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(project.root)
    except ValueError as exc:
        raise FilesystemError(f"input path is outside the project root: {raw}") from exc
    return resolved, is_symlink_input


def _is_python_file(path: Path) -> bool:
    return path.suffix in _PYTHON_SUFFIXES


def _normalize_exclude_pattern(pattern: str) -> str:
    normalized = pattern.strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    while normalized.startswith("/"):
        normalized = normalized[1:]
    if len(normalized) > 1 and normalized.endswith("/"):
        normalized = normalized.rstrip("/")
    return normalized


def _is_excluded(canonical: str, excludes: Sequence[str]) -> bool:
    parts = canonical.split("/")
    for pattern in DEFAULT_EXCLUDES:
        if pattern in parts:
            return True
    for pattern in excludes:
        if "*" in pattern or "?" in pattern:
            if fnmatch.fnmatch(canonical, pattern):
                return True
            if fnmatch.fnmatch(canonical, f"{pattern}/*"):
                return True
        elif canonical == pattern or canonical.startswith(f"{pattern}/") or pattern in parts:
            return True
    return False


def _add_path(
    project: Project,
    absolute: Path,
    discovered: set[str],
    ordered: list[Path],
    *,
    excludes: Sequence[str],
) -> None:
    if absolute.is_symlink():
        return
    if not _is_python_file(absolute):
        return
    canonical = project.canonical(absolute)
    if _is_excluded(canonical, excludes):
        return
    if canonical not in discovered:
        discovered.add(canonical)
        ordered.append(absolute)


def _walk_directory(
    project: Project,
    directory: Path,
    discovered: set[str],
    ordered: list[Path],
    excludes: Sequence[str],
) -> None:
    try:
        entries = sorted(os.listdir(directory), key=lambda name: name)
    except OSError as exc:
        raise FilesystemError(f"cannot read directory: {directory}") from exc

    for name in entries:
        child = directory / name
        if child.is_symlink():
            continue
        if child.is_dir():
            canonical_dir = project.canonical(child)
            if _is_excluded(canonical_dir, excludes):
                continue
            if name in DEFAULT_EXCLUDES:
                continue
            _walk_directory(project, child, discovered, ordered, excludes)
        elif child.is_file():
            _add_path(project, child, discovered, ordered, excludes=excludes)


def physical_line_count(text: str) -> int:
    """Count lines using newline semantics only (LF, CRLF, CR).

    Unlike ``str.splitlines``, form feed, vertical tab, NEL, and Unicode line
    separators do not start a new physical line.
    """
    if not text:
        return 0
    count = 0
    index = 0
    length = len(text)
    while index < length:
        count += 1
        while index < length and text[index] not in "\n\r":
            index += 1
        if index >= length:
            break
        if text[index] == "\r" and index + 1 < length and text[index + 1] == "\n":
            index += 2
        else:
            index += 1
    return count


def physical_line_numbers(text: str) -> FrozenSet[int]:
    count = physical_line_count(text)
    if count == 0:
        return frozenset()
    return frozenset(range(1, count + 1))


def is_path_excluded(canonical: str, excludes: Sequence[str]) -> bool:
    normalized = tuple(_normalize_exclude_pattern(pattern) for pattern in excludes)
    return _is_excluded(canonical, normalized)


def read_source(
    project: Project,
    path: Path | str,
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_line_count: int = MAX_LINE_COUNT,
) -> ReadSourceResult:
    if max_file_bytes < 1:
        raise FilesystemError("max-file-bytes must be a positive integer")
    if max_line_count < 1:
        raise FilesystemError("max line count must be a positive integer")

    absolute, is_symlink_input = _resolve_input(project, path)
    if is_symlink_input:
        raise FilesystemError(f"symlink inputs are not supported: {path}")
    if not absolute.is_file():
        raise FilesystemError(f"source file does not exist: {path}")

    canonical = project.canonical(absolute)
    relative_path = Path(canonical)

    try:
        size = absolute.stat().st_size
    except OSError as exc:
        raise FilesystemError(f"cannot read source file: {path}") from exc

    if size > max_file_bytes:
        return ReadSourceResult(
            source=None,
            error=AnalysisError(
                kind="limit",
                path=relative_path,
                message=f"source file exceeds max-file-bytes ({max_file_bytes}): {canonical}",
            ),
        )

    try:
        with open(absolute, "rb") as handle:
            payload = handle.read(max_file_bytes + 1)
    except OSError as exc:
        raise FilesystemError(f"cannot read source file: {path}") from exc

    if len(payload) > max_file_bytes:
        return ReadSourceResult(
            source=None,
            error=AnalysisError(
                kind="limit",
                path=relative_path,
                message=f"source file exceeds max-file-bytes ({max_file_bytes}): {canonical}",
            ),
        )

    try:
        encoding = tokenize.detect_encoding(io.BytesIO(payload).readline)[0]
        text = payload.decode(encoding)
    except SyntaxError as exc:
        return ReadSourceResult(
            source=None,
            error=AnalysisError(kind="encode", path=relative_path, message=str(exc)),
        )
    except UnicodeDecodeError as exc:
        return ReadSourceResult(
            source=None,
            error=AnalysisError(kind="encode", path=relative_path, message=str(exc)),
        )
    except LookupError as exc:
        return ReadSourceResult(
            source=None,
            error=AnalysisError(kind="encode", path=relative_path, message=str(exc)),
        )

    line_count = physical_line_count(text)
    if line_count > max_line_count:
        return ReadSourceResult(
            source=None,
            error=AnalysisError(
                kind="limit",
                path=relative_path,
                message=f"source file exceeds maximum line count ({max_line_count}): {canonical}",
            ),
        )

    return ReadSourceResult(
        source=SourceFile(path=relative_path, text=text, encoding=encoding),
        error=None,
    )
