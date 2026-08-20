from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

SUPPRESSIBLE_RULE_CODES = frozenset({"TW002", "TW003", "TW004"})

SAFETY_REASON_WORD_RE = re.compile(r"[A-Za-z0-9]+")
TYPE_IGNORE_RE = re.compile(
    r"^type:\s*ignore(?:\s*\[(?P<codes>[^\]]*)\])?(?:\s|$)",
)
TYPE_IGNORE_CODE_RE = re.compile(r"^[\w-]+$")


@dataclass(frozen=True)
class SafetyDirective:
    reason: str
    scoped_codes: frozenset[str]


@dataclass(frozen=True)
class TypeIgnoreDirective:
    has_valid_codes: bool
    inline_safety_reason: Optional[str] = None


def comment_body(comment_text: str) -> str:
    return comment_text.lstrip("#").strip()


def _strip_trailing_whitespace(text: str) -> str:
    end = len(text)
    while end > 0 and text[end - 1].isspace():
        end -= 1
    return text[:end]


def _skip_spaces(body: str, index: int) -> int:
    while index < len(body) and body[index].isspace():
        index += 1
    return index


def _safety_reason_valid(reason: str) -> bool:
    words = SAFETY_REASON_WORD_RE.findall(reason)
    return len(words) >= 2


def _validated_scoped_codes(scope_part: str) -> Optional[frozenset[str]]:
    codes = [part.strip() for part in scope_part.split(",") if part.strip()]
    if not codes:
        return None
    if any(code not in SUPPRESSIBLE_RULE_CODES for code in codes):
        return None
    return frozenset(codes)


def _parse_safety_body(body: str) -> Optional[tuple[Optional[str], str]]:
    if not body.startswith("SAFETY"):
        return None

    index = len("SAFETY")
    scope_part: Optional[str] = None
    index = _skip_spaces(body, index)
    if index < len(body) and body[index] == "[":
        close = body.find("]", index + 1)
        if close == -1:
            return None
        scope_part = body[index + 1 : close]
        index = close + 1

    index = _skip_spaces(body, index)
    if index >= len(body) or body[index] != ":":
        return None
    index += 1
    index = _skip_spaces(body, index)
    if index >= len(body):
        return None

    reason = _strip_trailing_whitespace(body[index:])
    if not reason:
        return None
    return scope_part, reason


def _parse_type_ignore_inline_safety(body: str) -> Optional[tuple[Optional[str], str]]:
    if not body.startswith("type:"):
        return None
    index = len("type:")
    index = _skip_spaces(body, index)
    if index + len("ignore") > len(body) or body[index : index + len("ignore")] != "ignore":
        return None
    index += len("ignore")

    codes_part: Optional[str] = None
    index = _skip_spaces(body, index)
    if index < len(body) and body[index] == "[":
        close = body.find("]", index + 1)
        if close == -1:
            return None
        codes_part = body[index + 1 : close]
        index = close + 1

    index = _skip_spaces(body, index)
    if index + len("SAFETY:") > len(body) or body[index : index + len("SAFETY:")] != "SAFETY:":
        return None
    index += len("SAFETY:")
    index = _skip_spaces(body, index)
    if index >= len(body):
        return None

    reason = _strip_trailing_whitespace(body[index:])
    if not reason:
        return None
    return codes_part, reason


def parse_safety(comment_text: str) -> Optional[SafetyDirective]:
    if not comment_text.startswith("#"):
        return None
    if comment_text.startswith("##"):
        return None
    body = comment_body(comment_text)
    if body.startswith("type:"):
        return None
    parsed = _parse_safety_body(body)
    if parsed is None:
        return None
    scope_part, reason = parsed
    if not _safety_reason_valid(reason):
        return None
    scoped_codes: frozenset[str] = frozenset()
    if scope_part is not None:
        validated = _validated_scoped_codes(scope_part)
        if validated is None:
            return None
        scoped_codes = validated
    return SafetyDirective(reason=reason, scoped_codes=scoped_codes)


