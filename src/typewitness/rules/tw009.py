from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from typewitness.context import AnalysisContext
from typewitness.models import Finding
from typewitness.rules._finding_helpers import candidate_finding, statement_safety_suppresses


@dataclass(frozen=True)
class MockPatchCreateNeedsEvidenceRule:
    code: str = "TW009"
    name: str = "mock-patch-create-needs-evidence"

    def check(self, context: AnalysisContext) -> Tuple[Finding, ...]:
        findings: List[Finding] = []
        for candidate in context.candidates.mock_patch_candidates:
            if not candidate.has_literal_create_true:
                continue
            if statement_safety_suppresses(context, candidate, self.code):
                continue
            findings.append(
                candidate_finding(
                    context,
                    candidate,
                    code=self.code,
                    message="mock patch call with create=True missing SAFETY evidence",
                )
            )
        return tuple(findings)
