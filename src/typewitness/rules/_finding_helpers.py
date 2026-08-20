from __future__ import annotations

from typing import Protocol

from typewitness.candidate_ref import CandidateRef
from typewitness.context import AnalysisContext
from typewitness.directives import evidence_suppresses_rule
from typewitness.fingerprint import fingerprint_for_rule
from typewitness.models import Finding, SourceRange


class FindingCandidate(Protocol):
    @property
    def ref(self) -> CandidateRef: ...

    @property
    def scope_path(self) -> str: ...

    @property
    def source_range(self) -> SourceRange: ...

    @property
    def candidate_norm(self) -> str: ...

    @property
    def host_norm(self) -> str: ...


def statement_safety_suppresses(
    context: AnalysisContext,
    candidate: FindingCandidate,
    rule_code: str,
) -> bool:
    safety_directives = context.source_index.safety_for_statement(
        candidate.source_range.start.line,
        candidate.source_range.end.line,
    )
    return any(evidence_suppresses_rule(directive, rule_code) for directive in safety_directives)


def candidate_finding(
    context: AnalysisContext,
    candidate: FindingCandidate,
    *,
    code: str,
    message: str,
) -> Finding:
    return Finding(
        code=code,
        path=context.source.path,
        range=candidate.source_range,
        message=message,
        fingerprint=fingerprint_for_rule(
            context.fingerprints,
            ref=candidate.ref,
            code=code,
            path=context.source.path,
            scope_path=candidate.scope_path,
            candidate_norm=candidate.candidate_norm,
            host_norm=candidate.host_norm,
        ),
    )
