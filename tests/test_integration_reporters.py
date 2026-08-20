"""Output format contracts: text, JSON, and SARIF 2.1.0.

These assert schemas and ordering, not golden blobs. The findings under test come from the
real core so message text and positions never drift away from the analyzer.

Column bases differ on purpose and are asserted explicitly:

* the core and the JSON document use 0-based character columns,
* the text format prints 1-based columns for humans and editors,
* SARIF requires 1-based columns.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from tests._integration_support import (
    CAST_NO_EVIDENCE,
    CHAINED_CAST,
    REPO_ROOT,
    analyze_text,
)
from typewitness.models import DEFAULT_RULESET, VALID_RULE_CODES, AnalysisError, Finding
from typewitness.report import (
    DOCS_BASE_URL,
    JSON_SCHEMA,
    RULE_METADATA,
    SARIF_SCHEMA_URI,
    SARIF_VERSION,
    TOOL_NAME,
    TOOL_VERSION,
    Report,
    render_errors_text,
    render_json,
    render_sarif,
    render_text,
)
from typewitness.rules import RULES

ANSI = re.compile("\x1b\\[")


def _findings(path: str = "pkg/mod.py", text: str = CAST_NO_EVIDENCE) -> Tuple[Finding, ...]:
    result = analyze_text(path, text)
    assert result.findings, "fixture must produce findings"
    return result.findings


def _report(**kwargs: Any) -> Report:
    findings = kwargs.pop("findings", _findings())
    errors = kwargs.pop("errors", ())
    assert not kwargs
    return Report(findings=findings, errors=errors)


def _sarif(report: Report) -> Dict[str, Any]:
    payload = json.loads(render_sarif(report))
    assert isinstance(payload, dict)
    return payload


def _json(report: Report) -> Dict[str, Any]:
    payload = json.loads(render_json(report))
    assert isinstance(payload, dict)
    return payload


# --------------------------------------------------------------------------- metadata


def test_tool_identity() -> None:
    assert TOOL_NAME == "typewitness"
    assert DOCS_BASE_URL == "https://github.com/micic-mihajlo/typewitness"
    assert re.fullmatch(r"\d+\.\d+\.\d+", TOOL_VERSION)


def test_rule_metadata_covers_every_rule_code() -> None:
    assert set(RULE_METADATA) == set(VALID_RULE_CODES)
    assert tuple(RULE_METADATA) == tuple(sorted(RULE_METADATA))


def test_rule_metadata_names_match_the_rule_implementations() -> None:
    implemented = {rule.code: rule.name for rule in RULES}

    for code, metadata in RULE_METADATA.items():
        assert metadata.code == code
        assert metadata.name == implemented[code]


def test_rule_metadata_default_enabled_matches_the_core_ruleset() -> None:
    for code, metadata in RULE_METADATA.items():
        assert metadata.default_enabled is (code in DEFAULT_RULESET)


def test_only_tw004_is_marked_experimental() -> None:
    experimental = {code for code, meta in RULE_METADATA.items() if meta.experimental}

    assert experimental == {"TW004"}


def test_rule_metadata_levels() -> None:
    for code, metadata in RULE_METADATA.items():
        expected = "note" if metadata.experimental else "warning"
        assert metadata.level == expected, code


def test_rule_help_uris_point_at_the_github_readme() -> None:
    for code, metadata in RULE_METADATA.items():
        assert metadata.help_uri.startswith(DOCS_BASE_URL + "#")
        assert code.lower() in metadata.help_uri


def test_rule_help_uri_anchors_exist_in_the_readme() -> None:
    """A dead documentation link is worse than no link, so the anchors are checked."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    anchors = set()
    for line in readme.splitlines():
        if not line.startswith("#"):
            continue
        heading = line.lstrip("#").strip()
        slug = "".join(
            char if (char.isalnum() or char in "-_") else ("-" if char == " " else "")
            for char in heading.lower()
        )
        anchors.add(slug)

    for code, metadata in RULE_METADATA.items():
        anchor = metadata.help_uri.split("#", 1)[1]
        assert anchor in anchors, f"{code} help anchor {anchor!r} is not a README heading"


def test_rule_summaries_are_present_and_single_line() -> None:
    for code, metadata in RULE_METADATA.items():
        assert metadata.summary.strip()
        assert "\n" not in metadata.summary, code


# ------------------------------------------------------------------------------- text


def test_text_format_is_one_line_per_finding_with_1_based_columns() -> None:
    findings = _findings(text=CHAINED_CAST)
    report = _report(findings=findings)

    lines = render_text(report).splitlines()

    assert len(lines) == len(findings)
    for line, finding in zip(lines, findings):
        expected = (
            f"{finding.path.as_posix()}:{finding.range.start.line}:"
            f"{finding.range.start.column + 1}: {finding.code} {finding.message}"
        )
        assert line == expected


def test_text_format_ends_with_a_single_newline() -> None:
    rendered = render_text(_report())

    assert rendered.endswith("\n")
    assert not rendered.endswith("\n\n")


