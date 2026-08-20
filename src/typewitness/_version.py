from __future__ import annotations

from pathlib import Path
from typing import Optional

try:
    from importlib.metadata import PackageNotFoundError, version
except ImportError:  # pragma: no cover - Python 3.7 fallback unused here
    from importlib_metadata import (  # type: ignore[no-redef,import-not-found]
        PackageNotFoundError,
        version,
    )

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _checkout_version() -> Optional[str]:
    """Read ``[project].version`` without a TOML parser, for uninstalled source checkouts."""
    try:
        text = _PYPROJECT.read_text(encoding="utf-8")
    except OSError:
        return None
    table = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            table = line
            continue
        key, separator, value = line.partition("=")
        if table == "[project]" and separator and key.strip() == "version":
            return value.strip().strip("\"'") or None
    return None


def tool_version() -> str:
    try:
        return version("typewitness")
    except PackageNotFoundError:
        return _checkout_version() or "0+unknown"
