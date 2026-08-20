from __future__ import annotations

import ast
import sys

import pytest

from tests.conftest import DEFAULT_RULESET, analyze_source, analyze_tw004, finding_codes
from typewitness.scopes import BindingForm, ScopeKind, ScopeTree, build_scope_tree
from typewitness.source_index import normalize_source_text

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="TryStar requires Python 3.11+",
)


def _fn_scope(tree: ast.Module, scope_tree: ScopeTree, name: str = "f") -> int:
    for index, scope in enumerate(scope_tree.scopes):
        if scope.kind == ScopeKind.FUNCTION and scope.name == name:
            return index
    raise AssertionError(name)


def test_trystar_except_star_handler_in_function_scope() -> None:
    text = "\n".join(
        [
            "def f():",
            "    try:",
            "        pass",
            "    except* Exception as err:",
            "        err = 1",
        ]
    )
    tree = ast.parse(normalize_source_text(text))
    scope_tree = build_scope_tree(tree)
    fn_index = _fn_scope(tree, scope_tree)
    forms = [site.binding_form for site in scope_tree.sites_for_name(fn_index, "err")]
    assert BindingForm.EXCEPT_STAR.value in forms


def test_trystar_cast_in_body_resolves_with_import() -> None:
    text = "\n".join(
        [
            "def f():",
            "    from typing import cast",
            "    try:",
            "        x = 1",
            "    except* Exception:",
            "        pass",
            "    return cast(int, x)",
        ]
    )
    result = analyze_source(text, select=DEFAULT_RULESET)
    assert "TW002" in finding_codes(result)


def test_trystar_widen_invalidated_by_except_star_handler() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f():",
            "    w: Any = [1]",
            "    try:",
            "        pass",
            "    except* Exception as err:",
            "        _ = err",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_tw004(text)
    assert "TW004" in finding_codes(result)


def test_trystar_handler_rebind_invalidates_tw004() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f():",
            "    w: Any = [1]",
            "    try:",
            "        pass",
            "    except* Exception as w:",
            "        pass",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_tw004(text)
    assert "TW004" not in finding_codes(result)