def test_text_format_of_an_empty_report_is_empty() -> None:
    assert render_text(Report(findings=(), errors=())) == ""
    assert render_errors_text(Report(findings=(), errors=())) == ""


def test_text_format_has_no_summary_line_and_no_colour() -> None:
    findings = _findings(text=CHAINED_CAST)

    rendered = render_text(_report(findings=findings))

    assert len(rendered.splitlines()) == len(findings)
    assert not ANSI.search(rendered)


def test_text_format_is_sorted_independently_of_input_order() -> None:
    findings = _findings(text=CHAINED_CAST)
    forward = render_text(_report(findings=findings))
    reversed_order = render_text(_report(findings=tuple(reversed(findings))))

    assert forward == reversed_order


def test_error_text_names_the_kind_and_path() -> None:
    error = AnalysisError(kind="parse", path=Path("pkg/bad.py"), message="invalid syntax")

    rendered = render_errors_text(Report(findings=(), errors=(error,)))

    assert rendered == "pkg/bad.py: parse: invalid syntax\n"


def test_error_text_handles_a_missing_path() -> None:
    error = AnalysisError(kind="internal", path=None, message="boom")

    rendered = render_errors_text(Report(findings=(), errors=(error,)))

    assert rendered == "-: internal: boom\n"


# ------------------------------------------------------------------------------- JSON


def test_json_top_level_schema_is_exact() -> None:
    payload = _json(_report())

    assert set(payload) == {"schema", "tool", "version", "findings", "errors"}
    assert payload["schema"] == JSON_SCHEMA == "typewitness-json-1"
    assert payload["tool"] == TOOL_NAME
    assert payload["version"] == TOOL_VERSION


def test_json_finding_schema_is_exact_and_uses_core_columns() -> None:
    findings = _findings(text=CHAINED_CAST)
    payload = _json(_report(findings=findings))

    assert len(payload["findings"]) == len(findings)
    for entry, finding in zip(payload["findings"], findings):
        assert set(entry) == {
            "code",
            "path",
            "line",
            "column",
            "end_line",
            "end_column",
            "message",
            "fingerprint",
        }
        assert entry["code"] == finding.code
        assert entry["path"] == finding.path.as_posix()
        assert entry["line"] == finding.range.start.line
        assert entry["column"] == finding.range.start.column
        assert entry["end_line"] == finding.range.end.line
        assert entry["end_column"] == finding.range.end.column
        assert entry["message"] == finding.message
        assert entry["fingerprint"] == finding.fingerprint


def test_json_error_schema_is_exact() -> None:
    error = AnalysisError(kind="parse", path=Path("pkg/bad.py"), message="invalid syntax")

    payload = _json(Report(findings=(), errors=(error,)))

    assert payload["errors"] == [
        {"kind": "parse", "path": "pkg/bad.py", "message": "invalid syntax"}
    ]


def test_json_error_path_is_null_when_absent() -> None:
    error = AnalysisError(kind="internal", path=None, message="boom")

    payload = _json(Report(findings=(), errors=(error,)))

    assert payload["errors"][0]["path"] is None


def test_json_render_is_byte_stable() -> None:
    report = _report(findings=_findings(text=CHAINED_CAST))

    assert render_json(report) == render_json(report)


def test_json_order_is_independent_of_input_order() -> None:
    findings = _findings(text=CHAINED_CAST)

    forward = render_json(_report(findings=findings))
    backward = render_json(_report(findings=tuple(reversed(findings))))

    assert forward == backward


def test_json_ends_with_a_newline() -> None:
    assert render_json(_report()).endswith("\n")


def test_json_of_an_empty_report_is_still_a_valid_document() -> None:
    payload = _json(Report(findings=(), errors=()))

    assert payload["findings"] == []
    assert payload["errors"] == []


def test_json_paths_are_relative_posix() -> None:
    payload = _json(_report(findings=_findings(path="src dir/caf\u00e9/mod.py")))

    for entry in payload["findings"]:
        assert entry["path"] == "src dir/caf\u00e9/mod.py"


# ------------------------------------------------------------------------------ SARIF


def test_sarif_envelope() -> None:
    payload = _sarif(_report())

    assert set(payload) == {"$schema", "version", "runs"}
    assert payload["version"] == SARIF_VERSION == "2.1.0"
    assert payload["$schema"] == SARIF_SCHEMA_URI
    assert "sarif-2.1.0" in SARIF_SCHEMA_URI
    assert len(payload["runs"]) == 1


def test_sarif_driver_metadata() -> None:
    driver = _sarif(_report())["runs"][0]["tool"]["driver"]

    assert driver["name"] == TOOL_NAME
    assert driver["version"] == TOOL_VERSION
    assert driver["semanticVersion"] == TOOL_VERSION
    assert driver["informationUri"] == DOCS_BASE_URL


def test_sarif_declares_unicode_code_point_columns() -> None:
    """The core reports character columns, so the run must say so rather than imply UTF-16."""
    run = _sarif(_report())["runs"][0]

    assert run["columnKind"] == "unicodeCodePoints"


