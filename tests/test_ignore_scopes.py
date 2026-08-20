from __future__ import annotations

import ast

from typewitness.candidates import build_candidates
from typewitness.scopes import build_scope_tree
from typewitness.source_index import build_source_index, normalize_source_text


def _ignore_scope_paths(text: str) -> list[str]:
    normalized = normalize_source_text(text)
    tree = ast.parse(normalized)
    index = build_source_index(normalized)
    scope_tree = build_scope_tree(tree)
    candidates = build_candidates(tree, index, scope_tree)
    return [candidate.scope_path for candidate in candidates.ignore_candidates]


def test_ignore_scope_at_module() -> None:
    text = "x = 1  # type: ignore[assignment]\n"
    assert _ignore_scope_paths(text) == ["module"]


def test_ignore_scope_in_function() -> None:
    text = "\n".join(
        [
            "def f():",
            "    x = 1  # type: ignore[assignment]",
        ]
    )
    assert _ignore_scope_paths(text) == ["fn:f"]


def test_ignore_scope_in_nested_function() -> None:
    text = "\n".join(
        [
            "def outer():",
            "    def inner():",
            "        x = 1  # type: ignore[assignment]",
        ]
    )
    assert _ignore_scope_paths(text) == ["fn:outer@fn:inner"]


def test_ignore_scope_in_class_method() -> None:
    text = "\n".join(
        [
            "class C:",
            "    def m(self):",
            "        x = 1  # type: ignore[assignment]",
        ]
    )
    assert _ignore_scope_paths(text) == ["class:C@fn:m"]


def test_ignore_scope_in_class_body() -> None:
    text = "\n".join(
        [
            "class C:",
            "    x = 1  # type: ignore[assignment]",
        ]
    )
    assert _ignore_scope_paths(text) == ["class:C"]


def test_ignore_fingerprints_independent_under_sibling_reorder() -> None:
    from tests.conftest import analyze_source

    first = "\n".join(
        [
            "def f():",
            "    x = 1  # type: ignore[assignment]",
            "def g():",
            "    y = 2  # type: ignore[arg-type]",
        ]
    )
    second = "\n".join(
        [
            "def g():",
            "    y = 2  # type: ignore[arg-type]",
            "def f():",
            "    x = 1  # type: ignore[assignment]",
        ]
    )

    def tw003_fingerprints(text: str) -> set[str]:
        result = analyze_source(text)
        return {finding.fingerprint for finding in result.findings if finding.code == "TW003"}

    assert tw003_fingerprints(first) == tw003_fingerprints(second)
    assert len(tw003_fingerprints(first)) == 2
