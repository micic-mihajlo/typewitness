from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple, Union

from typewitness._instrumentation import record
from typewitness.directives import (
    SafetyDirective,
    parse_safety,
    parse_type_ignore,
)
from typewitness.models import SourceLocation, SourceRange

LocatedNode = Union[ast.expr, ast.stmt, ast.ExceptHandler]

FSTRING_START = getattr(tokenize, "FSTRING_START", None)
FSTRING_MIDDLE = getattr(tokenize, "FSTRING_MIDDLE", None)
FSTRING_END = getattr(tokenize, "FSTRING_END", None)
TSTRING_START = getattr(tokenize, "TSTRING_START", None)
TSTRING_MIDDLE = getattr(tokenize, "TSTRING_MIDDLE", None)
TSTRING_END = getattr(tokenize, "TSTRING_END", None)

_FSTRING_GROUP = tuple(t for t in (FSTRING_START, FSTRING_MIDDLE, FSTRING_END) if t is not None)
_TSTRING_GROUP = tuple(t for t in (TSTRING_START, TSTRING_MIDDLE, TSTRING_END) if t is not None)
_COMPOUND_START_TYPES = frozenset(t for t in (FSTRING_START, TSTRING_START) if t is not None)
_COMPOUND_END_BY_START: Dict[int, int] = {}
if FSTRING_START is not None and FSTRING_END is not None:
    _COMPOUND_END_BY_START[FSTRING_START] = FSTRING_END
if TSTRING_START is not None and TSTRING_END is not None:
    _COMPOUND_END_BY_START[TSTRING_START] = TSTRING_END


def normalize_source_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized.startswith("\ufeff"):
        normalized = normalized[1:]
    return normalized


def preflight_encode_error(text: str) -> Optional[str]:
    if "\x00" in text:
        return "source contains null bytes"
    for index, char in enumerate(text):
        if 0xD800 <= ord(char) <= 0xDFFF:
            return f"source contains lone surrogate at index {index}"
    return None


@dataclass(frozen=True)
class IndexedToken:
    bucket: str
    start_line: int
    start_col: int
    end_line: int
    end_col: int
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class CommentInfo:
    line: int
    column: int
    text: str
    safety: Optional[SafetyDirective]
    type_ignore: bool


