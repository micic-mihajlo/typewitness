from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Optional, Tuple

VALID_RULE_CODES = frozenset({"TW001", "TW002", "TW003", "TW004"})
DEFAULT_RULESET = frozenset({"TW001", "TW002", "TW003"})


def _validate_rule_codes(codes: frozenset[str], field_name: str) -> None:
    for code in codes:
        if code not in VALID_RULE_CODES:
            raise ValueError(f"unknown rule code in {field_name}: {code!r}")


@dataclass(frozen=True)
class SourceLocation:
    line: int
    column: int

    def __post_init__(self) -> None:
        if self.line < 1:
            raise ValueError("line must be >= 1")
        if self.column < 0:
            raise ValueError("column must be >= 0")


@dataclass(frozen=True)
class SourceRange:
    start: SourceLocation
    end: SourceLocation

    def __post_init__(self) -> None:
        start_pos = (self.start.line, self.start.column)
        end_pos = (self.end.line, self.end.column)
        if end_pos < start_pos:
            raise ValueError("end must not be before start")


@dataclass(frozen=True)
class SourceFile:
    path: pathlib.Path
    text: str
    encoding: str = "utf-8"


@dataclass(frozen=True)
class Finding:
    code: str
    path: pathlib.Path
    range: SourceRange
    message: str
    fingerprint: str


@dataclass(frozen=True)
class AnalysisError:
    kind: str
    path: Optional[pathlib.Path]
    message: str


@dataclass(frozen=True)
class AnalysisResult:
    findings: Tuple[Finding, ...]
    errors: Tuple[AnalysisError, ...]


@dataclass(frozen=True)
class Config:
    select: Optional[frozenset[str]] = None
    ignore: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.select is not None:
            _validate_rule_codes(self.select, "select")
        _validate_rule_codes(self.ignore, "ignore")

    def resolved_select(self) -> frozenset[str]:
        base = DEFAULT_RULESET if self.select is None else self.select
        return base - self.ignore
