from __future__ import annotations

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ANALYSIS_ERROR = 2
EXIT_USAGE_ERROR = 3


def resolve_exit_code(
    *,
    has_findings: bool,
    has_analysis_errors: bool,
    has_usage_error: bool = False,
) -> int:
    if has_usage_error:
        return EXIT_USAGE_ERROR
    if has_analysis_errors:
        return EXIT_ANALYSIS_ERROR
    if has_findings:
        return EXIT_FINDINGS
    return EXIT_OK