@dataclass
class SourceIndex:
    text: str
    lines: Tuple[str, ...]
    line_starts: Tuple[int, ...]
    comments: Tuple[CommentInfo, ...]
    comments_by_line: Dict[int, Tuple[CommentInfo, ...]]
    comment_only_lines: frozenset[int]
    logical_line_start: Dict[int, int]
    logical_line_end: Dict[int, int]
    safety_by_logical_line: Dict[int, Tuple[SafetyDirective, ...]]
    normalized_tokens: Tuple[IndexedToken, ...]
    _byte_to_char_cache: Dict[Tuple[int, int], int] = field(
        default_factory=dict,
        init=False,
        repr=False,
        compare=False,
    )
    _byte_column_maps: Dict[int, Tuple[int, ...]] = field(
        default_factory=dict,
        init=False,
        repr=False,
        compare=False,
    )
    _norm_cache: Dict[Tuple[int, int, int, int], str] = field(
        default_factory=dict,
        init=False,
        repr=False,
        compare=False,
    )

    def char_offset(self, line: int, byte_column: int) -> int:
        if line < 1 or line > len(self.lines):
            return byte_column
        line_text = self.lines[line - 1]
        if line_text.isascii():
            return min(byte_column, len(line_text))

        cache_key = (line, byte_column)
        cached = self._byte_to_char_cache.get(cache_key)
        if cached is not None:
            return cached
        byte_map = self._byte_column_maps.get(line)
        if byte_map is None:
            byte_map = _build_byte_column_map(line_text)
            self._byte_column_maps[line] = byte_map
        result = byte_map[min(byte_column, len(byte_map) - 1)]
        self._byte_to_char_cache[cache_key] = result
        return result

    def node_range(self, node: LocatedNode) -> SourceRange:
        start_line = node.lineno
        start_col = self.char_offset(start_line, node.col_offset)
        end_line = getattr(node, "end_lineno", None) or start_line
        end_col_offset = getattr(node, "end_col_offset", None)
        if end_col_offset is None:
            end_col = start_col + 1
        else:
            end_col = self.char_offset(end_line, end_col_offset)
        return SourceRange(
            start=SourceLocation(line=start_line, column=start_col),
            end=SourceLocation(line=end_line, column=end_col),
        )

    def logical_end_line(self, line: int) -> int:
        return self.logical_line_end.get(line, line)

    def logical_start_line(self, line: int) -> int:
        return self.logical_line_start.get(line, line)

    def safety_for_statement(self, start_line: int, end_line: int) -> Tuple[SafetyDirective, ...]:
        directives: List[SafetyDirective] = []
        logical_end = self.logical_end_line(end_line)
        for line in range(start_line, logical_end + 1):
            directives.extend(self.safety_by_logical_line.get(line, ()))
        prev_line = start_line - 1
        while prev_line >= 1 and prev_line in self.comment_only_lines:
            directives.extend(self.safety_by_logical_line.get(prev_line, ()))
            prev_line -= 1
        return tuple(directives)

    def is_comment_only_line(self, line: int) -> bool:
        return line in self.comment_only_lines

    def slice_source(self, start_line: int, start_col: int, end_line: int, end_col: int) -> str:
        if start_line == end_line:
            return self.lines[start_line - 1][start_col:end_col]
        parts = [self.lines[start_line - 1][start_col:]]
        for line_no in range(start_line + 1, end_line):
            parts.append(self.lines[line_no - 1])
        parts.append(self.lines[end_line - 1][:end_col])
        return "\n".join(parts)

    def host_norm_for_span(
        self,
        start_line: int,
        start_col: int,
        end_line: int,
        end_col: int,
    ) -> str:
        cache_key = (start_line, start_col, end_line, end_col)
        cached = self._norm_cache.get(cache_key)
        if cached is not None:
            return cached
        span_start = self.line_starts[start_line - 1] + start_col
        span_end = self.line_starts[end_line - 1] + end_col
        tokens = self.normalized_tokens
        if not tokens:
            self._norm_cache[cache_key] = ""
            return ""
        lo = 0
        hi = len(tokens)
        while lo < hi:
            mid = (lo + hi) // 2
            if tokens[mid].end_offset <= span_start:
                lo = mid + 1
            else:
                hi = mid
        parts: List[str] = []
        visits = 0
        for index in range(lo, len(tokens)):
            tok = tokens[index]
            if tok.start_offset >= span_end:
                break
            if tok.end_offset > span_start and tok.start_offset < span_end:
                parts.append(tok.bucket)
                visits += 1
        record("token_visits", visits)
        record("span_token_visits", visits)
        result = " ".join(parts)
        self._norm_cache[cache_key] = result
        return result

    def norm_for_span(
        self,
        start_line: int,
        start_col: int,
        end_line: int,
        end_col: int,
    ) -> str:
        return self.host_norm_for_span(start_line, start_col, end_line, end_col)


def _safe_tokenize(text: str) -> list[tokenize.TokenInfo]:
    try:
        return list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, TabError, SyntaxError):
        return []


def build_source_index(text: str) -> SourceIndex:
    normalized = normalize_source_text(text)
    lines = tuple(normalized.split("\n"))
    line_starts: List[int] = []
    offset = 0
    for line in lines:
        line_starts.append(offset)
        offset += len(line) + 1

    tokens = _safe_tokenize(normalized)
    record("token_visits", len(tokens))
    normalized_tokens = _build_normalized_tokens(tokens, normalized, line_starts)

    comments: List[CommentInfo] = []
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            comment = CommentInfo(
                line=tok.start[0],
                column=tok.start[1],
                text=tok.string,
                safety=parse_safety(tok.string),
                type_ignore=parse_type_ignore(tok.string) is not None,
            )
            comments.append(comment)

    comments_by_line: Dict[int, List[CommentInfo]] = {}
    for comment in comments:
        comments_by_line.setdefault(comment.line, []).append(comment)
    comments_by_line_frozen = {line: tuple(items) for line, items in comments_by_line.items()}

    comment_only_lines: set[int] = set()
    for line_no, line_text in enumerate(lines, start=1):
        stripped = line_text.strip()
        if stripped and stripped.startswith("#") and not _has_code_before_comment(line_text):
            comment_only_lines.add(line_no)

    logical_line_start, logical_line_end = _compute_logical_line_bounds(tokens, lines)
    safety_by_logical_line = _index_safety(comments, logical_line_end)

    return SourceIndex(
        text=normalized,
        lines=lines,
        line_starts=tuple(line_starts),
        comments=tuple(comments),
        comments_by_line=comments_by_line_frozen,
        comment_only_lines=frozenset(comment_only_lines),
        logical_line_start=logical_line_start,
        logical_line_end=logical_line_end,
        safety_by_logical_line=safety_by_logical_line,
        normalized_tokens=tuple(normalized_tokens),
    )


