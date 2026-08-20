from __future__ import annotations

from typing import List, Optional

from typewitness.presentation.sources import (
    MARKDOWN_FINDING_CAP,
    PR_COMMENT_MARKER,
    CodeSnippet,
    PresentedFinding,
    PresentedReport,
)
from typewitness.report import RULE_METADATA, escape_text_output


def render_markdown(report: PresentedReport) -> str:
    if not report.findings and not report.errors:
        return ""

    lines: List[str] = [PR_COMMENT_MARKER, ""]
    if report.findings:
        finding_noun = "finding" if len(report.findings) == 1 else "findings"
        file_noun = "file" if report.files_affected == 1 else "files"
        lines.append(
            f"TypeWitness found {len(report.findings)} {finding_noun} in "
            f"{report.files_affected} {file_noun}."
        )
        lines.append("")
        lines.append("| Rule | Count |")
        lines.append("| --- | ---: |")
        for code, count in report.counts_by_code:
            help_uri = RULE_METADATA[code].help_uri
            lines.append(f"| [{code}]({help_uri}) | {count} |")
        lines.append("")

        visible = report.findings[:MARKDOWN_FINDING_CAP]
        hidden = len(report.findings) - len(visible)
        findings_by_code: dict[str, list[PresentedFinding]] = {}
        for item in visible:
            findings_by_code.setdefault(item.finding.code, []).append(item)

        for code, _count in report.counts_by_code:
            group = findings_by_code.get(code)
            if not group:
                continue
            summary = f"{code} ({len(group)})"
            if group[0].experimental:
                summary += " experimental"
            lines.append("<details>")
            lines.append(f"<summary>{summary}</summary>")
            lines.append("")
            for item in group:
                lines.extend(_render_finding(item, report.compare_url))
            lines.append("</details>")
            lines.append("")

        if hidden > 0:
            lines.append(f"_...and {hidden} more_")
            lines.append("")

    if report.errors:
        lines.append("## Analysis errors")
        lines.append("")
        for error in report.errors:
            path = error.path.as_posix() if error.path is not None else "-"
            message = escape_text_output(error.message)
            lines.append(f"- `{escape_text_output(path)}` ({error.kind}) {message}")
        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines) + "\n"


def _render_finding(item: PresentedFinding, compare_url: Optional[str]) -> List[str]:
    finding = item.finding
    start = finding.range.start
    path = escape_text_output(finding.path.as_posix())
    location = f"{path}:{start.line}:{start.column + 1}"
    if compare_url is not None:
        location = f"[{location}]({compare_url}/{finding.path.as_posix()}#L{start.line})"
    heading = f"**{location}** `{finding.code}`"
    if item.experimental:
        heading += " (experimental)"
    lines = [
        heading,
        "",
        escape_text_output(item.summary),
        "",
    ]
    if item.snippet is not None:
        lines.extend(_render_snippet(item.snippet))
        lines.append("")
    if item.suppression is not None:
        lines.append(f"`{item.suppression}`")
        lines.append("")
    return lines


def _render_snippet(snippet: CodeSnippet) -> List[str]:
    width = max(len(str(snippet.start_line + len(snippet.lines) - 1)), 1)
    lines: List[str] = ["```python"]
    highlight_line_no = snippet.start_line + snippet.highlight_line - 1
    for offset, line in enumerate(snippet.lines):
        line_no = snippet.start_line + offset
        displayed = escape_text_output(line)
        prefix = ">" if line_no == highlight_line_no else " "
        lines.append(f"{prefix}{line_no:>{width}} | {displayed}")
    lines.append("```")
    return lines
