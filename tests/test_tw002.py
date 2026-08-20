from __future__ import annotations

from tests.conftest import analyze_source, finding_at, finding_codes


def test_flags_cast_without_safety_comment() -> None:
    text = "from typing import cast\nx = cast(int, '1')\n"
    result = analyze_source(text)
    assert "TW002" in finding_codes(result)


def test_allows_cast_with_inline_safety() -> None:
    text = "from typing import cast\nx = cast(int, '1')  # SAFETY: coercion needed\n"
    result = analyze_source(text)
    assert "TW002" not in finding_codes(result)


def test_allows_cast_with_preceding_comment_only_line() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "# SAFETY: coercion needed on next line",
            "x = cast(int, '1')",
        ]
    )
    result = analyze_source(text)
    assert "TW002" not in finding_codes(result)


def test_flags_empty_safety_reason() -> None:
    text = "from typing import cast\nx = cast(int, '1')  # SAFETY:\n"
    result = analyze_source(text)
    assert "TW002" in finding_codes(result)


def test_resolves_typing_cast_attribute() -> None:
    text = "import typing\nx = typing.cast(int, '1')  # SAFETY: ok reason\n"
    result = analyze_source(text)
    assert "TW002" not in finding_codes(result)


def test_resolves_cast_alias() -> None:
    text = "from typing import cast as c\nx = c(int, '1')  # SAFETY: ok reason\n"
    result = analyze_source(text)
    assert "TW002" not in finding_codes(result)


def test_ignores_shadowed_cast() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "def f(cast):",
            "    return cast(int, '1')",
        ]
    )
    result = analyze_source(text)
    assert "TW002" not in finding_codes(result)


def test_string_with_safety_does_not_count() -> None:
    text = "from typing import cast\nx = cast(int, 'SAFETY: fake')\n"
    result = analyze_source(text)
    assert "TW002" in finding_codes(result)


def test_multiline_cast_uses_spanning_line_comment() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "x = cast(",
            "    int,",
            "    '1',",
            ")  # SAFETY: multiline cast",
        ]
    )
    result = analyze_source(text)
    assert "TW002" not in finding_codes(result)


def test_finding_range_on_cast_call() -> None:
    text = "from typing import cast\nx = cast(int, '1')\n"
    result = analyze_source(text)
    finding = finding_at(result, line=2, column=4)
    assert finding is not None
    assert finding.code == "TW002"
    assert finding.fingerprint
