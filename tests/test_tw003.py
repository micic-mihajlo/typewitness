from __future__ import annotations

from tests.conftest import analyze_source, finding_at, finding_codes


def test_flags_type_ignore_without_codes() -> None:
    text = "x = 1  # type: ignore SAFETY: missing codes\n"
    result = analyze_source(text)
    assert "TW003" in finding_codes(result)


def test_flags_type_ignore_without_safety() -> None:
    text = "x = 1  # type: ignore[assignment]\n"
    result = analyze_source(text)
    assert "TW003" in finding_codes(result)


def test_flags_empty_safety_in_type_ignore() -> None:
    text = "x = 1  # type: ignore[assignment] SAFETY:\n"
    result = analyze_source(text)
    assert "TW003" in finding_codes(result)


def test_allows_valid_type_ignore() -> None:
    text = "\n".join(
        [
            "# SAFETY: legacy code API",
            "x = 1  # type: ignore[assignment]",
        ]
    )
    result = analyze_source(text)
    assert "TW003" not in finding_codes(result)


def test_allows_multiple_error_codes() -> None:
    text = "\n".join(
        [
            "# SAFETY: legacy code",
            "x = 1  # type: ignore[assignment,arg-type]",
        ]
    )
    result = analyze_source(text)
    assert "TW003" not in finding_codes(result)


def test_ignores_type_ignore_in_string() -> None:
    text = 'msg = "type: ignore[assignment] SAFETY: fake"\n'
    result = analyze_source(text)
    assert "TW003" not in finding_codes(result)


def test_ignores_type_ignore_in_docstring() -> None:
    text = 'def f():\n    """type: ignore[misc] SAFETY: fake"""\n    return 1\n'
    result = analyze_source(text)
    assert "TW003" not in finding_codes(result)


def test_reports_at_comment_location() -> None:
    text = "x = 1  # type: ignore[assignment]\n"
    result = analyze_source(text)
    finding = finding_at(result, line=1, column=7)
    assert finding is not None
    assert finding.code == "TW003"


def test_flags_type_ignore_on_own_line() -> None:
    text = "\n".join(
        [
            "def f():",
            "    # type: ignore[return-value]",
            "    return 1",
        ]
    )
    result = analyze_source(text)
    assert "TW003" in finding_codes(result)


def test_allows_type_ignore_with_trailing_rationale_before_safety() -> None:
    text = "x = 1  # type: ignore[assignment] rationale SAFETY: reason\n"
    result = analyze_source(text)
    assert "TW003" in finding_codes(result)
