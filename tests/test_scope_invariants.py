from __future__ import annotations

import ast
import sys
import textwrap

import pytest

from tests.conftest import DEFAULT_RULESET, analyze_source, finding_codes
from typewitness.scopes import build_scope_tree
from typewitness.source_index import normalize_source_text

MATCH_SKIP = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="match statement requires Python 3.11+",
)


def _semantic_expr_nodes(tree: ast.AST) -> list[ast.AST]:
    nodes: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.expr):
            nodes.append(node)
        elif isinstance(node, ast.comprehension):
            nodes.append(node)
    return nodes


@MATCH_SKIP
def test_every_semantic_expr_has_exactly_one_scope_assignment() -> None:
    text = """
from typing import cast
import typing as t

def f(x):
    w = cast(int, x)
    return [cast(int, y) for y in (lambda z: cast(str, z))(w)]

class C:
    def m(self):
        return cast(int, 1)

def g():
    match x:
        case [a, *rest]:
            return cast(int, a)
        case {'k': v}:
            return cast(int, v)
        case 1 | 2:
            return cast(int, x)
"""
    tree = ast.parse(normalize_source_text(text))
    scope_tree = build_scope_tree(tree)
    for node in _semantic_expr_nodes(tree):
        assert id(node) in scope_tree.node_scope, ast.dump(node)


def test_comprehension_cast_callee_shadow_without_safety() -> None:
    text = "from typing import cast\n[x for cast in 'ab' if cast(int, x)]\n"
    result = analyze_source(text, select=DEFAULT_RULESET)
    assert "TW002" not in finding_codes(result)


def test_lambda_cast_callee_shadow_without_safety() -> None:
    text = "from typing import cast\n(lambda cast: cast(int, 1))(cast)\n"
    result = analyze_source(text, select=DEFAULT_RULESET)
    assert "TW002" not in finding_codes(result)


def test_cast_value_name_shadow_without_safety() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "def f():",
            "    cast = '1'",
            "    return cast(int, cast)",
        ]
    )
    result = analyze_source(text, select=DEFAULT_RULESET)
    assert "TW002" not in finding_codes(result)


def test_use_before_local_import_is_opaque() -> None:
    text = "\n".join(
        [
            "def f():",
            "    x = cast(int, 1)",
            "    from typing import cast",
        ]
    )
    result = analyze_source(text, select=DEFAULT_RULESET)
    assert "TW002" not in finding_codes(result)


def test_conditional_import_resolves_cast() -> None:
    text = "\n".join(
        [
            "def f():",
            "    if True:",
            "        from typing import cast",
            "    return cast(int, 1)",
        ]
    )
    result = analyze_source(text, select=DEFAULT_RULESET)
    assert "TW002" in finding_codes(result)


def test_try_import_fallback_resolves_cast() -> None:
    text = "\n".join(
        [
            "def f():",
            "    try:",
            "        from typing import cast",
            "    except ImportError:",
            "        pass",
            "    return cast(int, 1)",
        ]
    )
    result = analyze_source(text, select=DEFAULT_RULESET)
    assert "TW002" in finding_codes(result)


def test_mixed_kind_conditional_import_remains_opaque() -> None:
    text = "\n".join(
        [
            "def f():",
            "    if True:",
            "        from typing import cast",
            "    else:",
            "        def cast():",
            "            pass",
            "    return cast(int, 1)",
        ]
    )
    result = analyze_source(text, select=DEFAULT_RULESET)
    assert "TW002" not in finding_codes(result)


def test_local_import_after_use_then_valid() -> None:
    text = "\n".join(
        [
            "def f():",
            "    from typing import cast",
            "    return cast(int, 1)",
        ]
    )
    result = analyze_source(text, select=DEFAULT_RULESET)
    assert "TW002" in finding_codes(result)


def test_module_alias_cast_after_import() -> None:
    text = "\n".join(
        [
            "import typing as t",
            "x = t.cast(int, t.cast(str, '1'))  # SAFETY: chain cast",
        ]
    )
    result = analyze_source(text, select=DEFAULT_RULESET)
    assert "TW001" in finding_codes(result)
    assert "TW002" not in finding_codes(result)


def test_any_import_position_aware() -> None:
    text = "\n".join(
        [
            "def f():",
            "    w: Any = 1",
            "    from typing import Any",
        ]
    )
    result = analyze_source(text, select=frozenset({"TW004"}))
    assert "TW004" not in finding_codes(result)


@MATCH_SKIP
def test_default_ruleset_analyzes_match_without_effect_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typewitness import engine

    def fail_build(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("EffectIndex must not be built for default ruleset")

    monkeypatch.setattr(engine, "build_effect_index", fail_build)
    text = """
def f(x):
    match x:
        case [a, *rest]:
            return a
"""
    result = analyze_source(text, select=DEFAULT_RULESET)
    assert result.errors == ()


@MATCH_SKIP
@pytest.mark.parametrize(
    "body",
    [
        "match x:\n    case [a, *rest]:\n        return a",
        "match x:\n    case {'k': v, **rest}:\n        return v",
        "match x:\n    case 1 | 2:\n        return x",
        "match x:\n    case _ as name:\n        return name",
        "match x:\n    case int():\n        return x",
    ],
)
def test_match_patterns_analyze_without_error(body: str) -> None:
    indented_body = textwrap.indent(body, "    ")
    text = f"def f(x):\n{indented_body}\n"
    result = analyze_source(text, select=DEFAULT_RULESET)
    assert result.errors == ()
