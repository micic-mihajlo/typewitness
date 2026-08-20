from __future__ import annotations

import ast

from tests.conftest import ALL_RULES, analyze_source, finding_codes
from typewitness.candidates import build_candidates, build_parent_map
from typewitness.scopes import build_scope_tree
from typewitness.source_index import build_source_index, normalize_source_text


def test_flags_patch_without_fidelity_keyword() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch('pkg.mod.target')",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" in finding_codes(result)


def test_flags_patch_object_without_fidelity_keyword() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch.object(object(), 'attr')",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" in finding_codes(result)


def test_ignores_when_autospec_present() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch('pkg.mod.target', autospec=False)",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" not in finding_codes(result)


def test_ignores_when_spec_present() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch('pkg.mod.target', spec=object)",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" not in finding_codes(result)


def test_ignores_when_spec_set_present() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch('pkg.mod.target', spec_set=object)",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" not in finding_codes(result)


def test_ignores_when_new_present() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch('pkg.mod.target', new=1)",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" not in finding_codes(result)


def test_ignores_when_positional_new_present() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch('pkg.mod.target', object())",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" not in finding_codes(result)


def test_ignores_when_positional_new_present_for_patch_object() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch.object(object(), 'attr', object())",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" not in finding_codes(result)


def test_ignores_when_new_callable_present() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch('pkg.mod.target', new_callable=list)",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" not in finding_codes(result)


def test_ignores_when_wraps_present() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch('pkg.mod.target', wraps=object())",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" not in finding_codes(result)


def test_ignores_kwargs_splat() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "kwargs = {}",
            "patch('pkg.mod.target', **kwargs)",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" not in finding_codes(result)


def test_ignores_patch_dict() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch.dict('pkg.mod', {'a': 1})",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" not in finding_codes(result)


def test_ignores_mock_construction() -> None:
    text = "\n".join(
        [
            "from unittest.mock import Mock",
            "Mock()",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" not in finding_codes(result)


def test_ignores_shadowed_patch() -> None:
    text = "\n".join(
        [
            "def patch(*args, **kwargs):",
            "    return None",
            "patch('pkg.mod.target')",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" not in finding_codes(result)


def test_resolves_unittest_mock_qualified_patch() -> None:
    text = "\n".join(
        [
            "import unittest.mock",
            "unittest.mock.patch('pkg.mod.target')",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" in finding_codes(result)


def test_resolves_unittest_mock_qualified_patch_object() -> None:
    text = "\n".join(
        [
            "import unittest",
            "unittest.mock.patch.object(object(), 'attr', object())",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" not in finding_codes(result)


def test_unittest_patch_stays_silent() -> None:
    text = "\n".join(
        [
            "import unittest",
            "unittest.patch('pkg.mod.target')",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" not in finding_codes(result)


def test_from_unittest_import_mock_still_resolves() -> None:
    text = "\n".join(
        [
            "from unittest import mock",
            "mock.patch('pkg.mod.target', object())",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" not in finding_codes(result)


def test_allows_unscoped_safety() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch('pkg.mod.target')  # SAFETY: legacy test double",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" not in finding_codes(result)


def test_allows_scoped_safety() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch('pkg.mod.target')  # SAFETY[TW012]: reviewed mock",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" not in finding_codes(result)


def test_not_enabled_by_default() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch('pkg.mod.target')",
        ]
    )
    result = analyze_source(text)
    assert "TW012" not in finding_codes(result)


def test_context_manager_form_is_body_insensitive() -> None:
    base = "\n".join(
        [
            "from unittest.mock import patch",
            "with patch('pkg.mod.target'):",
            "    x = 1",
        ]
    )
    modified = "\n".join(
        [
            "from unittest.mock import patch",
            "with patch('pkg.mod.target'):",
            "    x = 2",
            "    y = 3",
        ]
    )
    select = ALL_RULES | frozenset({"TW012"})
    first = next(f for f in analyze_source(base, select=select).findings if f.code == "TW012")
    second = next(f for f in analyze_source(modified, select=select).findings if f.code == "TW012")
    assert first.fingerprint == second.fingerprint


def test_mock_patch_candidate_shape() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch.object(object(), 'attr', spec=object)",
        ]
    )
    normalized = normalize_source_text(text)
    tree = ast.parse(normalized)
    source_index = build_source_index(normalized)
    scope_tree = build_scope_tree(tree)
    candidates = build_candidates(tree, source_index, scope_tree, build_parent_map(tree))
    assert len(candidates.mock_patch_candidates) == 1
    candidate = candidates.mock_patch_candidates[0]
    assert candidate.patch_form == "patch.object"
    assert candidate.has_fidelity_keyword is True
    assert candidate.candidate_norm == "patch.object|create=absent|fidelity=present|kwargs=absent"
