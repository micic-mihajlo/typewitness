from __future__ import annotations

from contextvars import ContextVar
from typing import Dict

_EMPTY_COUNTERS: Dict[str, int] = {
    "chain_ref_lookups": 0,
    "line_scope_lookups": 0,
    "name_site_lookups": 0,
    "name_site_steps": 0,
    "span_token_visits": 0,
    "token_visits": 0,
}
_COUNTERS: ContextVar[Dict[str, int] | None] = ContextVar(
    "typewitness_instrumentation",
    default=None,
)


def record(operation: str, count: int = 1) -> None:
    counters = _COUNTERS.get()
    if counters is None:
        return
    updated = dict(counters)
    updated[operation] = updated.get(operation, 0) + count
    _COUNTERS.set(updated)


def reset() -> None:
    _COUNTERS.set(dict(_EMPTY_COUNTERS))


def disable() -> None:
    _COUNTERS.set(None)


def snapshot() -> Dict[str, int]:
    counters = _COUNTERS.get()
    if counters is None:
        return dict(_EMPTY_COUNTERS)
    return dict(counters)
