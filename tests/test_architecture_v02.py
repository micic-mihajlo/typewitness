from __future__ import annotations

import ast
import importlib
import importlib.util
import sys
from pathlib import Path
from typing import FrozenSet, Tuple

import pytest

from tests._integration_support import CAST_NO_EVIDENCE, CHAINED_CAST, analyze_text
from tests.conftest import ALL_RULES, DEFAULT_RULESET, analyze_source
from typewitness import catalog
from typewitness.candidates import (
    CastCandidate,
    CheckerDisableCandidate,
    NarrowingFunctionCandidate,
    NoTypeCheckCandidate,
    build_candidates,
    build_parent_map,
)
from typewitness.engine import analyze
from typewitness.models import (
    DEFAULT_RULESET as MODEL_DEFAULT_RULESET,
)
from typewitness.models import (
    VALID_RULE_CODES as MODEL_VALID_RULE_CODES,
)
from typewitness.models import (
    Config,
    SourceFile,
)
from typewitness.report import RULE_METADATA, Report, render_text
from typewitness.rules import RULES
from typewitness.scopes import ResolutionKind, ScopeTree, SymbolIdentity, build_scope_tree
from typewitness.source_index import build_source_index, normalize_source_text


def test_catalog_is_import_cycle_safe() -> None:
    for module_name in list(sys.modules):
        if module_name == "typewitness.catalog" or module_name.startswith("typewitness.catalog."):
            del sys.modules[module_name]
    loaded = importlib.import_module("typewitness.catalog")
    assert loaded.VALID_RULE_CODES == catalog.VALID_RULE_CODES
    assert loaded.DEFAULT_RULESET == catalog.DEFAULT_RULESET
    catalog_spec = importlib.util.find_spec("typewitness.catalog")
    assert catalog_spec is not None and catalog_spec.origin is not None
    source = Path(catalog_spec.origin).read_text(encoding="utf-8")
    assert "typewitness.rules" not in source


def test_catalog_derives_public_rule_sets() -> None:
    assert catalog.VALID_RULE_CODES == frozenset(
        {
            "TW001",
            "TW002",
            "TW003",
            "TW004",
            "TW005",
            "TW006",
            "TW007",
            "TW008",
            "TW009",
            "TW010",
            "TW011",
            "TW012",
            "TW013",
        }
    )
    assert catalog.DEFAULT_RULESET == frozenset(
        {"TW001", "TW002", "TW003", "TW005", "TW006", "TW007", "TW008", "TW009", "TW010"}
    )
    assert catalog.SUPPRESSIBLE_RULE_CODES == frozenset(
        {
            "TW002",
            "TW003",
            "TW004",
            "TW005",
            "TW006",
            "TW007",
            "TW008",
            "TW009",
            "TW010",
            "TW011",
            "TW012",
            "TW013",
        }
    )
    assert catalog.SCOPED_ONLY_SUPPRESSION_RULE_CODES == frozenset(
        {"TW004", "TW005", "TW006", "TW010", "TW011", "TW013"}
    )
    assert catalog.EFFECT_INDEX_RULE_CODES == frozenset({"TW004"})
    assert catalog.TYPEVAR_INDEX_RULE_CODES == frozenset({"TW013"})
    assert MODEL_VALID_RULE_CODES == catalog.VALID_RULE_CODES
    assert MODEL_DEFAULT_RULESET == catalog.DEFAULT_RULESET


def test_catalog_metadata_matches_reporter_output() -> None:
    assert set(RULE_METADATA) == catalog.VALID_RULE_CODES
    for descriptor in catalog.RULE_DESCRIPTORS:
        metadata = RULE_METADATA[descriptor.code]
        assert metadata.code == descriptor.code
        assert metadata.name == descriptor.name
        assert metadata.summary == descriptor.summary
        assert metadata.help_uri == descriptor.help_uri
        assert metadata.default_enabled is descriptor.default_enabled
        assert metadata.experimental is descriptor.experimental
        assert metadata.level == descriptor.level


def test_rule_registration_matches_catalog() -> None:
    catalog.validate_rule_registration(frozenset(rule.code for rule in RULES))
    for rule in RULES:
        descriptor = catalog.RULE_BY_CODE[rule.code]
        assert rule.name == descriptor.name


