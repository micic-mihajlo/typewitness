from __future__ import annotations

from pathlib import Path

from tests._integration_support import (
    CAST_NO_EVIDENCE,
    CHAINED_CAST,
    REPO_ROOT,
    analyze_text,
    make_root,
    write_project,
)
from typewitness.models import AnalysisError, Finding
from typewitness.presentation import (
    GITHUB_FINDING_CAP,
    PR_COMMENT_MARKER,
    PresentationContext,
    extract_snippet,
    present_report,
    render_github,
    render_pretty,
    source_lines_from_text,
    suppression_hint,
)
from typewitness.project import discover_project
from typewitness.report import Report, render_json, render_sarif, render_text
from typewitness.settings import effective_output_format
from typewitness.source_index import build_source_index

LONG_LINE = "x = cast(int, '" + ("a" * 200) + "')\n"


def _context(root: Path) -> PresentationContext:
    return PresentationContext(project=discover_project(root))


def _report(findings: tuple[Finding, ...] = (), errors: tuple[AnalysisError, ...] = ()) -> Report:
    return Report(findings=findings, errors=errors)


def test_source_lines_match_source_index() -> None:
    text = "from typing import cast\r\n\r\nvalue = cast(int, 1)\n"
    assert source_lines_from_text(text) == build_source_index(text).lines


def test_extract_snippet_truncates_long_lines() -> None:
    text = "from typing import cast\n" + LONG_LINE
    finding = analyze_text("wide.py", text).findings[0]
    snippet = extract_snippet(text, finding.range.start.line, finding.range.start.column)
    assert snippet is not None
    assert all(len(line) <= 120 for line in snippet.lines)
    assert snippet.lines[snippet.highlight_line - 1].endswith("...")


def test_unreadable_file_yields_no_snippet(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_project(root, {})
    finding = analyze_text("missing.py", CAST_NO_EVIDENCE).findings[0]
    assert present_report(_report((finding,)), _context(root)).findings[0].snippet is None


def test_present_report_counts_and_path_order(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_project(root, {"a.py": CAST_NO_EVIDENCE, "b.py": CHAINED_CAST})
    findings = (
        *analyze_text("a.py", CAST_NO_EVIDENCE).findings,
        *analyze_text("b.py", CHAINED_CAST).findings,
    )
    presented = present_report(_report(findings), _context(root))
    assert presented.counts_by_code == (("TW001", 1), ("TW002", 2))
    assert presented.files_affected == 2
    assert [item.finding.path.as_posix() for item in presented.findings] == [
        "a.py",
        "b.py",
        "b.py",
    ]


def test_github_starts_with_marker(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_project(root, {"mod.py": CAST_NO_EVIDENCE})
    finding = analyze_text("mod.py", CAST_NO_EVIDENCE).findings[0]
    rendered = render_github(present_report(_report((finding,)), _context(root)))
    assert rendered.startswith(f"{PR_COMMENT_MARKER}\n")
    assert "| [TW002]" in rendered
    assert "—" not in rendered


def test_github_zero_findings_keeps_marker(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_project(root, {})
    rendered = render_github(present_report(_report(), _context(root)))
    assert rendered.startswith(f"{PR_COMMENT_MARKER}\n")
    assert "TypeWitness found 0 findings." in rendered


def test_github_caps_finding_bodies(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    findings = []
    files = {}
    extra = 5
    total = GITHUB_FINDING_CAP + extra
    for index in range(total):
        rel = f"f{index:02d}.py"
        files[rel] = CAST_NO_EVIDENCE
        findings.append(analyze_text(rel, CAST_NO_EVIDENCE).findings[0])
    write_project(root, files)
    rendered = render_github(present_report(_report(tuple(findings)), _context(root)))
    assert f"And {extra} more:" in rendered
    assert rendered.count("<details>") == 1


def test_pretty_groups_by_rule(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_project(root, {"mod.py": CHAINED_CAST})
    findings = analyze_text("mod.py", CHAINED_CAST).findings
    presented = present_report(_report(findings), _context(root))
    rendered = render_pretty(presented)
    assert "TW001" in rendered and "TW002" in rendered
    tw001_uri = next(item.help_uri for item in presented.findings if item.finding.code == "TW001")
    tw002_uri = next(item.help_uri for item in presented.findings if item.finding.code == "TW002")
    assert rendered.count(tw001_uri) == 1
    assert rendered.count(tw002_uri) == 1


def test_pretty_caret_sits_under_column(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_project(root, {"mod.py": CAST_NO_EVIDENCE})
    finding = analyze_text("mod.py", CAST_NO_EVIDENCE).findings[0]
    rendered = render_pretty(present_report(_report((finding,)), _context(root)))
    lines = rendered.splitlines()
    snippet_line = next(line for line in lines if line.endswith("value = cast(int, 1)"))
    caret_line = lines[lines.index(snippet_line) + 1]
    source_start = snippet_line.index("| ") + 2
    assert caret_line.index("^") - source_start == finding.range.start.column


def test_pretty_empty_findings_is_empty(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_project(root, {})
    assert render_pretty(present_report(_report(), _context(root))) == ""


def test_existing_renderers_unchanged_on_same_report(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_project(root, {"mod.py": CHAINED_CAST})
    report = _report(analyze_text("mod.py", CHAINED_CAST).findings)
    before = (render_text(report), render_json(report), render_sarif(report))
    present_report(report, _context(root))
    after = (render_text(report), render_json(report), render_sarif(report))
    assert before == after


def test_suppression_hint_rules() -> None:
    assert suppression_hint("TW001") is None
    assert suppression_hint("TW002") == "# SAFETY: <reason>"
    assert suppression_hint("TW005") == "# SAFETY[TW005]: <reason>"


def test_effective_output_format_tty_default() -> None:
    assert effective_output_format("text", None, None, True) == "pretty"
    assert effective_output_format("text", None, None, False) == "text"
    assert effective_output_format("json", "json", None, True) == "json"
    assert effective_output_format("github", None, "github", True) == "github"


def test_action_yml_posts_sticky_github_report() -> None:
    text = (REPO_ROOT / "action.yml").read_text(encoding="utf-8")
    assert PR_COMMENT_MARKER in text
    assert "--format github" in text
    assert "blocking" in text


def test_pr_workflow_uses_the_composite_action() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "typewitness-pr.yml").read_text(encoding="utf-8")
    assert "uses: ./" in text
    assert "blocking" in text
