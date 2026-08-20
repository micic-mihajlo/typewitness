from __future__ import annotations

import sys

import pytest

from tests.conftest import analyze_source
from typewitness.source_index import normalize_token_stream

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 14),
    reason="t-string tokens require Python 3.14+",
)


def test_nested_tstring_normalizes() -> None:
    source = 'x = t"{t"{1}"}"\n'
    normalized = normalize_token_stream(source)
    assert "STRING:" in normalized
    assert normalized.count("STRING:") >= 1


def test_nested_f_inside_t_normalizes() -> None:
    source = 'x = t"{f"{1}"}"\n'
    normalized = normalize_token_stream(source)
    assert "STRING:" in normalized


def test_nested_t_inside_f_normalizes() -> None:
    source = 'x = f"{t"{1}"}"\n'
    normalized = normalize_token_stream(source)
    assert "STRING:" in normalized


def test_tstring_fingerprint_stable_across_unrelated_insert() -> None:
    original = 'from typing import cast\ndef f():\n    return cast(int, t"{1}")\n'
    modified = "# header\n" + original
    fp_original = analyze_source(original).findings[0].fingerprint
    fp_modified = analyze_source(modified).findings[0].fingerprint
    assert fp_original == fp_modified


def test_nested_tstring_cast_fingerprints_match_across_runs() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "label = t\"{t'{nested}'}\"",
            "def f():",
            "    return cast(str, label)",
        ]
    )
    first = analyze_source(text)
    second = analyze_source(text)
    assert len(first.findings) == len(second.findings) == 1
    assert first.findings[0].fingerprint == second.findings[0].fingerprint
