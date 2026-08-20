from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from typewitness.context import AnalysisContext
from typewitness.models import Finding
from typewitness.rules._finding_helpers import candidate_finding
from typewitness.rules._narrowing_helpers import should_report_constant_narrowing


@dataclass(frozen=True)
class ConstantTypeGuardRule:
    code: str = "TW010"
    name: str = "constant-type-guard"

    def check(self, context: AnalysisContext) -> Tuple[Finding, ...]:
        findings: List[Finding] = []
        for candidate in context.candidates.narrowing_function_candidates:
            if not should_report_constant_narrowing(context, candidate, self.code):
                continue
            findings.append(
                candidate_finding(
                    context,
                    candidate,
                    code=self.code,
                    message="narrowing function body is only return True or return False",
                )
            )
        return tuple(findings)
