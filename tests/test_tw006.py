from __future__ import annotations

from tests.conftest import analyze_source, finding_codes


def test_flags_discarded_cast_expression_statement() -> None:
    text = "from typing import cast\ncast(int, payload)\n"
    result = analyze_source(text)
    assert "TW006" in finding_codes(result)


def test_allows_assigned_cast() -> None:
    text = "from typing import cast\nx = cast(int, payload)\n"
    result = analyze_source(text)
    assert "TW006" not in finding_codes(result)


def test_allows_cast_in_return() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "def f():",
            "    return cast(int, payload)",
        ]
    )
    result = analyze_source(text)
    assert "TW006" not in finding_codes(result)


def test_allows_cast_in_call_argument() -> None:
    text = "from typing import cast\nprint(cast(int, payload))\n"
    result = analyze_source(text)
    assert "TW006" not in finding_codes(result)


def test_allows_explicit_scoped_suppression() -> None:
    text = "from typing import cast\ncast(int, payload)  # SAFETY[TW006]: intentional no-op\n"
    result = analyze_source(text)
    assert "TW006" not in finding_codes(result)


def test_bare_safety_does_not_suppress() -> None:
    text = "from typing import cast\ncast(int, payload)  # SAFETY: intentional no-op\n"
    result = analyze_source(text)
    assert "TW006" in finding_codes(result)


def test_skips_chain_child() -> None:
    text = "from typing import cast\ncast(int, cast(str, payload))\n"
    result = analyze_source(text)
    assert finding_codes(result).count("TW006") == 1


def test_double_reports_with_tw002() -> None:
    text = "from typing import cast\ncast(int, payload)\n"
    result = analyze_source(text)
    codes = finding_codes(result)
    assert "TW002" in codes
    assert "TW006" in codes


def test_finding_range_on_cast_call() -> None:
    text = "from typing import cast\ncast(int, payload)\n"
    result = analyze_source(text)
    finding = next(f for f in result.findings if f.code == "TW006")
    assert finding.range.start.line == 2
    assert finding.range.start.column == 0
    assert finding.fingerprint


def test_fingerprint_stable_across_unrelated_edits() -> None:
    text = "from typing import cast\ncast(int, payload)\n"
    modified = text + "y = 1\n"
    first = next(f for f in analyze_source(text).findings if f.code == "TW006")
    second = next(f for f in analyze_source(modified).findings if f.code == "TW006")
    assert first.fingerprint == second.fingerprint