_LEGACY_FINDING_GOLDENS: dict[str, Tuple[Tuple[str, str, str, int, int], ...]] = {
    "cast_no_evidence": (("TW002", "cast call missing SAFETY evidence", "45fd0a4b3c314030", 3, 8),),
    "chained_cast": (
        ("TW001", "nested typing.cast call", "b29eb0e0892bb5a9", 3, 8),
        ("TW002", "cast call missing SAFETY evidence", "58b5d4fb724951dd", 3, 8),
    ),
    "type_ignore": (
        (
            "TW003",
            "type: ignore comment missing codes or SAFETY evidence",
            "a09e3fd61e518b78",
            1,
            7,
        ),
    ),
}


@pytest.mark.parametrize(
    ("fixture_name", "text", "select"),
    [
        ("cast_no_evidence", CAST_NO_EVIDENCE, ALL_RULES),
        ("chained_cast", CHAINED_CAST, ALL_RULES),
        (
            "type_ignore",
            "x = 1  # type: ignore[assignment]\n",
            DEFAULT_RULESET,
        ),
    ],
)
def test_legacy_findings_remain_byte_identical(
    fixture_name: str,
    text: str,
    select: FrozenSet[str],
) -> None:
    result = analyze(
        SourceFile(path=__import__("pathlib").Path("pkg/mod.py"), text=text),
        config=Config(select=select, ignore=frozenset()),
    )
    payload = tuple(
        (
            finding.code,
            finding.message,
            finding.fingerprint,
            finding.range.start.line,
            finding.range.start.column,
        )
        for finding in result.findings
    )
    if fixture_name == "type_ignore":
        assert payload == _LEGACY_FINDING_GOLDENS[fixture_name]
        return
    assert payload == _LEGACY_FINDING_GOLDENS[fixture_name]


def test_legacy_text_output_for_core_fixtures() -> None:
    cast_result = analyze_text("pkg/mod.py", CAST_NO_EVIDENCE, select=ALL_RULES)
    cast_report = Report(findings=cast_result.findings, errors=cast_result.errors)
    assert render_text(cast_report) == ("pkg/mod.py:3:9: TW002 cast call missing SAFETY evidence\n")

    chain_result = analyze_text("pkg/mod.py", CHAINED_CAST, select=ALL_RULES)
    chain_report = Report(findings=chain_result.findings, errors=chain_result.errors)
    assert render_text(chain_report) == (
        "pkg/mod.py:3:9: TW001 nested typing.cast call\n"
        "pkg/mod.py:3:9: TW002 cast call missing SAFETY evidence\n"
    )


def test_cast_candidate_enrichment_shape() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "cast(int, 1)",
            "x = cast(str, 'a')",
        ]
    )
    normalized = normalize_source_text(text)
    tree = ast.parse(normalized)
    parent_map = build_parent_map(tree)
    source_index = build_source_index(normalized)
    scope_tree = build_scope_tree(tree)
    candidates = build_candidates(tree, source_index, scope_tree, parent_map)

    assert len(candidates.cast_candidates) == 2
    standalone, assigned = candidates.cast_candidates
    assert isinstance(standalone.type_arg, ast.Name)
    assert standalone.type_arg.id == "int"
    assert isinstance(standalone.value_arg, ast.Constant)
    assert standalone.is_entire_expr_value is True
    assert isinstance(assigned.type_arg, ast.Name)
    assert assigned.type_arg.id == "str"
    assert isinstance(assigned.value_arg, ast.Constant)
    assert assigned.is_entire_expr_value is False

    for candidate in candidates.cast_candidates:
        assert isinstance(candidate, CastCandidate)
        assert candidate.candidate_norm
        assert candidate.host_norm


def test_checker_disable_candidate_shape() -> None:
    text = "\n".join(
        [
            "# mypy: ignore-errors",
            "import x",
        ]
    )
    normalized = normalize_source_text(text)
    tree = ast.parse(normalized)
    source_index = build_source_index(normalized)
    scope_tree = build_scope_tree(tree)
    candidates = build_candidates(tree, source_index, scope_tree, build_parent_map(tree))
    assert len(candidates.checker_disable_candidates) == 1
    candidate = candidates.checker_disable_candidates[0]
    assert isinstance(candidate, CheckerDisableCandidate)
    assert candidate.checker == "mypy"
    assert candidate.candidate_norm == "mypy:ignore-errors"
    assert candidate.host_norm == ""


