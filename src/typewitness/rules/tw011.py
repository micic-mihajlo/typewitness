from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from typewitness.context import AnalysisContext
from typewitness.models import Finding
from typewitness.rules._cast_helpers import (
    is_cast_target_any_or_object,
    value_expr_has_boundary_root,
)
from typewitness.rules._finding_helpers import candidate_finding, statement_safety_suppresses


@dataclass(frozen=True)
class UnvalidatedBoundaryCastRule:
    code: str = "TW011"
    name: str = "unvalidated-boundary-cast"

    def check(self, context: AnalysisContext) -> Tuple[Finding, ...]:
        findings: List[Finding] = []
        for candidate in context.candidates.cast_candidates:
            if candidate.is_chain_child:
                continue
            if statement_safety_suppresses(context, candidate, self.code):
                continue
            if is_cast_target_any_or_object(candidate.type_arg, context, candidate):
                continue
            if not value_expr_has_boundary_root(candidate.value_arg, context, candidate):
                continue
            findings.append(
                candidate_finding(
                    context,
                    candidate,
                    code=self.code,
                    message="cast of unvalidated boundary parse",
                )
            )
        return tuple(findings)
