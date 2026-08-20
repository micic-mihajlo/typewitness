from typewitness.presentation.markdown import render_markdown
from typewitness.presentation.pretty import render_pretty
from typewitness.presentation.sources import (
    MARKDOWN_FINDING_CAP,
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
    "MARKDOWN_FINDING_CAP",
    "PR_COMMENT_MARKER",
    "CodeSnippet",
    "PresentationContext",
    "PresentedFinding",
    "PresentedReport",
    "extract_snippet",
    "present_report",
    "render_markdown",
    "render_pretty",
    "resolve_github_context",
    "source_lines_from_text",
    "suppression_hint",
)