def test_no_type_check_candidate_shape() -> None:
    text = "\n".join(
        [
            "from typing import no_type_check",
            "@no_type_check",
            "def f():",
            "    return 1",
        ]
    )
    normalized = normalize_source_text(text)
    tree = ast.parse(normalized)
    source_index = build_source_index(normalized)
    scope_tree = build_scope_tree(tree)
    candidates = build_candidates(tree, source_index, scope_tree, build_parent_map(tree))
    assert len(candidates.no_type_check_candidates) == 1
    candidate = candidates.no_type_check_candidates[0]
    assert isinstance(candidate, NoTypeCheckCandidate)
    assert candidate.target_kind == "function"
    assert candidate.candidate_norm == "no_type_check|function|f"
    assert candidate.scope_path == "module"


@pytest.mark.parametrize(
    ("text", "name", "expected"),
    [
        (
            "from typing import no_type_check\n",
            "no_type_check",
            SymbolIdentity.TYPING_NO_TYPE_CHECK,
        ),
        ("from typing import TypeGuard\n", "TypeGuard", SymbolIdentity.TYPING_TYPE_GUARD),
        ("from typing import TypeIs\n", "TypeIs", SymbolIdentity.TYPING_TYPE_IS),
        ("from typing import TypeVar\n", "TypeVar", SymbolIdentity.TYPING_TYPE_VAR),
        ("from typing import Any\n", "Any", SymbolIdentity.TYPING_ANY),
        ("from unittest.mock import patch\n", "patch", SymbolIdentity.MOCK_PATCH),
        ("import unittest.mock\n", "unittest", SymbolIdentity.UNITTEST_MODULE),
        ("import unittest.mock as mock\n", "mock", SymbolIdentity.MOCK_MODULE),
        ("from unittest import mock\n", "mock", SymbolIdentity.MOCK_MODULE),
        ("import json\n", "json", SymbolIdentity.JSON_MODULE),
        ("from json import loads\n", "loads", SymbolIdentity.JSON_LOADS),
        ("from json import load\n", "load", SymbolIdentity.JSON_LOAD),
        ("import pickle\n", "pickle", SymbolIdentity.PICKLE_MODULE),
        ("from pickle import loads\n", "loads", SymbolIdentity.PICKLE_LOADS),
        ("import marshal\n", "marshal", SymbolIdentity.MARSHAL_MODULE),
        ("from marshal import loads\n", "loads", SymbolIdentity.MARSHAL_LOADS),
        ("import plistlib\n", "plistlib", SymbolIdentity.PLISTLIB_MODULE),
        ("from plistlib import loads\n", "loads", SymbolIdentity.PLISTLIB_LOADS),
        ("import ast\n", "ast", SymbolIdentity.AST_MODULE),
        ("from ast import literal_eval\n", "literal_eval", SymbolIdentity.AST_LITERAL_EVAL),
    ],
)
def test_symbol_identity_positive_resolution(
    text: str,
    name: str,
    expected: SymbolIdentity,
) -> None:
    if "tomllib" in text:
        pytest.skip("tomllib fixture handled separately")
    normalized = normalize_source_text(text + f"{name}\n")
    tree = ast.parse(normalized)
    scope_tree = build_scope_tree(tree)
    use_line = 2
    resolved = scope_tree.resolve_symbol_identity(
        name,
        scope_tree.module_index,
        use_line,
        0,
    )
    assert resolved is expected


@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib requires Python 3.11+")
def test_symbol_identity_tomllib_positive_resolution() -> None:
    text = "import tomllib\nfrom tomllib import loads\n"
    normalized = normalize_source_text(text + "tomllib\nloads\n")
    tree = ast.parse(normalized)
    scope_tree = build_scope_tree(tree)
    assert (
        scope_tree.resolve_symbol_identity("tomllib", scope_tree.module_index, 3, 0)
        is SymbolIdentity.TOMLLIB_MODULE
    )
    assert (
        scope_tree.resolve_symbol_identity("loads", scope_tree.module_index, 3, 0)
        is SymbolIdentity.TOMLLIB_LOADS
    )


