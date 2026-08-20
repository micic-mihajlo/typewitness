from __future__ import annotations

import hashlib
import pathlib
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from typewitness.candidate_ref import CandidateRef

FINGERPRINT_SCHEMA = "tw-fp-2"


def population_key(
    *,
    kind: str,
    scope_path: str,
    candidate_norm: str,
    host_norm: str,
) -> Tuple[str, str, str, str]:
    return (kind, scope_path, candidate_norm, host_norm)


def duplicate_suffix(group_size: int, index: int) -> str:
    if group_size <= 1:
        return ""
    return f"dup:{group_size}:{index}"


def make_fingerprint(
    *,
    code: str,
    path: pathlib.Path,
    kind: str,
    scope_path: str,
    candidate_norm: str,
    host_norm: str,
    dup_suffix: str = "",
) -> str:
    posix_path = path.as_posix()
    payload = "|".join(
        [
            FINGERPRINT_SCHEMA,
            code,
            posix_path,
            kind,
            scope_path,
            candidate_norm,
            host_norm,
            dup_suffix,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class FingerprintAssignment:
    ref: CandidateRef
    population_key: Tuple[str, str, str, str]
    dup_suffix: str


class FingerprintTable:
    def __init__(self, assignments: Dict[CandidateRef, FingerprintAssignment]) -> None:
        self._assignments = assignments

    def dup_suffix_for(self, ref: CandidateRef) -> str:
        return self._assignments[ref].dup_suffix

    def population_key_for(self, ref: CandidateRef) -> Tuple[str, str, str, str]:
        return self._assignments[ref].population_key


def build_fingerprint_table(
    *,
    path: pathlib.Path,
    refs: Sequence[CandidateRef],
    scope_paths: Sequence[str],
    candidate_norms: Sequence[str],
    host_norms: Sequence[str],
) -> FingerprintTable:
    groups: Dict[Tuple[str, str, str, str], List[CandidateRef]] = {}
    for ref, scope_path, candidate_norm, host_norm in zip(
        refs,
        scope_paths,
        candidate_norms,
        host_norms,
    ):
        key = population_key(
            kind=ref.kind,
            scope_path=scope_path,
            candidate_norm=candidate_norm,
            host_norm=host_norm,
        )
        groups.setdefault(key, []).append(ref)

    assignments: Dict[CandidateRef, FingerprintAssignment] = {}
    for key, members in groups.items():
        for index, ref in enumerate(members):
            suffix = duplicate_suffix(len(members), index)
            assignments[ref] = FingerprintAssignment(
                ref=ref,
                population_key=key,
                dup_suffix=suffix,
            )
    return FingerprintTable(assignments)


def fingerprint_for_rule(
    table: FingerprintTable,
    *,
    ref: CandidateRef,
    code: str,
    path: pathlib.Path,
    scope_path: str,
    candidate_norm: str,
    host_norm: str,
) -> str:
    assignment = table._assignments[ref]
    return make_fingerprint(
        code=code,
        path=path,
        kind=ref.kind,
        scope_path=scope_path,
        candidate_norm=candidate_norm,
        host_norm=host_norm,
        dup_suffix=assignment.dup_suffix,
    )
