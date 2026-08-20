from __future__ import annotations

from tests.conftest import analyze_source, finding_at, finding_codes


def test_flags_mypy_ignore_errors_without_evidence() -> None:
    text = "# mypy: ignore-errors\nimport x\n"
    result = analyze_source(text)
    assert "TW007" in finding_codes(result)


def test_flags_mypy_disable_error_code_without_evidence() -> None:
    text = '# mypy: disable-error-code="assignment,misc"\nimport x\n'
    result = analyze_source(text)
    assert "TW007" in finding_codes(result)


def test_flags_pyright_basic_without_evidence() -> None:
    text = "# pyright: basic\nimport x\n"
    result = analyze_source(text)
    assert "TW007" in finding_codes(result)


def test_flags_pyright_report_setting_without_evidence() -> None:
    text = "# pyright: reportGeneralTypeIssues=false\nimport x\n"
    result = analyze_source(text)
    assert "TW007" in finding_codes(result)


def test_allows_preceding_safety_on_immediately_prior_line_only() -> None:
    text = "\n".join(
        [
            "# SAFETY: vendored stubs incomplete",
            "# mypy: ignore-errors",
            "import x",
        ]
    )
    result = analyze_source(text)
    assert "TW007" not in finding_codes(result)


def test_rejects_safety_two_comment_lines_above_directive() -> None:
    text = "\n".join(
        [
            "# SAFETY: vendored stubs incomplete",
            "# unrelated note",
            "# mypy: ignore-errors",
            "import x",
        ]
    )
    result = analyze_source(text)
    assert "TW007" in finding_codes(result)


def test_flags_mypy_ignore_errors_mid_module() -> None:
    text = "\n".join(
        [
            "import x",
            "",
            "# mypy: ignore-errors",
            "import y",
        ]
    )
    result = analyze_source(text)
    assert "TW007" in finding_codes(result)


def test_flags_mypy_mixed_weakening_option_list() -> None:
    text = "# mypy: warn-return-any, ignore-errors\nimport x\n"
    result = analyze_source(text)
    assert "TW007" in finding_codes(result)


def test_flags_pyright_mixed_weakening_option_list() -> None:
    text = "# pyright: strict, reportGeneralTypeIssues=false\nimport x\n"
    result = analyze_source(text)
    assert "TW007" in finding_codes(result)


def test_allows_preceding_safety_comment() -> None:
    text = "\n".join(
        [
            "# SAFETY: vendored stubs incomplete",
            "# mypy: ignore-errors",
            "import x",
        ]
    )
    result = analyze_source(text)
    assert "TW007" not in finding_codes(result)


def test_allows_scoped_safety_comment() -> None:
    text = "\n".join(
        [
            "# SAFETY[TW007]: vendored stubs incomplete",
            "# mypy: ignore-errors",
            "import x",
        ]
    )
    result = analyze_source(text)
    assert "TW007" not in finding_codes(result)


def test_rejects_inline_safety_on_directive_line() -> None:
    text = "# mypy: ignore-errors SAFETY: vendored stubs incomplete\nimport x\n"
    result = analyze_source(text)
    assert "TW007" in finding_codes(result)


def test_ignores_indented_checker_disable() -> None:
    text = "\n".join(
        [
            "def f():",
            "    # mypy: ignore-errors",
            "    return 1",
        ]
    )
    result = analyze_source(text)
    assert "TW007" not in finding_codes(result)


def test_ignores_directive_after_module_code() -> None:
    text = "\n".join(
        [
            '"""module doc"""',
            "# mypy: ignore-errors",
            "import x",
        ]
    )
    result = analyze_source(text)
    assert "TW007" in finding_codes(result)


def test_ignores_double_hash_comment() -> None:
    text = "## mypy: ignore-errors\nimport x\n"
    result = analyze_source(text)
    assert "TW007" not in finding_codes(result)


def test_ignores_case_variants() -> None:
    text = "# MyPy: ignore-errors\nimport x\n"
    result = analyze_source(text)
    assert "TW007" not in finding_codes(result)


def test_ignores_directive_in_string() -> None:
    text = 'msg = "# mypy: ignore-errors"\nimport x\n'
    result = analyze_source(text)
    assert "TW007" not in finding_codes(result)


def test_ignores_noqa_and_ruff() -> None:
    text = "\n".join(
        [
            "# noqa",
            "# ruff: noqa",
            "# flake8: noqa",
            "import x",
        ]
    )
    result = analyze_source(text)
    assert "TW007" not in finding_codes(result)


def test_ignores_module_level_type_ignore() -> None:
    text = "# type: ignore\nimport x\n"
    result = analyze_source(text)
    assert "TW007" not in finding_codes(result)
    assert "TW003" in finding_codes(result)


def test_fingerprint_stable_for_code_reordering() -> None:
    first_text = '# mypy: disable-error-code="misc,assignment"\nimport x\n'
    second_text = '# mypy: disable-error-code="assignment,misc"\nimport x\n'
    first = next(f for f in analyze_source(first_text).findings if f.code == "TW007")
    second = next(f for f in analyze_source(second_text).findings if f.code == "TW007")
    assert first.fingerprint == second.fingerprint


def test_ignores_mypy_without_space_after_hash() -> None:
    text = "#mypy: ignore-errors\nimport x\n"
    result = analyze_source(text)
    assert "TW007" not in finding_codes(result)


def test_ignores_mypy_with_extra_space_after_hash() -> None:
    text = "#  mypy: ignore-errors\nimport x\n"
    result = analyze_source(text)
    assert "TW007" not in finding_codes(result)


def test_finding_range_on_directive_comment() -> None:
    text = "# mypy: ignore-errors\nimport x\n"
    result = analyze_source(text)
    finding = finding_at(result, line=1, column=0)
    assert finding is not None
    assert finding.code == "TW007"