def test_symbol_identity_patch_object_positive_resolution() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch.object(object(), 'attr')",
        ]
    )
    normalized = normalize_source_text(text)
    tree = ast.parse(normalized)
    scope_tree = build_scope_tree(tree)
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call))
    assert (
        scope_tree.resolve_mock_patch_call(call, scope_tree.module_index)
        is SymbolIdentity.MOCK_PATCH_OBJECT
    )


def test_symbol_identity_unittest_mock_patch_chain() -> None:
    text = "\n".join(
        [
            "import unittest.mock",
            "unittest.mock.patch('pkg.mod.target')",
        ]
    )
    normalized = normalize_source_text(text)
    tree = ast.parse(normalized)
    scope_tree = build_scope_tree(tree)
    assert (
        scope_tree.resolve_symbol_identity(
            "unittest",
            scope_tree.module_index,
            2,
            0,
        )
        is SymbolIdentity.UNITTEST_MODULE
    )
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call))
    assert (
        scope_tree.resolve_mock_patch_call(call, scope_tree.module_index)
        is SymbolIdentity.MOCK_PATCH
    )


def test_symbol_identity_unittest_patch_stays_unknown() -> None:
    text = "\n".join(
        [
            "import unittest",
            "unittest.patch('pkg.mod.target')",
        ]
    )
    normalized = normalize_source_text(text)
    tree = ast.parse(normalized)
    scope_tree = build_scope_tree(tree)
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call))
    assert scope_tree.resolve_mock_patch_call(call, scope_tree.module_index) is None


def test_mock_patch_candidate_shape() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "with patch('pkg.mod.target', create=True):",
            "    x = 1",
        ]
    )
    normalized = normalize_source_text(text)
    tree = ast.parse(normalized)
    source_index = build_source_index(normalized)
    scope_tree = build_scope_tree(tree)
    candidates = build_candidates(tree, source_index, scope_tree, build_parent_map(tree))
    assert len(candidates.mock_patch_candidates) == 1
    candidate = candidates.mock_patch_candidates[0]
    assert candidate.patch_form == "patch"
    assert candidate.has_literal_create_true is True
    assert candidate.candidate_norm == "patch|create=true|fidelity=absent|kwargs=absent"
    assert candidate.host_norm


@pytest.mark.parametrize(
    ("text", "ambiguous_names"),
    [
        ("json = 1\nimport json\n", frozenset({"json"})),
        ("def f():\n    json = 1\n    import json\n", frozenset({"json"})),
        ("from json import loads\nfrom yaml import loads\n", frozenset({"loads"})),
        (
            "try:\n    from typing import Any\nexcept ImportError:\n    Any = object\n",
            frozenset({"Any"}),
        ),
        (
            "if True:\n    from typing import TypeVar\nelse:\n    TypeVar = int\n",
            frozenset({"TypeVar"}),
        ),
        ("from typing import *\nTypeVar = int\n", frozenset({"TypeVar"})),
        (
            "from mock import patch\nimport mock as patch\n",
            frozenset({"patch"}),
        ),
        ("from typing import TypeGuard\nTypeGuard = int\n", frozenset({"TypeGuard"})),
        ("def f():\n    global TypeGuard\n    TypeGuard = int\n", frozenset({"TypeGuard"})),
        (
            "\n".join(
                [
                    "def outer():",
                    "    TypeGuard = 1",
                    "    def inner():",
                    "        nonlocal TypeGuard",
                    "        TypeGuard = 2",
                ]
            ),
            frozenset({"TypeGuard"}),
        ),
    ],
)
def test_symbol_identity_adversarial_shadowing_returns_unknown(
    text: str,
    ambiguous_names: FrozenSet[str],
) -> None:
    normalized = normalize_source_text(text)
    tree = ast.parse(normalized)
    scope_tree = build_scope_tree(tree)
    use_line = max(getattr(node, "lineno", 1) for node in tree.body) + 1
    for name in ambiguous_names:
        resolved = scope_tree.resolve_symbol_identity(
            name,
            scope_tree.module_index,
            use_line,
            0,
        )
        assert resolved is SymbolIdentity.UNKNOWN, name


