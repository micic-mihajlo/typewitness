from __future__ import annotations

import ast

from tests.conftest import analyze_source, finding_codes
from typewitness.candidates import build_candidates, build_parent_map
from typewitness.scopes import build_scope_tree
from typewitness.source_index import build_source_index, normalize_source_text


def test_flags_function_decorator_without_evidence() -> None:
    text = "\n".join(
        [
            "from typing import no_type_check",
            "@no_type_check",
            "def f():",
            "    return 1",
        ]
    )
    result = analyze_source(text)
    assert "TW008" in finding_codes(result)


def test_flags_async_function_decorator_without_evidence() -> None:
    text = "\n".join(
        [
            "from typing import no_type_check",
            "@no_type_check",
            "async def f():",
            "    return 1",
        ]
    )
    result = analyze_source(text)
    assert "TW008" in finding_codes(result)


def test_flags_class_decorator_without_evidence() -> None:
    text = "\n".join(
        [
            "from typing import no_type_check",
            "@no_type_check",
            "class C:",
            "    pass",
        ]
    )
    result = analyze_source(text)
    assert "TW008" in finding_codes(result)


def test_flags_qualified_decorator_without_evidence() -> None:
    text = "\n".join(
        [
            "import typing",
            "@typing.no_type_check",
            "def f():",
            "    pass",
        ]
    )
    result = analyze_source(text)
    assert "TW008" in finding_codes(result)


def test_allows_preceding_safety_comment() -> None:
    text = "\n".join(
        [
            "from typing import no_type_check",
            "# SAFETY: legacy untyped module",
            "@no_type_check",
            "def f():",
            "    return 1",
        ]
    )
    result = analyze_source(text)
    assert "TW008" not in finding_codes(result)


def test_allows_trailing_safety_on_decorator_line() -> None:
    text = "\n".join(
        [
            "from typing import no_type_check",
            "@no_type_check  # SAFETY: legacy untyped module",
            "def f():",
            "    return 1",
        ]
    )
    result = analyze_source(text)
    assert "TW008" not in finding_codes(result)


def test_allows_scoped_suppression() -> None:
    text = "\n".join(
        [
            "from typing import no_type_check",
            "@no_type_check  # SAFETY[TW008]: legacy untyped module",
            "def f():",
            "    return 1",
        ]
    )
    result = analyze_source(text)
    assert "TW008" not in finding_codes(result)


def test_ignores_decorator_call_form() -> None:
    text = "\n".join(
        [
            "from typing import no_type_check",
            "@no_type_check()",
            "def f():",
            "    return 1",
        ]
    )
    result = analyze_source(text)
    assert "TW008" not in finding_codes(result)


def test_ignores_shadowed_name() -> None:
    text = "\n".join(
        [
            "def no_type_check(fn):",
            "    return fn",
            "@no_type_check",
            "def f():",
            "    return 1",
        ]
    )
    result = analyze_source(text)
    assert "TW008" not in finding_codes(result)


def test_ignores_relative_import() -> None:
    text = "\n".join(
        [
            "from .typing import no_type_check",
            "@no_type_check",
            "def f():",
            "    return 1",
        ]
    )
    result = analyze_source(text)
    assert "TW008" not in finding_codes(result)


def test_ignores_unknown_decorator() -> None:
    text = "\n".join(
        [
            "@unknown",
            "def f():",
            "    return 1",
        ]
    )
    result = analyze_source(text, allow_errors=True)
    assert "TW008" not in finding_codes(result)


def test_resolves_typing_extensions_import() -> None:
    text = "\n".join(
        [
            "from typing_extensions import no_type_check",
            "@no_type_check",
            "def f():",
            "    return 1",
        ]
    )
    result = analyze_source(text)
    assert "TW008" in finding_codes(result)


