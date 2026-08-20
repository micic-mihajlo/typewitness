from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import List, Tuple

from typewitness.context import AnalysisContext
from typewitness.models import Finding
from typewitness.rules._finding_helpers import candidate_finding, statement_safety_suppresses


@dataclass(frozen=True)
class CastToTypeVarRule:
    code: str = "TW013"
    name: str = "cast-to-typevar"

    def check(self, context: AnalysisContext) -> Tuple[Finding, ...]:
        if context.typevar_index is None:
            return ()
        findings: List[Finding] = []
        for candidate in context.candidates.cast_candidates:
            if candidate.is_chain_child:
                continue
            if statement_safety_suppresses(context, candidate, self.code):
                continue
            if not isinstance(candidate.type_arg, ast.Name):
                continue
            line = candidate.source_range.start.line
            column = candidate.source_range.start.column
            if not context.typevar_index.is_proven_local_typevar(
                candidate.scope_index,
                candidate.type_arg.id,
                line,
                column,
            ):
                continue
            findings.append(
                candidate_finding(
                    context,
                    candidate,
                    code=self.code,
                    message="cast target is local TypeVar",
                )
            )
        return tuple(findings)
