from typewitness.presentation.github import render_github
from typewitness.presentation.pretty import render_pretty
from typewitness.presentation.sources import (
    GITHUB_FINDING_CAP,
    PR_COMMENT_MARKER,
    CodeSnippet,
    PresentationContext,
    PresentedFinding,
    PresentedReport,
    extract_snippet,
    present_report,
    resolve_github_context,
    source_lines_from_text,
    suppression_hint,
)

__all__ = (
    "GITHUB_FINDING_CAP",
    "PR_COMMENT_MARKER",
    "CodeSnippet",
    "PresentationContext",
    "PresentedFinding",
    "PresentedReport",
    "extract_snippet",
    "present_report",
    "render_github",
    "render_pretty",
    "resolve_github_context",
    "source_lines_from_text",
    "suppression_hint",
)