def test_method_decorator_uses_class_scope_not_module() -> None:
    text = "\n".join(
        [
            "from typing import no_type_check",
            "class C:",
            "    @no_type_check",
            "    def m(self):",
            "        return 1",
        ]
    )
    normalized = normalize_source_text(text)
    tree = ast.parse(normalized)
    source_index = build_source_index(normalized)
    scope_tree = build_scope_tree(tree)
    candidates = build_candidates(tree, source_index, scope_tree, build_parent_map(tree))
    assert len(candidates.no_type_check_candidates) == 1
    candidate = candidates.no_type_check_candidates[0]
    assert candidate.scope_path == "class:C"
    assert candidate.candidate_norm == "no_type_check|function|m"


def test_nested_function_decorator_uses_outer_function_scope() -> None:
    text = "\n".join(
        [
            "from typing import no_type_check",
            "def outer():",
            "    @no_type_check",
            "    def inner():",
            "        return 1",
        ]
    )
    normalized = normalize_source_text(text)
    tree = ast.parse(normalized)
    source_index = build_source_index(normalized)
    scope_tree = build_scope_tree(tree)
    candidates = build_candidates(tree, source_index, scope_tree, build_parent_map(tree))
    assert len(candidates.no_type_check_candidates) == 1
    assert candidates.no_type_check_candidates[0].scope_path == "fn:outer"


def test_first_method_after_unrelated_statement_still_class_scoped() -> None:
    text = "\n".join(
        [
            "from typing import no_type_check",
            "class C:",
            "    x = 1",
            "    @no_type_check",
            "    def m(self):",
            "        return 1",
        ]
    )
    normalized = normalize_source_text(text)
    tree = ast.parse(normalized)
    source_index = build_source_index(normalized)
    scope_tree = build_scope_tree(tree)
    candidates = build_candidates(tree, source_index, scope_tree, build_parent_map(tree))
    assert len(candidates.no_type_check_candidates) == 1
    assert candidates.no_type_check_candidates[0].scope_path == "class:C"


def test_fingerprint_differs_for_separate_decorated_definitions() -> None:
    text = "\n".join(
        [
            "from typing import no_type_check",
            "@no_type_check",
            "def f():",
            "    return 1",
            "",
            "@no_type_check",
            "def g():",
            "    return 2",
        ]
    )
    findings = [f for f in analyze_source(text).findings if f.code == "TW008"]
    assert len(findings) == 2
    assert findings[0].fingerprint != findings[1].fingerprint


def test_fingerprint_stable_when_sibling_decorated_def_inserted() -> None:
    base = "\n".join(
        [
            "from typing import no_type_check",
            "@no_type_check",
            "def f():",
            "    return 1",
        ]
    )
    modified = "\n".join(
        [
            "from typing import no_type_check",
            "@no_type_check",
            "def g():",
            "    return 0",
            "",
            "@no_type_check",
            "def f():",
            "    return 1",
        ]
    )
    first = next(f for f in analyze_source(base).findings if f.code == "TW008")
    modified_findings = [f for f in analyze_source(modified).findings if f.code == "TW008"]
    f_decorator_line = (
        next(
            index
            for index, line in enumerate(normalize_source_text(modified).split("\n"), start=1)
            if line.strip() == "def f():"
        )
        - 1
    )
    second = next(f for f in modified_findings if f.range.start.line == f_decorator_line)
    assert first.fingerprint == second.fingerprint


def test_fingerprint_stable_across_body_edit() -> None:
    base = "\n".join(
        [
            "from typing import no_type_check",
            "@no_type_check",
            "def f():",
            "    return 1",
        ]
    )
    modified = "\n".join(
        [
            "from typing import no_type_check",
            "@no_type_check",
            "def f():",
            "    return 2",
            "    x = 3",
        ]
    )
    first = next(f for f in analyze_source(base).findings if f.code == "TW008")
    second = next(f for f in analyze_source(modified).findings if f.code == "TW008")
    assert first.fingerprint == second.fingerprint
