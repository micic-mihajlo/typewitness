from __future__ import annotations

import os
import re
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, Mapping, Optional, Sequence, Tuple

from typewitness.discovery import (
    DEFAULT_MAX_FILE_BYTES,
    MAX_LINE_COUNT,
    _is_python_file,
    physical_line_numbers,
    read_source,
)
from typewitness.errors import GitError, UsageError
from typewitness.models import AnalysisError, Finding
from typewitness.project import Project

STAGED = "staged"
WORKTREE = "worktree"
DIFF_REF = "diff-ref"

_GIT_TIMEOUT_SECONDS = 60

_BLOCKED_GIT_ENV = frozenset(
    {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CEILING_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_DIFF_OPTS",
        "GIT_DIR",
        "GIT_EXTERNAL_DIFF",
        "GIT_INDEX_FILE",
        "GIT_NAMESPACE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_WORK_TREE",
    }
)

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_GIT_PATH = re.compile(r"^diff --git (?:\"?)(.+?)(?:\"?) (?:\"?)(.+?)(?:\"?)$")
_RENAME_FROM = re.compile(r"^rename from (.+)$")
_RENAME_TO = re.compile(r"^rename to (.+)$")


@dataclass(frozen=True)
class ChangedLinesResult:
    lines: Dict[str, FrozenSet[int]]
    errors: Tuple[AnalysisError, ...]


def _strip_ab_prefix(path: str) -> str:
    if len(path) >= 2 and path[0] in "ab" and path[1] == "/":
        return path[2:]
    return path


def _validate_diff_ref(ref: str) -> None:
    if not ref or "\0" in ref or ref.startswith("-"):
        raise UsageError(f"invalid git ref: {ref!r}")


@dataclass(frozen=True)
class GitSelection:
    mode: str
    ref: Optional[str] = None

    def __post_init__(self) -> None:
        if self.mode not in {STAGED, WORKTREE, DIFF_REF}:
            raise UsageError(f"unknown git selection mode: {self.mode!r}")
        if self.mode == DIFF_REF:
            if not self.ref:
                raise UsageError("--diff-ref requires a ref argument")
            _validate_diff_ref(self.ref)
        elif self.ref:
            raise UsageError(f"--{self.mode} does not accept a ref argument")


def diff_command(selection: GitSelection) -> Tuple[str, ...]:
    command: list[str] = [
        "diff",
        "--unified=0",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
    ]
    if selection.mode == STAGED:
        command.append("--cached")
    elif selection.mode == WORKTREE:
        command.extend(["--end-of-options", "HEAD"])
    elif selection.mode == DIFF_REF:
        assert selection.ref is not None
        command.extend(["--end-of-options", selection.ref, "--"])
    return tuple(command)


