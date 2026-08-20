from __future__ import annotations

import ast

from tests.conftest import ALL_RULES, analyze_source, finding_codes
from typewitness.candidates import build_candidates, build_parent_map
from typewitness.scopes import build_scope_tree
from typewitness.source_index import build_source_index, normalize_source_text


def test_flags_patch_with_literal_create_true() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch('pkg.mod.target', create=True)",
        ]
    )
    result = analyze_source(text)
    assert "TW009" in finding_codes(result)


def test_flags_patch_object_with_literal_create_true() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch.object(object(), 'attr', create=True)",
        ]
    )
    result = analyze_source(text)
    assert "TW009" in finding_codes(result)


def test_flags_qualified_mock_patch() -> None:
    text = "\n".join(
        [
            "import unittest.mock as mock",
            "mock.patch('pkg.mod.target', create=True)",
        ]
    )
    result = analyze_source(text)
    assert "TW009" in finding_codes(result)


def test_allows_unscoped_safety() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch('pkg.mod.target', create=True)  # SAFETY: attribute may not exist yet",
        ]
    )
    result = analyze_source(text)
    assert "TW009" not in finding_codes(result)


def test_allows_scoped_safety() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch('pkg.mod.target', create=True)  # SAFETY[TW009]: lazy attribute",
        ]
    )
    result = analyze_source(text)
    assert "TW009" not in finding_codes(result)


def test_ignores_create_false() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch('pkg.mod.target', create=False)",
        ]
    )
    result = analyze_source(text)
    assert "TW009" not in finding_codes(result)


def test_ignores_non_literal_create() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "flag = True",
            "patch('pkg.mod.target', create=flag)",
        ]
    )
    result = analyze_source(text)
    assert "TW009" not in finding_codes(result)


def test_ignores_patch_dict() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch.dict('pkg.mod', {'a': 1}, create=True)",
        ]
    )
    result = analyze_source(text)
    assert "TW009" not in finding_codes(result)


def test_ignores_patch_multiple() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch.multiple('pkg.mod', a=1, create=True)",
        ]
    )
    result = analyze_source(text)
    assert "TW009" not in finding_codes(result)


def test_ignores_shadowed_patch_name() -> None:
    text = "\n".join(
        [
            "def patch(*args, **kwargs):",
            "    return None",
            "patch('pkg.mod.target', create=True)",
        ]
    )
    result = analyze_source(text)
    assert "TW009" not in finding_codes(result)


def test_ignores_relative_import() -> None:
    text = "\n".join(
        [
            "from .mock import patch",
            "patch('pkg.mod.target', create=True)",
        ]
    )
    result = analyze_source(text)
    assert "TW009" not in finding_codes(result)


def test_ignores_unresolved_mocker_fixture_name() -> None:
    text = "\n".join(
        [
            "def test_x(mocker):",
            "    mocker.patch('pkg.mod.target', create=True)",
        ]
    )
    result = analyze_source(text, allow_errors=True)
    assert "TW009" not in finding_codes(result)


def test_decorator_form_is_body_insensitive() -> None:
    base = "\n".join(
        [
            "from unittest.mock import patch",
            "@patch('pkg.mod.target', create=True)",
            "def f():",
            "    return 1",
        ]
    )
    modified = "\n".join(
        [
            "from unittest.mock import patch",
            "@patch('pkg.mod.target', create=True)",
            "def f():",
            "    return 2",
            "    x = 3",
        ]
    )
    first = next(f for f in analyze_source(base).findings if f.code == "TW009")
    second = next(f for f in analyze_source(modified).findings if f.code == "TW009")
    assert first.fingerprint == second.fingerprint


def test_with_form_is_body_insensitive() -> None:
    base = "\n".join(
        [
            "from unittest.mock import patch",
            "with patch('pkg.mod.target', create=True):",
            "    x = 1",
        ]
    )
    modified = "\n".join(
        [
            "from unittest.mock import patch",
            "with patch('pkg.mod.target', create=True):",
            "    x = 2",
            "    y = 3",
        ]
    )
    first = next(f for f in analyze_source(base).findings if f.code == "TW009")
    second = next(f for f in analyze_source(modified).findings if f.code == "TW009")
    assert first.fingerprint == second.fingerprint


def test_double_reports_with_tw012_when_create_true_lacks_fidelity() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch('pkg.mod.target', create=True)",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    codes = finding_codes(result)
    assert codes.count("TW009") == 1
    assert codes.count("TW012") == 1


def test_mock_patch_candidate_shape() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch('pkg.mod.target', create=True)",
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
