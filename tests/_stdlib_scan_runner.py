from __future__ import annotations

import sys
from pathlib import Path

from typewitness import SourceFile, analyze
from typewitness.catalog import DEFAULT_RULESET
from typewitness.models import Config


def _stdlib_py_files(limit: int) -> list[Path]:
    root = Path(sys.base_prefix) / "lib"
    version_dir = next(root.glob("python*"), None)
    if version_dir is None:
        return []
    return sorted(version_dir.rglob("*.py"))[:limit]


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    files = _stdlib_py_files(limit)
    if len(files) < 100:
        print("0,0,0")
        return 0
    crashes = 0
    internals = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            result = analyze(
                SourceFile(path=path, text=text),
                config=Config(select=DEFAULT_RULESET, ignore=frozenset()),
            )
        except Exception:
            crashes += 1
            continue
        internals += sum(1 for error in result.errors if error.kind == "internal")
    print(f"{len(files)},{crashes},{internals}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