def test_sarif_rule_descriptors_cover_every_rule() -> None:
    rules = _sarif(_report())["runs"][0]["tool"]["driver"]["rules"]

    assert [rule["id"] for rule in rules] == sorted(RULE_METADATA)
    for rule in rules:
        metadata = RULE_METADATA[rule["id"]]
        assert set(rule) == {
            "id",
            "name",
            "shortDescription",
            "helpUri",
            "defaultConfiguration",
            "properties",
        }
        assert rule["name"] == metadata.name
        assert rule["shortDescription"] == {"text": metadata.summary}
        assert rule["helpUri"] == metadata.help_uri
        assert rule["defaultConfiguration"] == {"level": metadata.level}
        assert "tags" in rule["properties"]
        assert rule["properties"]["defaultEnabled"] is metadata.default_enabled


def test_sarif_result_schema_and_1_based_columns() -> None:
    findings = _findings(text=CHAINED_CAST)
    results = _sarif(_report(findings=findings))["runs"][0]["results"]

    assert len(results) == len(findings)
    for result, finding in zip(results, findings):
        assert set(result) == {
            "ruleId",
            "level",
            "message",
            "locations",
            "partialFingerprints",
        }
        assert result["ruleId"] == finding.code
        assert result["level"] == RULE_METADATA[finding.code].level
        assert result["message"] == {"text": finding.message}
        region = result["locations"][0]["physicalLocation"]["region"]
        assert region["startLine"] == finding.range.start.line
        assert region["startColumn"] == finding.range.start.column + 1
        assert region["endLine"] == finding.range.end.line
        assert region["endColumn"] == finding.range.end.column + 1
        assert region["startColumn"] >= 1


def test_sarif_artifact_location_is_repo_relative_posix() -> None:
    findings = _findings(path="src dir/caf\u00e9/mod.py")
    results = _sarif(_report(findings=findings))["runs"][0]["results"]

    artifact = results[0]["locations"][0]["physicalLocation"]["artifactLocation"]

    assert artifact["uri"] == "src dir/caf\u00e9/mod.py"
    assert artifact["uriBaseId"] == "SRCROOT"


def test_sarif_partial_fingerprints_carry_the_stable_fingerprint() -> None:
    findings = _findings()
    results = _sarif(_report(findings=findings))["runs"][0]["results"]

    for result, finding in zip(results, findings):
        assert result["partialFingerprints"] == {"typewitness/v1": finding.fingerprint}


def test_sarif_invocation_is_successful_without_analysis_errors() -> None:
    invocation = _sarif(_report())["runs"][0]["invocations"][0]

    assert invocation["executionSuccessful"] is True
    assert invocation["toolExecutionNotifications"] == []


def test_sarif_analysis_errors_become_tool_execution_notifications() -> None:
    errors = (
        AnalysisError(kind="parse", path=Path("pkg/bad.py"), message="invalid syntax"),
        AnalysisError(kind="internal", path=None, message="boom"),
    )

    invocation = _sarif(Report(findings=(), errors=errors))["runs"][0]["invocations"][0]

    assert invocation["executionSuccessful"] is False
    notifications = invocation["toolExecutionNotifications"]
    assert len(notifications) == 2
    assert notifications[0]["level"] == "error"
    assert notifications[0]["descriptor"] == {"id": "parse"}
    assert notifications[0]["message"] == {"text": "invalid syntax"}
    location = notifications[0]["locations"][0]["physicalLocation"]["artifactLocation"]
    assert location["uri"] == "pkg/bad.py"
    assert notifications[1]["descriptor"] == {"id": "internal"}
    assert "locations" not in notifications[1]


def test_sarif_render_is_byte_stable_and_order_independent() -> None:
    findings = _findings(text=CHAINED_CAST)

    forward = render_sarif(_report(findings=findings))
    backward = render_sarif(_report(findings=tuple(reversed(findings))))

    assert forward == render_sarif(_report(findings=findings))
    assert forward == backward


def test_sarif_of_an_empty_report_is_still_valid() -> None:
    payload = _sarif(Report(findings=(), errors=()))

    assert payload["runs"][0]["results"] == []
    assert payload["runs"][0]["invocations"][0]["executionSuccessful"] is True


def test_sarif_ends_with_a_newline() -> None:
    assert render_sarif(_report()).endswith("\n")


@pytest.mark.parametrize("renderer", [render_text, render_json, render_sarif])
def test_renderers_never_emit_ansi_escapes(renderer: Any) -> None:
    report = _report(
        findings=_findings(text=CHAINED_CAST),
        errors=(AnalysisError(kind="parse", path=Path("a.py"), message="bad"),),
    )

    assert not ANSI.search(renderer(report))


def test_report_is_frozen_and_hashable() -> None:
    report = _report()

    assert hash(report) == hash(_report())
    assert report == _report()


def test_reports_carry_no_absolute_paths() -> None:
    """Absolute paths in output leak the build machine and break fingerprint stability."""
    report = _report(findings=_findings(text=CHAINED_CAST))
    blobs: List[str] = [render_text(report), render_json(report), render_sarif(report)]

    for blob in blobs:
        assert str(REPO_ROOT) not in blob
        assert "/private/var" not in blob
