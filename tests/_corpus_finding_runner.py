from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from typewitness import SourceFile, analyze
from typewitness.models import Config

DEFAULT_RULESET = frozenset({"TW001", "TW002", "TW003"})


def _stdlib_root() -> Path:
    root = Path(sys.base_prefix) / "lib"
    version_dir = next(root.glob("python*"), None)
    if version_dir is None:
        raise RuntimeError("stdlib not found")
    return version_dir


def _relative_stdlib_paths(limit: int | None = None) -> list[str]:
    root = _stdlib_root()
    paths = sorted(path.relative_to(root).as_posix() for path in root.rglob("*.py"))
    if limit is None:
        return paths
    return paths[:limit]


def _file_digest(relpath: str) -> str | None:
    path = _stdlib_root() / relpath
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(data).hexdigest()


def _synthetic_corpus(count: int) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for index in range(count):
        if index % 5 == 0:
            text = "\n".join(
                [
                    "from typing import cast",
                    f"def f_{index}():",
                    f"    return cast(int, {index})",
                ]
            )
        elif index % 5 == 1:
            text = f"x_{index} = 1  # type: ignore[assignment]\n"
        elif index % 5 == 2:
            text = f"# SAFETY: ok reason\nz_{index} = 1  # type: ignore[arg-type]\n"
        elif index % 5 == 3:
            text = f'msg = "{{}}"  # braces in string\ny_{index} = {index}\n'
        else:
            text = f"value_{index} = {index!r}\n"
        items.append((f"synthetic/case_{index:04d}.py", text))
    return items


FindingTuple = tuple[str, int, int, str, str]


def _findings_for_source(relpath: str, path: Path, text: str) -> list[FindingTuple]:
    try:
        result = analyze(
            SourceFile(path=path, text=text),
            config=Config(select=DEFAULT_RULESET, ignore=frozenset()),
        )
    except Exception:
        return []
    if any(error.kind in ("parse", "encode") for error in result.errors):
        return []
    return [
        (
            relpath,
            finding.range.start.line,
            finding.range.start.column,
            finding.code,
            finding.fingerprint,
        )
        for finding in result.findings
    ]


def _finding_tuples_for_manifest(manifest: dict[str, object]) -> list[FindingTuple]:
    root = _stdlib_root()
    tuples: list[FindingTuple] = []
    stdlib_paths = manifest.get("stdlib", [])
    if isinstance(stdlib_paths, list):
        for relpath in stdlib_paths:
            if not isinstance(relpath, str):
                continue
            path = root / relpath
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            tuples.extend(_findings_for_source(relpath, path, text))
    synthetic = manifest.get("synthetic", [])
    if isinstance(synthetic, list):
        for entry in synthetic:
            if not isinstance(entry, list) or len(entry) != 2:
                continue
            relpath, text = entry
            if not isinstance(relpath, str) or not isinstance(text, str):
                continue
            tuples.extend(_findings_for_source(relpath, Path(relpath), text))
    return sorted(tuples)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "findings"
    if mode == "paths":
        print(json.dumps(_relative_stdlib_paths(None)))
    elif mode == "digests":
        relpaths = json.loads(sys.stdin.read())
        payload = {relpath: _file_digest(relpath) for relpath in relpaths}
        print(json.dumps(payload))
    elif mode == "manifest":
        manifest = json.loads(sys.stdin.read())
        print(json.dumps(_finding_tuples_for_manifest(manifest)))
    else:
        relpaths = _relative_stdlib_paths(int(mode))
        manifest = {"stdlib": relpaths, "synthetic": []}
        print(json.dumps(_finding_tuples_for_manifest(manifest)))
