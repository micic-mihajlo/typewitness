from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from typewitness.catalog import RULE_BY_CODE, RULE_DESCRIPTORS
from typewitness.discovery import DEFAULT_MAX_FILE_BYTES, read_source
from typewitness.errors import FilesystemError
from typewitness.models import AnalysisError, Finding
from typewitness.project import Project
from typewitness.report import RULE_METADATA, Report
from typewitness.source_index import normalize_source_text

PR_COMMENT_MARKER = "<!-- typewitness-report:v1 -->"
SNIPPET_CONTEXT_LINES = 2
MAX_SNIPPET_LINE_WIDTH = 120
MARKDOWN_FINDING_CAP = 50


@dataclass(frozen=True)
class PresentationContext:
    project: Project
    compare_url: Optional[str] = None
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES


@dataclass(frozen=True)
class CodeSnippet:
    start_line: int
    lines: Tuple[str, ...]
    highlight_line: int
    highlight_column: int


@dataclass(frozen=True)
class PresentedFinding:
    finding: Finding
    summary: str
    help_uri: str
    snippet: Optional[CodeSnippet]
    suppression: Optional[str]
    experimental: bool


@dataclass(frozen=True)
class PresentedReport:
    findings: Tuple[PresentedFinding, ...]
    counts_by_code: Tuple[Tuple[str, int], ...]
    files_affected: int
    errors: Tuple[AnalysisError, ...]
    compare_url: Optional[str] = None


def source_lines_from_text(text: str) -> Tuple[str, ...]:
    return tuple(normalize_source_text(text).split("\n"))


def suppression_hint(code: str) -> Optional[str]:
    descriptor = RULE_BY_CODE.get(code)
    if descriptor is None or not descriptor.suppressible:
        return None
    if descriptor.scoped_only_suppression:
        return f"# SAFETY[{code}]: <reason>"
    return "# SAFETY: <reason>"


def resolve_github_context() -> Optional[str]:
    repository = os.environ.get("TYPEWITNESS_GITHUB_REPOSITORY") or os.environ.get(
        "GITHUB_REPOSITORY"
    )
    sha = (
        os.environ.get("TYPEWITNESS_GITHUB_SHA")
        or os.environ.get("GITHUB_PR_SHA")
        or os.environ.get("GITHUB_SHA")
    )
    if repository is None or sha is None:
        return None
    return f"https://github.com/{repository}/blob/{sha}"


def extract_snippet(text: str, line: int, column: int) -> Optional[CodeSnippet]:
    lines = source_lines_from_text(text)
    if line < 1 or line > len(lines):
        return None

    start = max(1, line - SNIPPET_CONTEXT_LINES)
    end = min(len(lines), line + SNIPPET_CONTEXT_LINES)
    snippet_lines = tuple(_truncate_line(lines[index - 1]) for index in range(start, end + 1))
    highlight_index = line - start
    highlight_column = min(max(column, 0), len(snippet_lines[highlight_index]))
    return CodeSnippet(
        start_line=start,
        lines=snippet_lines,
        highlight_line=line - start + 1,
        highlight_column=highlight_column,
    )


def _truncate_line(line: str) -> str:
    if len(line) <= MAX_SNIPPET_LINE_WIDTH:
        return line
    return line[: MAX_SNIPPET_LINE_WIDTH - 3] + "..."


def _present_finding(
    context: PresentationContext,
    finding: Finding,
    source_cache: Dict[str, Optional[str]],
) -> PresentedFinding:
    metadata = RULE_METADATA[finding.code]
    snippet: Optional[CodeSnippet] = None
    cache_key = finding.path.as_posix()
    if cache_key not in source_cache:
        try:
            read_result = read_source(
                context.project,
                context.project.resolve(cache_key),
                max_file_bytes=context.max_file_bytes,
            )
        except FilesystemError:
            source_cache[cache_key] = None
        else:
            if read_result.source is None:
                source_cache[cache_key] = None
            else:
                source_cache[cache_key] = read_result.source.text

    source_text = source_cache[cache_key]
    if source_text is not None:
        snippet = extract_snippet(
            source_text,
            finding.range.start.line,
            finding.range.start.column,
        )

    return PresentedFinding(
        finding=finding,
        summary=metadata.summary,
        help_uri=metadata.help_uri,
        snippet=snippet,
        suppression=suppression_hint(finding.code),
        experimental=metadata.experimental,
    )


def present_report(report: Report, context: PresentationContext) -> PresentedReport:
    effective_context = context
    if effective_context.compare_url is None:
        compare_url = resolve_github_context()
        if compare_url is not None:
            effective_context = PresentationContext(
                project=context.project,
                compare_url=compare_url,
                max_file_bytes=context.max_file_bytes,
            )

    catalog_order = {descriptor.code: index for index, descriptor in enumerate(RULE_DESCRIPTORS)}

    def sort_key(finding: Finding) -> Tuple[int, str, int, int, str]:
        return (
            catalog_order.get(finding.code, len(RULE_DESCRIPTORS)),
            finding.path.as_posix(),
            finding.range.start.line,
            finding.range.start.column,
            finding.fingerprint,
        )

    sorted_findings = tuple(sorted(report.findings, key=sort_key))
    counts = Counter(finding.code for finding in sorted_findings)
    counts_by_code = tuple(
        (descriptor.code, counts[descriptor.code])
        for descriptor in RULE_DESCRIPTORS
        if counts[descriptor.code] > 0
    )
    files_affected = len({finding.path.as_posix() for finding in sorted_findings})
    source_cache: Dict[str, Optional[str]] = {}
    presented = tuple(
        _present_finding(effective_context, finding, source_cache) for finding in sorted_findings
    )
    return PresentedReport(
        findings=presented,
        counts_by_code=counts_by_code,
        files_affected=files_affected,
        errors=report.errors,
        compare_url=effective_context.compare_url,
    )
