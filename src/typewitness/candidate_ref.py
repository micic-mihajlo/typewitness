from __future__ import annotations

from dataclasses import dataclass

CANDIDATE_KIND_CAST = "cast-call"
CANDIDATE_KIND_IGNORE = "type-ignore-comment"


@dataclass(frozen=True, order=True)
class CandidateRef:
    kind: str
    index: int
