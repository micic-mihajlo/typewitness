from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from typewitness.context import AnalysisContext
from typewitness.directives import safety_suppresses_rule
from typewitness.fingerprint import fingerprint_for_rule
from typewitness.models import Finding


@dataclass(frozen=True)
class CastNeedsEvidenceRule:
    code: str = "TW002"
    name: str = "cast-needs-evidence"

    def check(self, context: AnalysisContext) -> Tuple[Finding, ...]:
        findings: List[Finding] = []
        for candidate in context.candidates.cast_candidates:
            if candidate.is_chain_child:
                continue
            start_line = candidate.source_range.start.line
            end_line = candidate.source_range.end.line
            safety_directives = context.source_index.safety_for_statement(start_line, end_line)
            if any(safety_suppresses_rule(directive, self.code) for directive in safety_directives):
                continue
            findings.append(
                Finding(
                    code=self.code,
                    path=context.source.path,
                    range=candidate.source_range,
                    message="cast call missing SAFETY evidence",
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