def _build_git_env(environ: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    source = dict(os.environ if environ is None else environ)
    cleaned: dict[str, str] = {}
    for key, value in source.items():
        if key.startswith("GIT_CONFIG"):
            continue
        if key in _BLOCKED_GIT_ENV:
            continue
        cleaned[key] = value
    cleaned["GIT_TERMINAL_PROMPT"] = "0"
    return cleaned


def run_git(root: Path, args: Sequence[str]) -> str:
    try:
        completed = subprocess.run(
            ("git", *args),
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            stdin=subprocess.DEVNULL,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=_build_git_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError("git command failed") from exc
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "git command failed"
        raise GitError(message)
    return completed.stdout


def _git_root(project: Project) -> Path:
    toplevel = run_git(project.root, ("rev-parse", "--show-toplevel")).strip()
    return Path(toplevel)


def _has_head(git_root: Path) -> bool:
    try:
        run_git(git_root, ("rev-parse", "--verify", "--quiet", "HEAD"))
    except GitError:
        return False
    return True


def _verify_diff_ref(git_root: Path, ref: str) -> None:
    run_git(git_root, ("rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}"))


def _parse_diff_git_new_path(line: str) -> Optional[str]:
    payload = line[len("diff --git ") :]
    if payload.startswith('"'):
        matches = re.findall(r'"((?:\\.|[^"\\])*)"', payload)
        if len(matches) >= 2:
            return _decode_git_path(_strip_ab_prefix(matches[1]))
        return None
    if payload.startswith("a/") and " b/" in payload:
        _old, new_part = payload.split(" b/", 1)
        return _decode_git_path(new_part)
    match = _GIT_PATH.match(line)
    if match:
        return _decode_git_path(_strip_ab_prefix(match.group(2)))
    return None


def parse_unified_diff(diff_text: str) -> Dict[str, FrozenSet[int]]:
    result: Dict[str, set[int]] = {}
    current_path: Optional[str] = None
    skip_hunks = False
    in_hunk = False
    old_remaining = 0
    new_remaining = 0
    new_line = 0

    def _finish_hunk() -> None:
        nonlocal in_hunk, old_remaining, new_remaining
        if not in_hunk:
            return
        if old_remaining > 0 or new_remaining > 0:
            raise GitError("truncated diff hunk")
        in_hunk = False
        old_remaining = 0
        new_remaining = 0

    def _start_hunk(line: str) -> None:
        nonlocal in_hunk, old_remaining, new_remaining, new_line
        match = _HUNK_HEADER.match(line)
        if not match:
            raise GitError(f"unrecognized diff hunk header: {line}")
        if current_path is None:
            if skip_hunks:
                return
            raise GitError("diff hunk without a preceding file header")
        old_count = int(match.group(2) or "1")
        new_count = int(match.group(4) or "1")
        if old_count < 0 or new_count < 0:
            raise GitError(f"invalid diff hunk counts: {line}")
        old_remaining = old_count
        new_remaining = new_count
        new_line = int(match.group(3))
        in_hunk = True

    def _consume_hunk_line(line: str) -> None:
        nonlocal old_remaining, new_remaining, new_line
        if current_path is None:
            raise GitError("diff hunk without a preceding file header")
        if line.startswith("\\ No newline at end of file"):
            return
        if line.startswith(" "):
            if old_remaining <= 0 or new_remaining <= 0:
                raise GitError("unexpected context line in diff hunk")
            new_line += 1
            old_remaining -= 1
            new_remaining -= 1
            return
        if line.startswith("-"):
            if old_remaining <= 0:
                raise GitError("unexpected removal line in diff hunk")
            old_remaining -= 1
            return
        if line.startswith("+"):
            if new_remaining <= 0:
                raise GitError("unexpected addition line in diff hunk")
            result[current_path].add(new_line)
            new_line += 1
            new_remaining -= 1
            return
        raise GitError(f"unexpected line in diff hunk: {line}")

    for raw_line in diff_text.splitlines():
        line = raw_line.rstrip("\n")

        if in_hunk:
            if line.startswith("@@"):
                _finish_hunk()
                _start_hunk(line)
                continue
            if line.startswith("diff --git "):
                _finish_hunk()
            elif line.startswith("\\ No newline at end of file") or line[:1] in {" ", "-", "+"}:
                _consume_hunk_line(line)
                continue
            else:
                _finish_hunk()

        if line.startswith("diff --git "):
            current_path = _parse_diff_git_new_path(line)
            skip_hunks = False
            if current_path is not None:
                result.setdefault(current_path, set())
            continue

        if line.startswith("rename from "):
            match = _RENAME_FROM.match(line)
            if match:
                current_path = None
            continue

        if line.startswith("rename to "):
            match = _RENAME_TO.match(line)
            if match:
                current_path = _decode_git_path(match.group(1))
                result.setdefault(current_path, set())
            continue

        if line.startswith("deleted file mode"):
            if current_path is not None:
                result.pop(current_path, None)
            current_path = None
            skip_hunks = True
            continue

        if line.startswith("new file mode"):
            continue

        if line.startswith("Binary files "):
            if current_path is not None:
                result.setdefault(current_path, set())
            continue

        if line.startswith("old mode ") or line.startswith("new mode "):
            if current_path is not None:
                result.setdefault(current_path, set())
            continue

        if line.startswith("similarity index"):
            continue

        if line.startswith("--- ") or line.startswith("+++ "):
            if line.startswith("+++ "):
                path_part = line[4:].strip()
                if path_part != "/dev/null":
                    if path_part.startswith('"') and path_part.endswith('"'):
                        current_path = _decode_git_path(path_part[1:-1])
                    else:
                        current_path = _decode_git_path(_strip_ab_prefix(path_part))
                    result.setdefault(current_path, set())
                    skip_hunks = False
            continue

        if line.startswith("@@"):
            _start_hunk(line)
            continue

        if current_path is None:
            continue

    _finish_hunk()

    return {path: frozenset(lines) for path, lines in sorted(result.items())}


def _decode_git_path(path: str) -> str:
    path = _strip_ab_prefix(path)
    if path.startswith('"') and path.endswith('"'):
        path = path[1:-1]

    out = bytearray()
    index = 0
    while index < len(path):
        char = path[index]
        if char == "\\" and index + 1 < len(path):
            nxt = path[index + 1]
            if "0" <= nxt <= "7":
                end = index + 1
                while end < len(path) and end < index + 4 and "0" <= path[end] <= "7":
                    end += 1
                out.append(int(path[index + 1 : end], 8))
                index = end
                continue
            if nxt == "n":
                out.append(ord("\n"))
                index += 2
                continue
            if nxt == "t":
                out.append(ord("\t"))
                index += 2
                continue
            if nxt == "r":
                out.append(ord("\r"))
                index += 2
                continue
            out.append(ord(nxt))
            index += 2
            continue
        out.extend(char.encode("utf-8"))
        index += 1
    try:
        return out.decode("utf-8", "surrogateescape")
    except UnicodeError as exc:
        raise GitError(f"malformed git path: {path!r}") from exc


def _list_untracked_paths(git_root: Path) -> Tuple[str, ...]:
    try:
        completed = subprocess.run(
            ("git", "ls-files", "--others", "--exclude-standard", "-z"),
            cwd=str(git_root),
            capture_output=True,
            text=False,
            check=False,
            shell=False,
            stdin=subprocess.DEVNULL,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=_build_git_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError("git command failed") from exc
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", "replace").strip()
        raise GitError(stderr or "git ls-files failed")

    if not completed.stdout:
        return ()

    parts = completed.stdout.split(b"\0")
    if parts and parts[-1] == b"":
        parts = parts[:-1]

    paths: list[str] = []
    for part in parts:
        if not part:
            raise GitError("git ls-files returned an empty path entry")
        try:
            paths.append(part.decode("utf-8", "surrogateescape"))
        except UnicodeError as exc:
            raise GitError("malformed untracked path from git") from exc
    return tuple(paths)


def _line_numbers_for_text(text: str) -> FrozenSet[int]:
    return physical_line_numbers(text)


def _project_relative(git_root: Path, project: Project, repo_path: str) -> Optional[str]:
    absolute = (git_root / repo_path).resolve()
    try:
        absolute.relative_to(project.root)
    except ValueError:
        return None
    return project.canonical(absolute)


def _normalize_path_nfc(path: str) -> str:
    return unicodedata.normalize("NFC", path)


def _changed_lines_lookup(changed: Mapping[str, FrozenSet[int]]) -> Dict[str, FrozenSet[int]]:
    by_nfc: Dict[str, FrozenSet[int]] = {}
    for path, lines in changed.items():
        nfc = _normalize_path_nfc(path)
        existing = by_nfc.get(nfc)
        if existing is not None:
            by_nfc[nfc] = frozenset(existing | lines)
        else:
            by_nfc[nfc] = lines

    lookup: Dict[str, FrozenSet[int]] = dict(by_nfc)
    for path in changed:
        lookup[path] = by_nfc[_normalize_path_nfc(path)]
    return lookup


def _store_changed_lines(
    filtered: Dict[str, FrozenSet[int]],
    canonical: str,
    lines: FrozenSet[int],
) -> None:
    nfc = _normalize_path_nfc(canonical)
    for existing_key in filtered:
        if _normalize_path_nfc(existing_key) == nfc:
            filtered[existing_key] = frozenset(filtered[existing_key] | lines)
            return
    if canonical in filtered:
        filtered[canonical] = frozenset(filtered[canonical] | lines)
    else:
        filtered[canonical] = lines


def filter_findings_to_changed_lines(
    findings: Sequence[Finding],
    changed: Mapping[str, FrozenSet[int]],
) -> Tuple[Finding, ...]:
    lookup = _changed_lines_lookup(changed)
    kept: list[Finding] = []
    for finding in findings:
        path = finding.path.as_posix()
        lines = lookup.get(path)
        if lines is None:
            lines = lookup.get(_normalize_path_nfc(path))
        if not lines:
            continue
        start = finding.range.start.line
        end = finding.range.end.line
        if any(line in lines for line in range(start, end + 1)):
            kept.append(finding)
    return tuple(kept)


def changed_lines(
    project: Project,
    selection: GitSelection,
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_line_count: int = MAX_LINE_COUNT,
) -> ChangedLinesResult:
    git_root = _git_root(project)
    errors: list[AnalysisError] = []

    if selection.mode == DIFF_REF:
        assert selection.ref is not None
        _verify_diff_ref(git_root, selection.ref)
        diff_text = run_git(git_root, diff_command(selection))
    elif selection.mode == STAGED:
        diff_text = run_git(git_root, diff_command(selection))
    elif selection.mode == WORKTREE and not _has_head(git_root):
        diff_text = ""
    else:
        diff_text = run_git(git_root, diff_command(selection))

    parsed = parse_unified_diff(diff_text)

    filtered: Dict[str, FrozenSet[int]] = {}
    for repo_path, lines in parsed.items():
        canonical = _project_relative(git_root, project, repo_path)
        if canonical is None:
            continue
        _store_changed_lines(filtered, canonical, lines)

    if selection.mode == WORKTREE:
        for repo_path in _list_untracked_paths(git_root):
            if not _is_python_file(Path(repo_path)):
                continue
            canonical = _project_relative(git_root, project, repo_path)
            if canonical is None:
                continue
            absolute = git_root / repo_path
            if not absolute.is_file() or absolute.is_symlink():
                continue
            read_result = read_source(
                project,
                absolute,
                max_file_bytes=max_file_bytes,
                max_line_count=max_line_count,
            )
            if read_result.error is not None:
                errors.append(read_result.error)
                continue
            assert read_result.source is not None
            _store_changed_lines(
                filtered,
                canonical,
                _line_numbers_for_text(read_result.source.text),
            )

    return ChangedLinesResult(lines=filtered, errors=tuple(errors))
