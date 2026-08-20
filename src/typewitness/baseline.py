from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

from typewitness.errors import BaselineError, FilesystemError
from typewitness.fingerprint import FINGERPRINT_SCHEMA

__all__ = (
    "BASELINE_SCHEMA",
    "FINGERPRINT_SCHEMA",
    "Baseline",
    "BaselineEntry",
    "apply_baseline",
    "load_baseline",
    "parse_baseline",
    "render_baseline",
    "write_baseline",
)
from typewitness.models import VALID_RULE_CODES, Finding

BASELINE_SCHEMA = "typewitness-baseline-1"
MAX_BASELINE_COUNT = 1_000_000
MAX_BASELINE_FILE_BYTES = 8_388_608
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{16}$")
_ENTRY_KEYS = frozenset({"fingerprint", "code", "path", "count"})


@dataclass(frozen=True)
class BaselineEntry:
    fingerprint: str
    code: str
    path: str
    count: int


@dataclass(frozen=True)
class Baseline:
    schema: str
    fingerprint_schema: str
    entries: dict[str, BaselineEntry]


def _validate_baseline_path(path: str) -> None:
    if not isinstance(path, str):
        raise BaselineError(f"invalid baseline path: {path!r}")
    if "\0" in path or path.startswith("/") or "\\" in path or ".." in path.split("/"):
        raise BaselineError(f"invalid baseline path: {path!r}")


def parse_baseline(text: str) -> Baseline:
    try:
        document = json.loads(text)
    except RecursionError as exc:
        raise BaselineError("malformed baseline file: excessive nesting") from exc
    except json.JSONDecodeError as exc:
        raise BaselineError(f"malformed baseline file: {exc}") from exc

    if not isinstance(document, dict):
        raise BaselineError("baseline file must contain a JSON object")

    for key in document:
        if key not in {"schema", "fingerprint_schema", "entries"}:
            raise BaselineError(f"unknown baseline key: {key!r}")

    schema = document.get("schema")
    if schema is not None and schema != BASELINE_SCHEMA:
        raise BaselineError(f"unsupported baseline schema: {schema!r}")

    for required in ("schema", "fingerprint_schema", "entries"):
        if required not in document:
            raise BaselineError(f"missing baseline key: {required!r}")

    schema = document["schema"]
    fingerprint_schema = document["fingerprint_schema"]
    entries_value = document["entries"]

    if schema != BASELINE_SCHEMA:
        raise BaselineError(f"unsupported baseline schema: {schema!r}")
    if fingerprint_schema != FINGERPRINT_SCHEMA:
        raise BaselineError(f"unsupported fingerprint schema: {fingerprint_schema!r}")
    if not isinstance(entries_value, list):
        raise BaselineError("baseline entries must be a list")

    entries: dict[str, BaselineEntry] = {}
    for raw_entry in entries_value:
        if not isinstance(raw_entry, dict):
            raise BaselineError("baseline entry must be an object")
        if set(raw_entry) != _ENTRY_KEYS:
            raise BaselineError("baseline entry has an invalid key set")
        fingerprint = raw_entry["fingerprint"]
        code = raw_entry["code"]
        path = raw_entry["path"]
        count = raw_entry["count"]
        if not isinstance(fingerprint, str) or not _FINGERPRINT_PATTERN.fullmatch(fingerprint):
            raise BaselineError(f"invalid fingerprint: {fingerprint!r}")
        if code not in VALID_RULE_CODES:
            raise BaselineError(f"unknown rule code in baseline entry: {code!r}")
        _validate_baseline_path(path)
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise BaselineError(f"invalid baseline count: {count!r}")
        if count > MAX_BASELINE_COUNT:
            raise BaselineError(f"baseline count exceeds maximum ({MAX_BASELINE_COUNT}): {count!r}")
        if fingerprint in entries:
            raise BaselineError(f"duplicate baseline entry for fingerprint: {fingerprint}")
        entries[fingerprint] = BaselineEntry(
            fingerprint=fingerprint,
            code=code,
            path=path,
            count=count,
        )

    return Baseline(schema=schema, fingerprint_schema=fingerprint_schema, entries=entries)


