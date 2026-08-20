from __future__ import annotations

from dataclasses import dataclass

CANDIDATE_KIND_CAST = "cast-call"
CANDIDATE_KIND_IGNORE = "type-ignore-comment"
CANDIDATE_KIND_CHECKER_DISABLE = "checker-disable-comment"
CANDIDATE_KIND_NO_TYPE_CHECK = "no-type-check-decorator"
CANDIDATE_KIND_MOCK_PATCH = "mock-patch-call"
CANDIDATE_KIND_NARROWING_FUNCTION = "narrowing-function"


@dataclass(frozen=True, order=True)
class CandidateRef:
    kind: str
    index: int
