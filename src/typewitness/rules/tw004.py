from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import List, Optional, Tuple

from typewitness.context import AnalysisContext
from typewitness.directives import safety_suppresses_rule
from typewitness.fingerprint import fingerprint_for_rule
from typewitness.models import Finding


@dataclass(frozen=True)
class NoWidenThenCastRule:
    code: str = "TW004"
    name: str = "no-widen-then-cast"

    def check(self, context: AnalysisContext) -> Tuple[Finding, ...]:
        if context.effects is None:
            return ()
        findings: List[Finding] = []
        for candidate in context.candidates.cast_candidates:
            safety_directives = context.source_index.safety_for_statement(
                candidate.source_range.start.line,
                candidate.source_range.end.line,
            )
            if any(
                directive.scoped_codes and safety_suppresses_rule(directive, self.code)
                for directive in safety_directives
            ):
                continue
            value_node = _value_name_node(candidate.node)
            if value_node is None:
                continue
            if not context.effects.is_evidence_eligible(
                candidate.scope_index,
                value_node.id,
                candidate.source_range.start.line,
                candidate.source_range.start.column,
            ):
                continue
            findings.append(
                Finding(
                    code=self.code,
                    path=context.source.path,
                    range=candidate.source_range,
                    message="cast follows explicit Any/object widen of a literal binding",
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


def _value_name_node(node: ast.Call) -> Optional[ast.Name]:
    value_arg: Optional[ast.expr] = None
    if len(node.args) >= 2:
        value_arg = node.args[1]
    elif len(node.args) == 1:
        value_arg = node.args[0]
    for keyword in node.keywords:
        if keyword.arg == "val":
            value_arg = keyword.value
    if isinstance(value_arg, ast.Name):
        return value_arg
    return None
