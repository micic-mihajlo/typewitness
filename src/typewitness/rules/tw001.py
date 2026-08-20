from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from typewitness.context import AnalysisContext
from typewitness.fingerprint import fingerprint_for_rule
from typewitness.models import Finding


@dataclass(frozen=True)
class NoChainedCastRule:
    code: str = "TW001"
    name: str = "no-chained-cast"

    def check(self, context: AnalysisContext) -> Tuple[Finding, ...]:
        findings: List[Finding] = []
        for candidate in context.candidates.cast_candidates:
            if not candidate.child_refs:
                continue
            if candidate.is_chain_child:
                continue
            findings.append(
                Finding(
                    code=self.code,
                    path=context.source.path,
                    range=candidate.source_range,
                    message="nested typing.cast call",
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
