from __future__ import annotations

import ast
import sys
import textwrap
from typing import Callable

import pytest

from tests.conftest import analyze_tw004, finding_codes
from typewitness.scopes import BindingForm, ScopeKind, ScopeTree, build_scope_tree
from typewitness.source_index import normalize_source_text


def _fn_scope_index(tree: ast.Module, scope_tree: ScopeTree, fn_name: str = "f") -> int:
    for index, scope in enumerate(scope_tree.scopes):
        if scope.kind == ScopeKind.FUNCTION and scope.name == fn_name:
            return index
    raise AssertionError(f"function scope {fn_name!r} not found")


def _forms(scope_tree: ScopeTree, scope_index: int, name: str) -> list[str]:
    return [site.binding_form for site in scope_tree.sites_for_name(scope_index, name)]


def test_effects_module_has_no_statement_walker() -> None:
    from pathlib import Path

    import typewitness.effects as effects_module

    source = Path(effects_module.__file__).read_text(encoding="utf-8")
    banned = (
        "isinstance(stmt",
        "_visit_stmt",
        "_apply_stmt",
        "_scan_function",
        "_stmt_children",
        "_written_names",
        "_target_names",
        "_all_arguments",
        "visit_module(",
    )
    for token in banned:
        assert token not in source


@pytest.mark.parametrize(
    ("snippet", "name", "expected_form", "scope_name"),
    [
        ("x = 1\n", "x", BindingForm.ASSIGN.value, "module"),
        ("x: int = 1\n", "x", BindingForm.ANN_ASSIGN.value, "module"),
        ("x += 1\n", "x", BindingForm.AUG_ASSIGN.value, "module"),
        ("del x\n", "x", BindingForm.DELETE.value, "module"),
        ("for x in []:\n    pass\n", "x", BindingForm.FOR.value, "module"),
        ("with open('/dev/null') as x:\n    pass\n", "x", BindingForm.WITH.value, "module"),
        (
            "try:\n    pass\nexcept Exception as x:\n    pass\n",
            "x",
            BindingForm.EXCEPT.value,
            "module",
        ),
        ("import os as x\n", "x", BindingForm.IMPORT.value, "module"),
        ("def x():\n    pass\n", "x", BindingForm.DEF.value, "module"),
        ("class x:\n    pass\n", "x", BindingForm.CLASS.value, "module"),
    ],
)
def test_binding_census_core_forms(
    snippet: str,
    name: str,
    expected_form: str,
    scope_name: str,
) -> None:
    tree = ast.parse(normalize_source_text(snippet))
    scope_tree = build_scope_tree(tree)
    if scope_name == "module":
        scope_index = scope_tree.module_index
    else:
        scope_index = _fn_scope_index(tree, scope_tree, scope_name)
    assert expected_form in _forms(scope_tree, scope_index, name)


def test_binding_census_tuple_and_star_targets() -> None:
    text = "def f():\n    a, *b = 1, 2, 3\n"
    tree = ast.parse(normalize_source_text(text))
    scope_tree = build_scope_tree(tree)
    fn_index = _fn_scope_index(tree, scope_tree)
    assert _forms(scope_tree, fn_index, "a") == [BindingForm.ASSIGN.value]
    assert _forms(scope_tree, fn_index, "b") == [BindingForm.ASSIGN.value]


@pytest.mark.parametrize(
    "body",
    [
        "assert (x := 1)",
        "if (x := 1): pass",
        "bool(1) and (x := 1)",
        "f(y=(x := 1))",
    ],
)
def test_binding_census_walrus_sites(body: str) -> None:
    text = f"def f():\n    {body}\n"
    tree = ast.parse(normalize_source_text(text))
    scope_tree = build_scope_tree(tree)
    fn_index = _fn_scope_index(tree, scope_tree)
    assert BindingForm.WALRUS.value in _forms(scope_tree, fn_index, "x")


def test_binding_census_walrus_in_comprehension_filter() -> None:
    text = "def f():\n    _ = [z for z in [1] if (x := z)]\n"
    tree = ast.parse(normalize_source_text(text))
    scope_tree = build_scope_tree(tree)
    fn_index = next(
        index for index, scope in enumerate(scope_tree.scopes) if scope.kind == ScopeKind.FUNCTION
    )
    assert BindingForm.WALRUS.value in _forms(scope_tree, fn_index, "x")


@pytest.mark.skipif(sys.version_info < (3, 11), reason="match requires 3.11+")
@pytest.mark.parametrize(
    ("body", "names"),
    [
        ("match x:\n    case [a, *rest]:\n        pass", ("a", "rest")),
        ("match x:\n    case {'k': v, **rest}:\n        pass", ("v", "rest")),
        ("match x:\n    case _ as name:\n        pass", ("name",)),
    ],
)
def test_binding_census_match_capture_sites(body: str, names: tuple[str, ...]) -> None:
    indented = textwrap.indent(body, "    ")
    text = f"def f(x):\n{indented}\n"
    tree = ast.parse(normalize_source_text(text))
    scope_tree = build_scope_tree(tree)
    fn_index = _fn_scope_index(tree, scope_tree)
    for name in names:
        assert BindingForm.MATCH.value in _forms(scope_tree, fn_index, name)


@pytest.mark.skipif(sys.version_info < (3, 12), reason="type alias requires 3.12+")
def test_binding_census_type_alias_site() -> None:
    text = "type Alias = int\n"
    tree = ast.parse(normalize_source_text(text))
    scope_tree = build_scope_tree(tree)
    assert BindingForm.ASSIGN.value in _forms(scope_tree, scope_tree.module_index, "Alias")


