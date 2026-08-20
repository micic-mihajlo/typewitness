from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from typewitness.context import AnalysisContext
from typewitness.models import Finding
from typewitness.rules._finding_helpers import candidate_finding, statement_safety_suppresses


@dataclass(frozen=True)
class NoTypeCheckNeedsEvidenceRule:
    code: str = "TW008"
    name: str = "no-type-check-needs-evidence"

    def check(self, context: AnalysisContext) -> Tuple[Finding, ...]:
        findings: List[Finding] = []
        for candidate in context.candidates.no_type_check_candidates:
            if statement_safety_suppresses(context, candidate, self.code):
                continue
            findings.append(
                candidate_finding(
                    context,
                    candidate,
                    code=self.code,
                    message="no_type_check decorator missing SAFETY evidence",
                )
            )
        return tuple(findings)
