from __future__ import annotations

from tests.conftest import analyze_source, finding_codes


def test_flags_cast_to_any() -> None:
    text = "from typing import Any, cast\nx = cast(Any, payload)\n"
    result = analyze_source(text)
    assert "TW005" in finding_codes(result)


def test_allows_cast_to_concrete_type() -> None:
    text = "from typing import cast\nx = cast(int, payload)\n"
    result = analyze_source(text)
    assert "TW005" not in finding_codes(result)


def test_resolves_typing_any_attribute() -> None:
    text = "import typing\nx = typing.cast(typing.Any, payload)\n"
    result = analyze_source(text)
    assert "TW005" in finding_codes(result)


def test_resolves_typing_extensions_any() -> None:
    text = "import typing_extensions as te\nfrom typing import cast\nx = cast(te.Any, payload)\n"
    result = analyze_source(text)
    assert "TW005" in finding_codes(result)


def test_ignores_shadowed_any() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "def f(Any):",
            "    return cast(Any, payload)",
        ]
    )
    result = analyze_source(text)
    assert "TW005" not in finding_codes(result)


def test_ignores_conditionally_ambiguous_any() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "try:",
            "    from typing import Any",
            "except ImportError:",
            "    Any = object",
            "x = cast(Any, payload)",
        ]
    )
    result = analyze_source(text)
    assert "TW005" not in finding_codes(result)


def test_does_not_flag_cast_to_object() -> None:
    text = "from typing import cast\nx = cast(object, payload)\n"
    result = analyze_source(text)
    assert "TW005" not in finding_codes(result)


def test_allows_explicit_scoped_suppression() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "x = cast(Any, payload)  # SAFETY[TW005]: reviewed erasure",
        ]
    )
    result = analyze_source(text)
    assert "TW005" not in finding_codes(result)


def test_bare_safety_does_not_suppress() -> None:
    text = "from typing import Any, cast\nx = cast(Any, payload)  # SAFETY: reviewed erasure\n"
    result = analyze_source(text)
    assert "TW005" in finding_codes(result)


def test_malformed_scope_does_not_suppress() -> None:
    text = "from typing import Any, cast\nx = cast(Any, payload)  # SAFETY[TW005]: checked\n"
    result = analyze_source(text)
    assert "TW005" in finding_codes(result)


def test_reports_inner_chain_child_cast_to_any() -> None:
    text = "from typing import Any, cast\nx = cast(int, cast(Any, payload))\n"
    result = analyze_source(text)
    codes = finding_codes(result)
    assert "TW001" in codes
    assert "TW005" in codes
    assert codes.count("TW005") == 1


def test_reports_outer_cast_to_any_in_chain() -> None:
    text = "from typing import Any, cast\nx = cast(Any, cast(int, payload))\n"
    result = analyze_source(text)
    assert finding_codes(result).count("TW005") == 1


def test_ignores_relative_typing_any_import() -> None:
    text = "\n".join(
        [
            "from .typing import Any, cast",
            "x = cast(Any, payload)",
        ]
    )
    result = analyze_source(text)
    assert "TW005" not in finding_codes(result)


def test_finding_range_on_cast_call() -> None:
    text = "from typing import Any, cast\nx = cast(Any, payload)\n"
    result = analyze_source(text)
    finding = next(f for f in result.findings if f.code == "TW005")
    assert finding.range.start.line == 2
    assert finding.range.start.column == 4
    assert finding.fingerprint


def test_fingerprint_stable_across_unrelated_edits() -> None:
    text = "from typing import Any, cast\nx = cast(Any, payload)\n"
    modified = text + "y = 1\n"
    first = next(f for f in analyze_source(text).findings if f.code == "TW005")
    second = next(f for f in analyze_source(modified).findings if f.code == "TW005")
    assert first.fingerprint == second.fingerprint
