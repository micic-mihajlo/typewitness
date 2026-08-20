from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Sequence, Tuple

from typewitness._version import tool_version
from typewitness.catalog import DOCS_BASE_URL, RULE_DESCRIPTORS
from typewitness.models import AnalysisError, Finding
from typewitness.rules import RULES

TOOL_NAME = "typewitness"
TOOL_VERSION = tool_version()
JSON_SCHEMA = "typewitness-json-1"
SARIF_VERSION = "2.1.0"
SARIF_SCHEMA_URI = "https://json.schemastore.org/sarif-2.1.0.json"


def escape_text_output(text: str) -> str:
    out: list[str] = []
    for char in text:
        code = ord(char)
        category = unicodedata.category(char)
        if code < 32 or code == 127 or 0x80 <= code <= 0x9F:
            out.append(f"\\x{code:02x}")
        elif (
            category == "Cf"
            or code in {0x2028, 0x2029}
            or 0x202A <= code <= 0x202E
            or code
            in {
                0x061C,
                0x2066,
                0x2067,
                0x2068,
                0x2069,
                0xFEFF,
                0x200D,
                0x200E,
                0x200F,
            }
        ):
            out.append(f"\\u{code:04x}")
        else:
            out.append(char)
    return "".join(out)


@dataclass(frozen=True)
class RuleMetadata:
    code: str
    name: str
    summary: str
    help_uri: str
    level: str
    default_enabled: bool
    experimental: bool


def _build_rule_metadata() -> Dict[str, RuleMetadata]:
    implemented = {rule.code: rule for rule in RULES}
    metadata: Dict[str, RuleMetadata] = {}
    for descriptor in RULE_DESCRIPTORS:
        rule = implemented[descriptor.code]
        metadata[descriptor.code] = RuleMetadata(
            code=descriptor.code,
            name=rule.name,
            summary=descriptor.summary,
            help_uri=descriptor.help_uri,
            level=descriptor.level,
            default_enabled=descriptor.default_enabled,
            experimental=descriptor.experimental,
        )
    return metadata


RULE_METADATA: Dict[str, RuleMetadata] = _build_rule_metadata()

__all__ = (
    "DOCS_BASE_URL",
    "JSON_SCHEMA",
    "RULE_METADATA",
    "Report",
    "RuleMetadata",
    "SARIF_SCHEMA_URI",
    "SARIF_VERSION",
    "TOOL_NAME",
    "TOOL_VERSION",
    "escape_text_output",
    "render_errors_text",
    "render_json",
    "render_sarif",
    "render_text",
)


@dataclass(frozen=True)
class Report:
    findings: Tuple[Finding, ...]
    errors: Tuple[AnalysisError, ...]


def _finding_sort_key(finding: Finding) -> Tuple[str, int, int, str, str]:
    return (
        finding.path.as_posix(),
        finding.range.start.line,
        finding.range.start.column,
        finding.code,
        finding.fingerprint,
    )


def _sorted_findings(findings: Sequence[Finding]) -> Tuple[Finding, ...]:
    return tuple(sorted(findings, key=_finding_sort_key))


def render_text(report: Report) -> str:
    lines: list[str] = []
    for finding in _sorted_findings(report.findings):
        start = finding.range.start
        path = escape_text_output(finding.path.as_posix())
        message = escape_text_output(finding.message)
        lines.append(f"{path}:{start.line}:{start.column + 1}: {finding.code} {message}")
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def render_errors_text(report: Report) -> str:
    lines: list[str] = []
    for error in report.errors:
        path = escape_text_output(error.path.as_posix()) if error.path is not None else "-"
        kind = escape_text_output(error.kind)
        message = escape_text_output(error.message)
        lines.append(f"{path}: {kind}: {message}")
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def render_json(report: Report) -> str:
    payload = {
        "schema": JSON_SCHEMA,
        "tool": TOOL_NAME,
        "version": TOOL_VERSION,
        "findings": [
            {
                "code": finding.code,
                "path": finding.path.as_posix(),
                "line": finding.range.start.line,
                "column": finding.range.start.column,
                "end_line": finding.range.end.line,
                "end_column": finding.range.end.column,
                "message": finding.message,
                "fingerprint": finding.fingerprint,
            }
            for finding in _sorted_findings(report.findings)
        ],
        "errors": [
            {
                "kind": error.kind,
                "path": error.path.as_posix() if error.path is not None else None,
                "message": error.message,
            }
            for error in report.errors
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def render_sarif(report: Report) -> str:
    rules = []
    for code in sorted(RULE_METADATA):
        metadata = RULE_METADATA[code]
        tags = ["experimental"] if metadata.experimental else []
        rules.append(
            {
                "id": code,
                "name": metadata.name,
                "shortDescription": {"text": metadata.summary},
                "helpUri": metadata.help_uri,
                "defaultConfiguration": {"level": metadata.level},
                "properties": {
                    "tags": tags,
                    "defaultEnabled": metadata.default_enabled,
                },
            }
        )

    results = []
    for finding in _sorted_findings(report.findings):
        metadata = RULE_METADATA[finding.code]
        results.append(
            {
                "ruleId": finding.code,
                "level": metadata.level,
                "message": {"text": finding.message},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": finding.path.as_posix(),
                                "uriBaseId": "SRCROOT",
                            },
                            "region": {
                                "startLine": finding.range.start.line,
                                "startColumn": finding.range.start.column + 1,
                                "endLine": finding.range.end.line,
                                "endColumn": finding.range.end.column + 1,
                            },
                        }
                    }
                ],
                "partialFingerprints": {"typewitness/v1": finding.fingerprint},
            }
        )

    notifications = []
    for error in report.errors:
        notification: Dict[str, Any] = {
            "level": "error",
            "descriptor": {"id": error.kind},
            "message": {"text": error.message},
        }
        if error.path is not None:
            notification["locations"] = [
                {
                    "physicalLocation": {
                        "artifactLocation": {
                            "uri": error.path.as_posix(),
                            "uriBaseId": "SRCROOT",
                        }
                    }
                }
            ]
        notifications.append(notification)

    payload = {
        "$schema": SARIF_SCHEMA_URI,
        "version": SARIF_VERSION,
        "runs": [
            {
                "columnKind": "unicodeCodePoints",
                "originalUriBaseIds": {
                    "SRCROOT": {
                        "uri": "file:///src/",
                    }
                },
                "tool": {
                    "driver": {
                        "name": TOOL_NAME,
                        "version": TOOL_VERSION,
                        "semanticVersion": TOOL_VERSION,
                        "informationUri": DOCS_BASE_URL,
                        "rules": rules,
                    }
                },
                "results": results,
                "invocations": [
                    {
                        "executionSuccessful": not report.errors,
                        "toolExecutionNotifications": notifications,
                    }
                ],
            }
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