def _has_code_before_comment(line_text: str) -> bool:
    in_string = False
    quote: Optional[str] = None
    index = 0
    while index < len(line_text):
        char = line_text[index]
        if not in_string:
            if char == "#":
                return False
            if char in ("'", '"'):
                if index + 2 < len(line_text) and line_text[index : index + 3] == char * 3:
                    quote = char * 3
                    in_string = True
                    index += 3
                    continue
                quote = char
                in_string = True
                index += 1
                continue
            if not char.isspace():
                return True
            index += 1
            continue
        if quote and line_text.startswith(quote, index):
            in_string = False
            quote = None
            index += len(quote or "")
            continue
        if quote and len(quote) == 1 and char == "\\":
            index += 2
            continue
        index += 1
    return False


def _compute_logical_line_bounds(
    tokens: Sequence[tokenize.TokenInfo],
    lines: Sequence[str],
) -> Tuple[Dict[int, int], Dict[int, int]]:
    if not lines:
        return {}, {}
    starts: Dict[int, int] = {}
    ends: Dict[int, int] = {}
    logical_start: Optional[int] = None

    for tok in tokens:
        if tok.type == tokenize.NEWLINE:
            line_no = tok.start[0]
            start_line = logical_start if logical_start is not None else line_no
            for stmt_line in range(start_line, line_no + 1):
                starts[stmt_line] = start_line
                ends[stmt_line] = line_no
            logical_start = None
            continue
        if tok.type == tokenize.NL:
            if logical_start is None:
                starts[tok.start[0]] = tok.start[0]
                ends[tok.start[0]] = tok.start[0]
            continue
        if tok.type == tokenize.COMMENT:
            if logical_start is None:
                starts[tok.start[0]] = tok.start[0]
                ends[tok.start[0]] = tok.start[0]
            continue
        if tok.type in (tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING):
            continue
        if tok.type == tokenize.ENDMARKER:
            break
        if logical_start is None:
            logical_start = tok.start[0]

    last_line = len(lines)
    if logical_start is not None:
        for line_no in range(logical_start, last_line + 1):
            starts[line_no] = logical_start
            ends[line_no] = last_line
    for line_no in range(1, last_line + 1):
        starts.setdefault(line_no, line_no)
        ends.setdefault(line_no, line_no)
    return starts, ends


def _index_safety(
    comments: Sequence[CommentInfo],
    logical_line_end: Dict[int, int],
) -> Dict[int, Tuple[SafetyDirective, ...]]:
    by_logical: Dict[int, List[SafetyDirective]] = {}
    for comment in comments:
        if comment.safety is None:
            continue
        logical_end = logical_line_end.get(comment.line, comment.line)
        by_logical.setdefault(logical_end, []).append(comment.safety)
    return {line: tuple(items) for line, items in by_logical.items()}