def is_type_ignore_comment(comment_text: str) -> bool:
    if not comment_text.startswith("#"):
        return False
    if comment_text.startswith("##"):
        return False
    body = comment_body(comment_text)
    return (
        TYPE_IGNORE_RE.match(body) is not None or _parse_type_ignore_inline_safety(body) is not None
    )


def parse_type_ignore(comment_text: str) -> Optional[TypeIgnoreDirective]:
    if not is_type_ignore_comment(comment_text):
        return None
    body = comment_body(comment_text)
    inline = _parse_type_ignore_inline_safety(body)
    if inline is not None:
        codes_part, reason = inline
        if not _safety_reason_valid(reason):
            return TypeIgnoreDirective(has_valid_codes=False)
        if codes_part is None:
            return TypeIgnoreDirective(has_valid_codes=False, inline_safety_reason=reason)
        codes = [code.strip() for code in codes_part.split(",") if code.strip()]
        if not codes or any(not TYPE_IGNORE_CODE_RE.match(code) for code in codes):
            return TypeIgnoreDirective(has_valid_codes=False)
        return TypeIgnoreDirective(has_valid_codes=True, inline_safety_reason=reason)
    match = TYPE_IGNORE_RE.match(body)
    if match is None:
        return None
    codes_part = match.group("codes")
    if codes_part is None:
        return TypeIgnoreDirective(has_valid_codes=False)
    codes = [code.strip() for code in codes_part.split(",") if code.strip()]
    if not codes or any(not TYPE_IGNORE_CODE_RE.match(code) for code in codes):
        return TypeIgnoreDirective(has_valid_codes=False)
    return TypeIgnoreDirective(has_valid_codes=True)


def parse_inline_type_ignore_safety(comment_text: str) -> Optional[str]:
    if not comment_text.startswith("#") or comment_text.startswith("##"):
        return None
    body = comment_body(comment_text)
    inline = _parse_type_ignore_inline_safety(body)
    if inline is None:
        return None
    codes_part, reason = inline
    if not _safety_reason_valid(reason):
        return None
    if codes_part is not None:
        codes = [code.strip() for code in codes_part.split(",") if code.strip()]
        if not codes or any(not TYPE_IGNORE_CODE_RE.match(code) for code in codes):
            return None
    return reason


def canonical_type_ignore_norm(comment_text: str) -> str:
    body = comment_body(comment_text)
    if _parse_type_ignore_inline_safety(body) is not None:
        safety_index = body.find("SAFETY:")
        if safety_index != -1:
            body = body[:safety_index].rstrip()
    match = TYPE_IGNORE_RE.match(body)
    if match is None:
        return "type:ignore:invalid"
    codes_part = match.group("codes")
    if codes_part is None:
        return "type:ignore:uncoded"
    codes = [code.strip() for code in codes_part.split(",") if code.strip()]
    if not codes:
        return "type:ignore:invalid-codes"
    if codes_part.endswith(",") or ",," in codes_part:
        return "type:ignore:invalid-codes"
    if any(not TYPE_IGNORE_CODE_RE.match(code) for code in codes):
        return "type:ignore:invalid-codes"
    if body.rstrip().endswith(","):
        return "type:ignore:invalid-codes"
    return "type:ignore[" + ",".join(sorted(codes)) + "]"


def safety_suppresses_rule(directive: SafetyDirective, rule_code: str) -> bool:
    if not directive.scoped_codes:
        return True
    return rule_code in directive.scoped_codes


def has_safety_reason(comment_text: str) -> bool:
    return parse_safety(comment_text) is not None


def type_ignore_has_codes(comment_text: str) -> bool:
    parsed = parse_type_ignore(comment_text)
    if parsed is None:
        return False
    if parsed.inline_safety_reason is not None:
        return parsed.has_valid_codes
    return parsed.has_valid_codes
