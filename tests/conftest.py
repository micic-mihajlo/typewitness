from __future__ import annotations

import pathlib

from typewitness import AnalysisResult, Config, Finding, SourceFile, analyze

DEFAULT_RULESET = frozenset({"TW001", "TW002", "TW003"})
ALL_RULES = DEFAULT_RULESET | frozenset({"TW004"})


def analyze_source(
    text: str,
    path: str = "sample.py",
    *,
    select: frozenset[str] | None = None,
    ignore: frozenset[str] | None = None,
    allow_errors: bool = False,
) -> AnalysisResult:
    config = Config(
        select=select,
        ignore=ignore if ignore is not None else frozenset(),
    )
    result = analyze(SourceFile(path=pathlib.Path(path), text=text), config=config)
    if not allow_errors:
        assert result.errors == (), result.errors
    return result


def finding_codes(result: AnalysisResult) -> list[str]:
    return [finding.code for finding in result.findings]


def finding_at(result: AnalysisResult, line: int, column: int = 0) -> Finding | None:
    for finding in result.findings:
        if finding.range.start.line == line and finding.range.start.column == column:
            return finding
    return None


def analyze_tw004(
    text: str,
    path: str = "sample.py",
    *,
    ignore: frozenset[str] | None = None,
    allow_errors: bool = False,
) -> AnalysisResult:
    return analyze_source(
        text,
        path=path,
        select=ALL_RULES,
        ignore=ignore,
        allow_errors=allow_errors,
    )