def _build_normalized_tokens(
    tokens: Sequence[tokenize.TokenInfo],
    source_text: str,
    line_starts: Sequence[int],
) -> List[IndexedToken]:
    parts: List[IndexedToken] = []
    index = 0
    while index < len(tokens):
        tok = tokens[index]
        if tok.type in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
            index += 1
            continue
        if tok.type == tokenize.COMMENT:
            index += 1
            continue
        if tok.type == tokenize.ENCODING:
            index += 1
            continue
        if tok.type == tokenize.ENDMARKER:
            break
        if tok.type in _COMPOUND_START_TYPES:
            compound, index = _read_compound_string(tokens, index, source_text, line_starts)
            end_line, end_col = tokens[index - 1].end if index > 0 else tok.end
            start_offset = _offset_for_position(line_starts, tok.start[0], tok.start[1])
            end_offset = _offset_for_position(line_starts, end_line, end_col)
            parts.append(
                IndexedToken(
                    bucket=f"STRING:{compound!r}",
                    start_line=tok.start[0],
                    start_col=tok.start[1],
                    end_line=end_line,
                    end_col=end_col,
                    start_offset=start_offset,
                    end_offset=end_offset,
                )
            )
            continue
        bucket = _token_bucket(tok)
        if bucket:
            parts.append(
                IndexedToken(
                    bucket=bucket,
                    start_line=tok.start[0],
                    start_col=tok.start[1],
                    end_line=tok.end[0],
                    end_col=tok.end[1],
                    start_offset=_offset_for_position(line_starts, tok.start[0], tok.start[1]),
                    end_offset=_offset_for_position(line_starts, tok.end[0], tok.end[1]),
                )
            )
        index += 1
    return parts


def normalize_token_stream(text: str) -> str:
    normalized = normalize_source_text(text)
    tokens = _safe_tokenize(normalized)
    line_starts = _line_starts_for_text(normalized)
    indexed = _build_normalized_tokens(tokens, normalized, line_starts)
    return " ".join(tok.bucket for tok in indexed)


def _line_starts_for_text(normalized: str) -> List[int]:
    lines = normalized.split("\n")
    line_starts: List[int] = []
    offset = 0
    for line in lines:
        line_starts.append(offset)
        offset += len(line) + 1
    return line_starts


def normalize_source_span(
    text: str, start_line: int, start_col: int, end_line: int, end_col: int
) -> str:
    index = build_source_index(text)
    return index.norm_for_span(start_line, start_col, end_line, end_col)


def _offset_for_position(line_starts: Sequence[int], line: int, column: int) -> int:
    return line_starts[line - 1] + column


def _read_compound_string(
    tokens: Sequence[tokenize.TokenInfo],
    start: int,
    source_text: str,
    line_starts: Sequence[int],
) -> Tuple[str, int]:
    tok = tokens[start]
    start_offset = _offset_for_position(line_starts, tok.start[0], tok.start[1])
    index = start + 1
    depth = 1
    expected_end = _COMPOUND_END_BY_START.get(tok.type, tok.type)
    while index < len(tokens) and depth > 0:
        current = tokens[index]
        if current.type == tokenize.ENDMARKER:
            break
        if current.type in _COMPOUND_START_TYPES:
            depth += 1
        elif current.type == expected_end:
            depth -= 1
            if depth == 0:
                end_offset = _offset_for_position(
                    line_starts,
                    current.end[0],
                    current.end[1],
                )
                return source_text[start_offset:end_offset], index + 1
        elif current.type in _COMPOUND_END_BY_START.values():
            depth = max(0, depth - 1)
        index += 1
    end_offset = _offset_for_position(line_starts, tok.end[0], tok.end[1])
    return source_text[start_offset:end_offset], start + 1


def _build_byte_column_map(line_text: str) -> Tuple[int, ...]:
    byte_length = len(line_text.encode("utf-8"))
    byte_map = [0] * (byte_length + 1)
    byte_offset = 0
    for char_index, char in enumerate(line_text):
        next_offset = byte_offset + len(char.encode("utf-8"))
        for index in range(byte_offset, next_offset):
            byte_map[index] = char_index
        byte_offset = next_offset
        byte_map[byte_offset] = char_index + 1
    return tuple(byte_map)


def _token_bucket(tok: tokenize.TokenInfo) -> Optional[str]:
    if tok.type == tokenize.NAME:
        return f"NAME:{tok.string}"
    if tok.type == tokenize.NUMBER:
        return f"NUMBER:{tok.string}"
    if tok.type == tokenize.STRING:
        return f"STRING:{tok.string!r}"
    if tok.type == tokenize.OP:
        return f"OP:{tok.string}"
    return None
