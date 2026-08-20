from __future__ import annotations

from tests.conftest import analyze_source


def test_analyze_empty_file() -> None:
    result = analyze_source("")
    assert result.findings == ()
    assert result.errors == ()


def test_analyze_syntax_error_returns_error() -> None:
    result = analyze_source("def f(:\n", allow_errors=True)
    assert result.findings == ()
    assert len(result.errors) == 1
    assert result.errors[0].kind == "parse"


def test_analyze_deterministic() -> None:
    text = "from typing import cast\nx = cast(int, '1')\n"
    first = analyze_source(text)
    second = analyze_source(text)
    assert first == second


def test_findings_sorted_deterministically() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "def a():",
            "    cast(int, 1)",
            "def b():",
            "    cast(int, 2)",
        ]
    )
    result = analyze_source(text)
    keys = [
        (str(f.path), f.range.start.line, f.range.start.column, f.code, f.fingerprint)
        for f in result.findings
    ]
    assert keys == sorted(keys)


def test_config_select_filters_rules() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "x = cast(int, cast(str, '1'))  # SAFETY: test evidence",
            "# type: ignore[assignment] SAFETY:",
        ]
    )
    result = analyze_source(text, select=frozenset({"TW001"}))
    assert all(f.code == "TW001" for f in result.findings)


def test_config_ignore_filters_rules() -> None:
    text = "from typing import cast\nx = cast(int, cast(str, '1'))  # SAFETY: test evidence\n"
    result = analyze_source(text, ignore=frozenset({"TW001"}))
    assert all(f.code != "TW001" for f in result.findings)


def test_public_exports() -> None:
    import typewitness

    expected = {
        "AnalysisError",
        "AnalysisResult",
        "Config",
        "Finding",
        "SourceFile",
        "SourceLocation",
        "SourceRange",
        "analyze",
    }
    assert expected.issubset(set(typewitness.__all__))
