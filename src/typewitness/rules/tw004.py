from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import List, Tuple

from typewitness.context import AnalysisContext
from typewitness.models import Finding
from typewitness.rules._finding_helpers import candidate_finding, statement_safety_suppresses


@dataclass(frozen=True)
class NoWidenThenCastRule:
    code: str = "TW004"
    name: str = "no-widen-then-cast"

    def check(self, context: AnalysisContext) -> Tuple[Finding, ...]:
        if context.effects is None:
            return ()
        findings: List[Finding] = []
        for candidate in context.candidates.cast_candidates:
            if statement_safety_suppresses(context, candidate, self.code):
                continue
            if not isinstance(candidate.value_arg, ast.Name):
                continue
            if not context.effects.is_evidence_eligible(
                candidate.scope_index,
                candidate.value_arg.id,
                candidate.source_range.start.line,
                candidate.source_range.start.column,
            ):
                continue
            findings.append(
                candidate_finding(
                    context,
                    candidate,
                    code=self.code,
                    message="cast follows explicit Any/object widen of a literal binding",
                )
            )
        return tuple(findings)
