from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from typewitness.context import AnalysisContext
from typewitness.directives import (
    has_safety_reason,
    parse_inline_type_ignore_safety,
    safety_suppresses_rule,
    type_ignore_has_codes,
)
from typewitness.fingerprint import fingerprint_for_rule
from typewitness.models import Finding


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
                    safety_suppresses_rule(directive, self.code) for directive in safety_directives
                )
            )
            if type_ignore_has_codes(candidate.comment_text) and has_safety:
                continue
            findings.append(
                Finding(
                    code=self.code,
                    path=context.source.path,
                    range=candidate.source_range,
                    message="type: ignore comment missing codes or SAFETY evidence",
                    fingerprint=fingerprint_for_rule(
                        context.fingerprints,
                        ref=candidate.ref,
                        code=self.code,
                        path=context.source.path,
                        scope_path=candidate.scope_path,
                        candidate_norm=candidate.candidate_norm,
                        host_norm=candidate.host_norm,
                    ),
                )
            )
        return tuple(findings)
