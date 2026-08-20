from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from typewitness.context import AnalysisContext
from typewitness.models import Finding
from typewitness.rules._cast_helpers import is_cast_target_any
from typewitness.rules._finding_helpers import candidate_finding, statement_safety_suppresses


@dataclass(frozen=True)
class CastToAnyRule:
    code: str = "TW005"
    name: str = "cast-to-any"

    def check(self, context: AnalysisContext) -> Tuple[Finding, ...]:
        findings: List[Finding] = []
        for candidate in context.candidates.cast_candidates:
            if statement_safety_suppresses(context, candidate, self.code):
                continue
            if not is_cast_target_any(candidate.type_arg, context, candidate):
                continue
            findings.append(
                candidate_finding(
                    context,
                    candidate,
                    code=self.code,
                    message="cast target is typing.Any",
                )
            )
        return tuple(findings)
