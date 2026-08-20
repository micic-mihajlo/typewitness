from __future__ import annotations

import pathlib

import pytest

from typewitness import (
    AnalysisError,
    AnalysisResult,
    Config,
    Finding,
    SourceFile,
    SourceLocation,
    SourceRange,
)


def test_source_location_rejects_invalid_line() -> None:
    with pytest.raises(ValueError):
        SourceLocation(line=0, column=0)


def test_source_location_rejects_negative_column() -> None:
    with pytest.raises(ValueError):
        SourceLocation(line=1, column=-1)


def test_source_range_half_open() -> None:
    start = SourceLocation(line=1, column=0)
    end = SourceLocation(line=1, column=4)
    assert SourceRange(start=start, end=end).start is start


def test_source_range_rejects_end_before_start() -> None:
    start = SourceLocation(line=2, column=0)
    end = SourceLocation(line=1, column=4)
    with pytest.raises(ValueError):
        SourceRange(start=start, end=end)


def test_config_defaults_are_immutable() -> None:
    config = Config()
    assert config.select is None
    assert config.ignore == frozenset()
    assert config.resolved_select() == frozenset({"TW001", "TW002", "TW003"})


def test_finding_is_frozen() -> None:
    finding = Finding(
        code="TW001",
        path=pathlib.Path("a.py"),
        range=SourceRange(
            start=SourceLocation(line=1, column=0),
            end=SourceLocation(line=1, column=4),
        ),
        message="msg",
        fingerprint="abc",
    )
    with pytest.raises(AttributeError):
        finding.code = "TW002"  # type: ignore[misc]


def test_analysis_result_tuple_fields() -> None:
    result = AnalysisResult(findings=(), errors=())
    assert result.findings == ()
    assert result.errors == ()


def test_analysis_error_optional_path() -> None:
    err = AnalysisError(kind="parse", path=None, message="bad syntax")
    assert err.path is None


def test_source_file_defaults() -> None:
    source = SourceFile(path=pathlib.Path("x.py"), text="pass\n")
    assert source.encoding == "utf-8"
