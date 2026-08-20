from __future__ import annotations

import pathlib

from typewitness.fingerprint import FINGERPRINT_SCHEMA, make_fingerprint


def test_fingerprint_format() -> None:
    fp = make_fingerprint(
        code="TW001",
        path=pathlib.Path("pkg/mod.py"),
        kind="cast-call",
        scope_path="fn:f",
        candidate_norm="NAME:cast OP:( ... )",
        host_norm="NAME:x OP:= ...",
    )
    assert len(fp) == 16
    assert fp == fp.lower()
    assert all(ch in "0123456789abcdef" for ch in fp)


def test_fingerprint_stable_for_same_input() -> None:
    first = make_fingerprint(
        code="TW002",
        path=pathlib.Path("a/b.py"),
        kind="cast-call",
        scope_path="fn:bar",
        candidate_norm="NAME:cast",
        host_norm="NAME:x",
    )
    second = make_fingerprint(
        code="TW002",
        path=pathlib.Path("a/b.py"),
        kind="cast-call",
        scope_path="fn:bar",
        candidate_norm="NAME:cast",
        host_norm="NAME:x",
    )
    assert first == second


def test_fingerprint_differs_by_rule_code() -> None:
    assert make_fingerprint(
        code="TW001",
        path=pathlib.Path("a.py"),
        kind="cast-call",
        scope_path="fn:f",
        candidate_norm="NAME:cast",
        host_norm="NAME:x",
    ) != make_fingerprint(
        code="TW002",
        path=pathlib.Path("a.py"),
        kind="cast-call",
        scope_path="fn:f",
        candidate_norm="NAME:cast",
        host_norm="NAME:x",
    )


def test_fingerprint_schema_constant() -> None:
    assert FINGERPRINT_SCHEMA == "tw-fp-2"


def test_fingerprint_survives_leading_line_insertion() -> None:
    from tests.conftest import analyze_source

    original = "from typing import cast\n\n\ndef f():\n    return cast(int, 1)\n"
    modified = "# header\n" + original
    result_original = analyze_source(original)
    result_modified = analyze_source(modified)
    assert len(result_original.findings) == 1
    assert len(result_modified.findings) == 1
    assert result_original.findings[0].fingerprint == result_modified.findings[0].fingerprint
