from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from typewitness.context import AnalysisContext
from typewitness.models import Finding
from typewitness.rules._finding_helpers import candidate_finding, statement_safety_suppresses


@dataclass(frozen=True)
class DiscardedCastRule:
    code: str = "TW006"
    name: str = "discarded-cast"

    def check(self, context: AnalysisContext) -> Tuple[Finding, ...]:
        findings: List[Finding] = []
        for candidate in context.candidates.cast_candidates:
            if candidate.is_chain_child:
                continue
            if not candidate.is_entire_expr_value:
                continue
            if statement_safety_suppresses(context, candidate, self.code):
                continue
            findings.append(
                candidate_finding(
                    context,
                    candidate,
                    code=self.code,
                    message="cast result is discarded",
                )
            )
        return tuple(findings)