def _read_bounded_text(path: Path, max_bytes: int, *, label: str) -> str:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise FilesystemError(f"cannot read {label}: {path}") from exc
    if size > max_bytes:
        raise BaselineError(f"{label} exceeds maximum size ({max_bytes} bytes): {path}")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise FilesystemError(f"cannot read {label}: {path}") from exc
    if len(payload) > max_bytes:
        raise BaselineError(f"{label} exceeds maximum size ({max_bytes} bytes): {path}")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BaselineError(f"{label} is not valid UTF-8: {path}") from exc


def load_baseline(path: Path) -> Baseline:
    if path.is_symlink():
        raise FilesystemError(f"cannot read baseline file: {path}")
    return parse_baseline(_read_bounded_text(path, MAX_BASELINE_FILE_BYTES, label="baseline file"))


def render_baseline(findings: Sequence[Finding]) -> str:
    counts = Counter(finding.fingerprint for finding in findings)
    by_fingerprint: dict[str, Finding] = {}
    for finding in findings:
        by_fingerprint.setdefault(finding.fingerprint, finding)

    entries = []
    for fingerprint in sorted(counts):
        finding = by_fingerprint[fingerprint]
        entries.append(
            {
                "fingerprint": fingerprint,
                "code": finding.code,
                "path": finding.path.as_posix(),
                "count": counts[fingerprint],
            }
        )

    payload = {
        "schema": BASELINE_SCHEMA,
        "fingerprint_schema": FINGERPRINT_SCHEMA,
        "entries": entries,
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def apply_baseline(findings: Sequence[Finding], baseline: Baseline) -> Tuple[Finding, ...]:
    remaining = {fp: entry.count for fp, entry in baseline.entries.items()}
    kept: list[Finding] = []
    for finding in findings:
        budget = remaining.get(finding.fingerprint, 0)
        if budget > 0:
            remaining[finding.fingerprint] = budget - 1
        else:
            kept.append(finding)
    return tuple(kept)


def _fsync_directory(directory: Path) -> None:
    dir_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _validate_baseline_target(project_root: Path, target: Path) -> Path:
    if target.is_symlink():
        raise FilesystemError(f"cannot write baseline file: {target}")

    root = project_root.resolve()
    resolved_target = target.resolve()
    try:
        relative = resolved_target.relative_to(root)
    except ValueError as exc:
        raise FilesystemError(f"baseline path is outside project root: {target}") from exc
    if ".." in relative.parts:
        raise FilesystemError(f"baseline path is outside project root: {target}")

    current = resolved_target
    while True:
        if current.is_symlink():
            raise FilesystemError(f"cannot write baseline file: {target}")
        if current == root:
            break
        current = current.parent

    if resolved_target.exists() and not resolved_target.is_file():
        raise FilesystemError(f"cannot write baseline file: {target}")

    return resolved_target


def write_baseline(project_root: Path, target: Path, findings: Sequence[Finding]) -> None:
    resolved_target = _validate_baseline_target(project_root, target)
    parent = resolved_target.parent.resolve()
    if not parent.is_dir():
        raise FilesystemError(f"baseline directory does not exist: {parent}")

    rendered = render_baseline(findings)
    preserved_mode: Optional[int] = None
    if resolved_target.exists():
        preserved_mode = stat.S_IMODE(os.lstat(resolved_target).st_mode)

    temp_path: Path | None = None
    temp_fd: int | None = None
    try:
        temp_fd, temp_name = tempfile.mkstemp(
            prefix=f".{resolved_target.name}.",
            suffix=".tmp",
            dir=parent,
            text=False,
        )
        temp_path = Path(temp_name)
        if temp_path.is_symlink():
            raise FilesystemError(f"cannot write baseline file: {target}")
        if temp_path.parent.resolve() != parent:
            raise FilesystemError(f"cannot write baseline file: {target}")

        os.fchmod(temp_fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(temp_fd, "w", encoding="utf-8") as handle:
            temp_fd = None
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())

        if preserved_mode is not None:
            os.chmod(temp_path, preserved_mode)

        os.replace(temp_path, resolved_target)
        temp_path = None
        _fsync_directory(parent)
    except OSError as exc:
        raise FilesystemError(f"cannot write baseline file: {target}") from exc
    finally:
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass
