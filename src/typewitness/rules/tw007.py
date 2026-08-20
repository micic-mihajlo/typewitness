from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from typewitness.context import AnalysisContext
from typewitness.disable_directives import preceding_comment_safety_suppresses_rule
from typewitness.models import Finding
from typewitness.rules._finding_helpers import candidate_finding


@dataclass(frozen=True)
class CheckerDisableNeedsEvidenceRule:
    code: str = "TW007"
    name: str = "checker-disable-needs-evidence"

    def check(self, context: AnalysisContext) -> Tuple[Finding, ...]:
        findings: List[Finding] = []
        for candidate in context.candidates.checker_disable_candidates:
            if preceding_comment_safety_suppresses_rule(
                context.source_index,
                candidate.comment_line,
                self.code,
            ):
                continue
            findings.append(
                candidate_finding(
                    context,
                    candidate,
                    code=self.code,
                    message="checker disable comment missing SAFETY evidence",
                )
            )
        return tuple(findings)