@pytest.mark.parametrize(
    ("text", "name", "expected"),
    [
        (
            "from typing import TypeGuard\nfrom typing import TypeGuard\n",
            "TypeGuard",
            SymbolIdentity.TYPING_TYPE_GUARD,
        ),
        (
            "from typing import Any\nfrom typing import Any as AnyAlias\n",
            "AnyAlias",
            SymbolIdentity.TYPING_ANY,
        ),
        (
            "from typing import no_type_check\nfrom typing import no_type_check\n",
            "no_type_check",
            SymbolIdentity.TYPING_NO_TYPE_CHECK,
        ),
        (
            "from unittest.mock import patch\nfrom unittest.mock import patch\n",
            "patch",
            SymbolIdentity.MOCK_PATCH,
        ),
        (
            "\n".join(
                [
                    "try:",
                    "    from typing import TypeGuard",
                    "except ImportError:",
                    "    from typing_extensions import TypeGuard",
                ]
            ),
            "TypeGuard",
            SymbolIdentity.TYPING_TYPE_GUARD,
        ),
        (
            "\n".join(
                [
                    "try:",
                    "    from typing import Any",
                    "except ImportError:",
                    "    from typing_extensions import Any",
                ]
            ),
            "Any",
            SymbolIdentity.TYPING_ANY,
        ),
    ],
)
def test_symbol_identity_duplicate_and_fallback_imports_remain_resolvable(
    text: str,
    name: str,
    expected: SymbolIdentity,
) -> None:
    normalized = normalize_source_text(text + f"\n{name}\n")
    tree = ast.parse(normalized)
    scope_tree = build_scope_tree(tree)
    use_line = max(getattr(node, "lineno", 1) for node in tree.body) + 1
    assert (
        scope_tree.resolve_symbol_identity(name, scope_tree.module_index, use_line, 0) is expected
    )


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("from .typing import Any\n", "Any"),
        ("from ..json import loads\n", "loads"),
        ("from .typing import cast\n", "cast"),
    ],
)
def test_symbol_identity_relative_imports_fail_closed(text: str, name: str) -> None:
    normalized = normalize_source_text(text + f"{name}\n")
    tree = ast.parse(normalized)
    scope_tree = build_scope_tree(tree)
    use_line = 3
    assert (
        scope_tree.resolve_symbol_identity(name, scope_tree.module_index, use_line, 0)
        is SymbolIdentity.UNKNOWN
    )


def test_relative_typing_import_preserves_legacy_resolution_kind() -> None:
    text = "from .typing import Any, cast\n"
    normalized = normalize_source_text(text)
    tree = ast.parse(normalized)
    scope_tree = build_scope_tree(tree)
    use_line = 2
    assert (
        scope_tree.resolve_name("Any", scope_tree.module_index, use_line, 0)
        is ResolutionKind.ANY_TYPE
    )
    assert (
        scope_tree.resolve_name("cast", scope_tree.module_index, use_line, 0)
        is ResolutionKind.CAST_FN
    )


def _inner_scope_use_line(scope_tree: ScopeTree, scope_index: int) -> int:
    sites = scope_tree.scopes[scope_index].binding_sites
    if sites:
        last = max(sites, key=lambda site: (site.line, site.column, site.site_id))
        return last.line + 1
    node = scope_tree.scopes[scope_index].node
    end_line = getattr(node, "end_lineno", None)
    if isinstance(end_line, int):
        return end_line
    start_line = getattr(node, "lineno", 1)
    return start_line if isinstance(start_line, int) else 1


def _assert_cross_scope_json_shadow_unknown(text: str, *, scope_kind: str) -> None:
    header = "import json\n"
    normalized = normalize_source_text(header + text)
    tree = ast.parse(normalized)
    scope_tree = build_scope_tree(tree)
    assert (
        scope_tree.resolve_symbol_identity("json", scope_tree.module_index, 2, 0)
        is SymbolIdentity.JSON_MODULE
    )
    scope_index = next(
        index for index, scope in enumerate(scope_tree.scopes) if scope.kind.value == scope_kind
    )
    use_line = _inner_scope_use_line(scope_tree, scope_index)
    assert (
        scope_tree.resolve_symbol_identity("json", scope_index, use_line, 0)
        is SymbolIdentity.UNKNOWN
    )


