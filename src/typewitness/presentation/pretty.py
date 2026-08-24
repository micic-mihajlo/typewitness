from __future__ import annotations

from typing import List

from typewitness.presentation.sources import CodeSnippet, PresentedFinding, PresentedReport
from typewitness.report import escape_text_output


def render_pretty(report: PresentedReport) -> str:
    if not report.findings:
        return ""

    finding_noun = "finding" if len(report.findings) == 1 else "findings"
    file_noun = "file" if report.files_affected == 1 else "files"
    header = (
        f"TypeWitness found {len(report.findings)} {finding_noun} "
        f"in {report.files_affected} {file_noun}"
    )
    lines: List[str] = [header]

    findings_by_code: dict[str, list[PresentedFinding]] = {}
    for item in report.findings:
        findings_by_code.setdefault(item.finding.code, []).append(item)

    for code, count in report.counts_by_code:
        group = findings_by_code[code]
        label = f"{code}  {count}"
        if group[0].experimental:
            label += "  (experimental)"
        lines.append(label)
        lines.append(f"  {group[0].help_uri}")
        lines.append("")
        for item in group:
            lines.extend(_render_finding(item))
            lines.append("")

    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines) + "\n"


def _render_finding(item: PresentedFinding) -> List[str]:
    finding = item.finding
    start = finding.range.start
    path = escape_text_output(finding.path.as_posix())
    message = escape_text_output(finding.message)
    location = f"{path}:{start.line}:{start.column + 1}"
    lines = [
        f"{location}  {finding.code}  {message}",
        f"  {item.summary}",
    ]
    if item.snippet is not None:
        lines.extend(_render_snippet(item.snippet))
    if item.suppression is not None:
        lines.append(f"  {item.suppression}")
    return lines


def _render_snippet(snippet: CodeSnippet) -> List[str]:
    lines: List[str] = []
    width = max(len(str(snippet.start_line + len(snippet.lines) - 1)), 1)
    gutter = 4 + width + 3
    highlight_line_no = snippet.start_line + snippet.highlight_line - 1
    for offset, line in enumerate(snippet.lines):
        line_no = snippet.start_line + offset
        displayed = escape_text_output(line)
        lines.append(f"    {line_no:>{width}} | {displayed}")
        if line_no == highlight_line_no:
            caret_column = _display_column(line, snippet.highlight_column)
            caret_column = min(max(caret_column, 0), len(displayed))
            lines.append(f"{' ' * (gutter + caret_column)}^")
    return lines


def _display_column(line: str, column: int) -> int:
    if column <= 0:
        return 0
    return len(escape_text_output(line[:column]))
