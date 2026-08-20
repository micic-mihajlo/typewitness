from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from typewitness.directives import (
    TYPE_IGNORE_CODE_RE,
    SafetyDirective,
    comment_body,
    evidence_suppresses_rule,
)
from typewitness.source_index import SourceIndex

MYPY_COMMENT_PREFIX = "# mypy: "
_TRUTHY_VALUES = frozenset({"1", "on", "true", "yes"})
_FALSY_VALUES = frozenset({"0", "false", "no", "off"})
_PYRIGHT_REPORT_RE = re.compile(
    r"^report([A-Z][A-Za-z0-9]*)\s*=\s*(false|none)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CheckerDisableDirective:
    checker: str
    candidate_norm: str


def _strip_optional_quotes(text: str) -> str:
    stripped = text.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "\"'":
        return stripped[1:-1]
    return stripped


def _normalize_mypy_key(key: str) -> str:
    return key.strip().replace("-", "_").lower()


def _is_truthy(value: Optional[str]) -> bool:
    if value is None:
        return True
    normalized = value.strip().lower()
    if not normalized:
        return True
    if normalized in _FALSY_VALUES:
        return False
    if normalized in _TRUTHY_VALUES:
        return True
    return False


def _validated_mypy_codes(codes_part: str) -> Optional[tuple[str, ...]]:
    raw = _strip_optional_quotes(codes_part.strip())
    if not raw:
        return None
    codes = [part.strip() for part in raw.split(",") if part.strip()]
    if not codes:
        return None
    if raw.endswith(",") or ",," in raw:
        return None
    if any(not TYPE_IGNORE_CODE_RE.match(code) for code in codes):
        return None
    return tuple(sorted(codes))


def _skip_mypy_whitespace(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _parse_mypy_option_segments(remainder: str) -> Optional[List[Tuple[str, Optional[str]]]]:
    segments: List[Tuple[str, Optional[str]]] = []
    index = 0
    length = len(remainder)
    while index < length:
        index = _skip_mypy_whitespace(remainder, index)
        if index >= length:
            break
        start = index
        in_quote: Optional[str] = None
        while index < length:
            char = remainder[index]
            if in_quote is not None:
                if char == in_quote:
                    in_quote = None
                index += 1
                continue
            if char in "\"'":
                in_quote = char
                index += 1
                continue
            if char == ",":
                break
            index += 1
        part = remainder[start:index].strip()
        if not part:
            return None
        if "=" in part:
            key_part, value_part = part.split("=", 1)
            key = _normalize_mypy_key(key_part)
            if not key:
                return None
            segments.append((key, value_part.strip()))
        else:
            first_token = part.split(None, 1)[0]
            key = _normalize_mypy_key(first_token)
            if not key:
                return None
            segments.append((key, None))
        index += 1
    if not segments:
        return None
    return segments


def _mypy_weakening_norms(segments: List[Tuple[str, Optional[str]]]) -> Optional[tuple[str, ...]]:
    norms: List[str] = []
    for key, value in segments:
        if key == "ignore_errors" and _is_truthy(value):
            norms.append("mypy:ignore-errors")
            continue
        if key == "disable_error_code":
            codes = _validated_mypy_codes(value or "")
            if codes is None:
                return None
            norms.append(f"mypy:disable-error-code[{','.join(codes)}]")
    if not norms:
        return None
    return tuple(sorted(set(norms)))


def _parse_pyright_segments(body: str) -> Optional[List[str]]:
    if not body.startswith("pyright:"):
        return None
    remainder = body[len("pyright:") :].strip()
    if not remainder:
        return None
    segments = [part.strip() for part in remainder.split(",")]
    if not segments or any(not segment for segment in segments):
        return None
    return segments


def _pyright_weakening_norms(segments: List[str]) -> Optional[tuple[str, ...]]:
    norms: List[str] = []
    for segment in segments:
        lowered = segment.lower()
        if lowered == "basic":
            norms.append("pyright:basic")
            continue
        if lowered == "standard":
            norms.append("pyright:standard")
            continue
        match = _PYRIGHT_REPORT_RE.match(segment)
        if match is not None:
            name, value = match.group(1), match.group(2).lower()
            norms.append(f"pyright:report{name}={value}")
    if not norms:
        return None
    return tuple(sorted(set(norms)))


def canonical_checker_disable_norm(comment_text: str) -> Optional[str]:
    parsed = parse_checker_disable(comment_text)
    if parsed is None:
        return None
    return parsed.candidate_norm


def parse_checker_disable(comment_text: str) -> Optional[CheckerDisableDirective]:
    if not comment_text.startswith("#"):
        return None
    if comment_text.startswith("##"):
        return None
    mypy = _parse_mypy_disable(comment_text)
    if mypy is not None:
        return mypy
    return _parse_pyright_disable(comment_text)


def _parse_mypy_disable(comment_text: str) -> Optional[CheckerDisableDirective]:
    if not comment_text.startswith(MYPY_COMMENT_PREFIX):
        return None
    remainder = comment_text[len(MYPY_COMMENT_PREFIX) :]
    segments = _parse_mypy_option_segments(remainder)
    if segments is None:
        return None
    norms = _mypy_weakening_norms(segments)
    if norms is None:
        return None
    return CheckerDisableDirective(checker="mypy", candidate_norm="|".join(norms))


def _parse_pyright_disable(comment_text: str) -> Optional[CheckerDisableDirective]:
    body = comment_body(comment_text)
    segments = _parse_pyright_segments(body)
    if segments is None:
        return None
    norms = _pyright_weakening_norms(segments)
    if norms is None:
        return None
    return CheckerDisableDirective(checker="pyright", candidate_norm="|".join(norms))


def preceding_comment_safety_suppresses_rule(
    source_index: SourceIndex,
    directive_line: int,
    rule_code: str,
) -> bool:
    prev_line = directive_line - 1
    if prev_line < 1 or prev_line not in source_index.comment_only_lines:
        return False
    directives: Tuple[SafetyDirective, ...] = source_index.safety_by_logical_line.get(
        prev_line,
        (),
    )
    return any(evidence_suppresses_rule(directive, rule_code) for directive in directives)
