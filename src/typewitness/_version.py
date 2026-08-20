from __future__ import annotations

try:
    from importlib.metadata import PackageNotFoundError, version
except ImportError:  # pragma: no cover - Python 3.7 fallback unused here
    from importlib_metadata import (  # type: ignore[no-redef,import-not-found]
        PackageNotFoundError,
        version,
    )


def tool_version() -> str:
    try:
        return version("typewitness")
    except PackageNotFoundError:
        return "0+unknown"