def test_binding_census_nonlocal_write_owned_by_outer_function() -> None:
    text = "\n".join(
        [
            "def f():",
            "    w = 1",
            "    def inner():",
            "        nonlocal w",
            "        w = 2",
        ]
    )
    tree = ast.parse(normalize_source_text(text))
    scope_tree = build_scope_tree(tree)
    fn_index = _fn_scope_index(tree, scope_tree)
    forms = _forms(scope_tree, fn_index, "w")
    assert BindingForm.ASSIGN.value in forms
    assert BindingForm.NONLOCAL_WRITE.value in forms


REBIND_CASES: list[tuple[str, Callable[[list[str]], bool]]] = [
    (
        "\n".join(
            [
                "from typing import Any, cast",
                "def f():",
                "    w: Any = [1]",
                "    for _ in []:",
                "        w = [2]",
                "    return cast(list[int], w)  # SAFETY: narrow list",
            ]
        ),
        lambda codes: "TW004" not in codes,
    ),
    (
        "\n".join(
            [
                "from typing import Any, cast",
                "def f():",
                "    w: Any = [1]",
                "    try:",
                "        w = [2]",
                "    except Exception:",
                "        pass",
                "    return cast(list[int], w)  # SAFETY: narrow list",
            ]
        ),
        lambda codes: "TW004" not in codes,
    ),
    (
        "\n".join(
            [
                "from typing import Any, cast",
                "def f():",
                "    w: Any = [1]",
                "    if True:",
                "        w = [2]",
                "    return cast(list[int], w)  # SAFETY: narrow list",
            ]
        ),
        lambda codes: "TW004" not in codes,
    ),
    (
        "\n".join(
            [
                "from typing import Any, cast",
                "def f():",
                "    w: Any = [1]",
                "    (w := [2])",
                "    return cast(list[int], w)  # SAFETY: narrow list",
            ]
        ),
        lambda codes: "TW004" not in codes,
    ),
    (
        "\n".join(
            [
                "from typing import Any, cast",
                "def f():",
                "    w: Any = [1]",
                "    assert (w := [2])",
                "    return cast(list[int], w)  # SAFETY: narrow list",
            ]
        ),
        lambda codes: "TW004" not in codes,
    ),
    (
        "\n".join(
            [
                "from typing import Any, cast",
                "def f():",
                "    w: Any = [1]",
                "    if (w := [2]):",
                "        pass",
                "    return cast(list[int], w)  # SAFETY: narrow list",
            ]
        ),
        lambda codes: "TW004" not in codes,
    ),
    (
        "\n".join(
            [
                "from typing import Any, cast",
                "def f():",
                "    w: Any = [1]",
                "    _ = f(x=(w := [2]))",
                "    return cast(list[int], w)  # SAFETY: narrow list",
            ]
        ),
        lambda codes: "TW004" not in codes,
    ),
    (
        "\n".join(
            [
                "from typing import Any, cast",
                "def f():",
                "    w: Any = [1]",
                "    _ = [z for z in [1] if (w := z)]",
                "    return cast(list[int], w)  # SAFETY: narrow list",
            ]
        ),
        lambda codes: "TW004" not in codes,
    ),
    (
        "\n".join(
            [
                "from typing import Any, cast",
                "def f():",
                "    w: Any = [1]",
                "    del w",
                "    w = [2]",
                "    return cast(list[int], w)  # SAFETY: narrow list",
            ]
        ),
        lambda codes: "TW004" not in codes,
    ),
    (
        "\n".join(
            [
                "from typing import Any, cast",
                "def f():",
                "    w: Any = [1]",
                "    def inner():",
                "        nonlocal w",
                "        w += [2]",
                "    return cast(list[int], w)  # SAFETY: narrow list",
            ]
        ),
        lambda codes: "TW004" not in codes,
    ),
]


@pytest.mark.parametrize("text,expect", REBIND_CASES, ids=[f"rebind-{i}" for i in range(10)])
def test_tw004_rebinding_regressions(text: str, expect: Callable[[list[str]], bool]) -> None:
    result = analyze_tw004(text)
    assert expect(finding_codes(result))


def test_tw004_site_order_requires_ann_assign_before_cast() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f():",
            "    return cast(list[int], w)  # SAFETY: narrow list",
            "    w: Any = [1]",
        ]
    )
    result = analyze_tw004(text)
    assert "TW004" not in finding_codes(result)


def test_tw004_alias_depth_limit() -> None:
    aliases = [f"a{i}" for i in range(10)]
    lines = ["from typing import Any, cast", "def f():"]
    lines.append("    a0 = [1]")
    for index in range(1, len(aliases)):
        lines.append(f"    {aliases[index]} = {aliases[index - 1]}")
    lines.append(f"    w: Any = {aliases[-1]}")
    lines.append("    return cast(list[int], w)  # SAFETY: narrow list")
    result = analyze_tw004("\n".join(lines) + "\n")
    assert "TW004" not in finding_codes(result)


def test_tw004_alias_depth_within_limit_flags() -> None:
    aliases = [f"a{i}" for i in range(7)]
    lines = ["from typing import Any, cast", "def f():"]
    lines.append("    a0 = [1]")
    for index in range(1, len(aliases)):
        lines.append(f"    {aliases[index]} = {aliases[index - 1]}")
    lines.append(f"    w: Any = {aliases[-1]}")
    lines.append("    return cast(list[int], w)  # SAFETY: narrow list")
    result = analyze_tw004("\n".join(lines) + "\n")
    assert "TW004" in finding_codes(result)
