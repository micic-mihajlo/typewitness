from __future__ import annotations

import pytest

from tests.conftest import DEFAULT_RULESET, analyze_source


def test_index_build_failure_returns_internal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typewitness import engine

    def boom(tree):  # type: ignore[no-untyped-def]
        raise RuntimeError("scope build failed")

    monkeypatch.setattr(engine, "build_scope_tree", boom)
    result = analyze_source("x = 1\n", select=DEFAULT_RULESET, allow_errors=True)
    assert result.findings == ()
    assert len(result.errors) == 1
    assert result.errors[0].kind == "internal"


def test_analyze_never_raises_on_valid_source() -> None:
    result = analyze_source("from typing import cast\ncast(int, 1)\n", select=DEFAULT_RULESET)
    assert result.errors == ()


def test_analyze_never_raises_on_malformed_source() -> None:
    result = analyze_source("def f(:\n", select=DEFAULT_RULESET, allow_errors=True)
    assert result.errors[0].kind == "parse"


def test_recursion_error_returns_limit_not_internal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typewitness import engine

    def recurse(_tree):  # type: ignore[no-untyped-def]
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(engine, "build_scope_tree", recurse)
    result = analyze_source("x = 1\n", select=DEFAULT_RULESET, allow_errors=True)
    assert result.findings == ()
    assert len(result.errors) == 1
    assert result.errors[0].kind == "limit"