@pytest.mark.parametrize(
    ("body", "scope_kind"),
    [
        ("def f(json):\n    pass\n", "function"),
        ("def f():\n    json = 1\n", "function"),
        ("def f():\n    for json in []:\n        pass\n", "function"),
        (
            "def f():\n    try:\n        pass\n    except Exception as json:\n        pass\n",
            "function",
        ),
        ("def f():\n    if (json := 1):\n        pass\n", "function"),
        (
            "def f():\n    def json():\n        pass\n",
            "function",
        ),
        ("class C:\n    json = 1\n", "class"),
    ],
)
def test_symbol_identity_cross_scope_shadow_by_binding_form(
    body: str,
    scope_kind: str,
) -> None:
    _assert_cross_scope_json_shadow_unknown(body, scope_kind=scope_kind)


def test_symbol_identity_cross_scope_shadow_use_before_local_still_unknown() -> None:
    text = "\n".join(
        [
            "import json",
            "def f():",
            "    json",
            "    json = 1",
        ]
    )
    normalized = normalize_source_text(text)
    tree = ast.parse(normalized)
    scope_tree = build_scope_tree(tree)
    fn_scope = next(i for i, s in enumerate(scope_tree.scopes) if s.kind.value == "function")
    assert scope_tree.resolve_symbol_identity("json", fn_scope, 3, 0) is SymbolIdentity.UNKNOWN


def test_symbol_attribute_resolution_for_module_members() -> None:
    text = "import json\nimport ast\n"
    normalized = normalize_source_text(text)
    tree = ast.parse(normalized)
    scope_tree = build_scope_tree(tree)
    use_line = max(getattr(node, "lineno", 1) for node in tree.body) + 1
    assert (
        scope_tree.resolve_symbol_attribute(
            "json",
            "loads",
            scope_tree.module_index,
            use_line,
            0,
        )
        is SymbolIdentity.JSON_LOADS
    )
    assert (
        scope_tree.resolve_symbol_attribute(
            "ast",
            "literal_eval",
            scope_tree.module_index,
            use_line,
            0,
        )
        is SymbolIdentity.AST_LITERAL_EVAL
    )


def test_effect_index_is_requirement_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    from typewitness import engine
    from typewitness.effects import build_effect_index as original_build

    calls: list[str] = []

    def tracking_build(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append("built")
        return original_build(*args, **kwargs)

    monkeypatch.setattr(engine, "build_effect_index", tracking_build)

    analyze_source("x = 1\n", select=DEFAULT_RULESET)
    assert calls == []

    analyze_source("x = 1\n", select=ALL_RULES)
    assert calls == ["built"]


def test_narrowing_function_candidate_shape() -> None:
    text = "\n".join(
        [
            "from typing import TypeGuard",
            "def is_str(x: object) -> TypeGuard[str]:",
            "    return True",
        ]
    )
    normalized = normalize_source_text(text)
    tree = ast.parse(normalized)
    source_index = build_source_index(normalized)
    scope_tree = build_scope_tree(tree)
    candidates = build_candidates(tree, source_index, scope_tree, build_parent_map(tree))
    assert len(candidates.narrowing_function_candidates) == 1
    candidate = candidates.narrowing_function_candidates[0]
    assert isinstance(candidate, NarrowingFunctionCandidate)
    assert candidate.candidate_norm == "TypeGuard|function|is_str"
    assert candidate.host_norm


def test_typevar_index_is_requirement_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    from typewitness import engine
    from typewitness.typevars import build_typevar_index as original_build

    calls: list[str] = []

    def tracking_build(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append("built")
        return original_build(*args, **kwargs)

    monkeypatch.setattr(engine, "build_typevar_index", tracking_build)

    analyze_source("x = 1\n", select=DEFAULT_RULESET)
    assert calls == []

    analyze_source("x = 1\n", select=ALL_RULES | frozenset({"TW013"}))
    assert calls == ["built"]


def test_all_rules_fixture_reports_every_rule_code() -> None:
    from tests._corpus_finding_runner import ALL_RULES_FIXTURE_TEXT

    result = analyze_source(
        ALL_RULES_FIXTURE_TEXT,
        path="synthetic/all_rules_fixture.py",
        select=ALL_RULES,
    )
    codes = {finding.code for finding in result.findings}
    assert codes == set(ALL_RULES)
