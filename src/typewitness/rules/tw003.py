from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from typewitness.context import AnalysisContext
from typewitness.directives import (
    evidence_suppresses_rule,
    has_safety_reason,
    parse_inline_type_ignore_safety,
    type_ignore_has_codes,
)
from typewitness.models import Finding
from typewitness.rules._finding_helpers import candidate_finding


@dataclass(frozen=True)
class TypedIgnoreNeedsEvidenceRule:
    code: str = "TW003"
    name: str = "typed-ignore-needs-evidence"

    def check(self, context: AnalysisContext) -> Tuple[Finding, ...]:
        findings: List[Finding] = []
        for candidate in context.candidates.ignore_candidates:
            inline_reason = parse_inline_type_ignore_safety(candidate.comment_text)
            safety_directives = context.source_index.safety_for_statement(
                candidate.comment_line,
                candidate.comment_line,
            )
            has_safety = (
                inline_reason is not None
                or has_safety_reason(candidate.comment_text)
                or any(
                    evidence_suppresses_rule(directive, self.code)
                    for directive in safety_directives
                )
            )
            if type_ignore_has_codes(candidate.comment_text) and has_safety:
                continue
            findings.append(
                candidate_finding(
                    context,
                    candidate,
                    code=self.code,
                    message="type: ignore comment missing codes or SAFETY evidence",
                )
            )
        return tuple(findings)
