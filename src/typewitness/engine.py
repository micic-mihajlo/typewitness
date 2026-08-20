from __future__ import annotations

import ast
from typing import Optional, Tuple

from typewitness.candidate_ref import CandidateRef
from typewitness.candidates import build_candidates, build_parent_map
from typewitness.catalog import (
    active_rules_require_effect_index,
    active_rules_require_typevar_index,
)
from typewitness.context import AnalysisContext
from typewitness.effects import build_effect_index
from typewitness.fingerprint import build_fingerprint_table
from typewitness.models import (
    AnalysisError,
    AnalysisResult,
    Config,
    Finding,
    SourceFile,
)
from typewitness.rules import RULES
from typewitness.scopes import build_scope_tree
from typewitness.source_index import (
    build_source_index,
    normalize_source_text,
    preflight_encode_error,
)
from typewitness.typevars import build_typevar_index


def _finding_sort_key(finding: Finding) -> Tuple[str, int, int, str, str]:
    return (
        finding.path.as_posix(),
        finding.range.start.line,
        finding.range.start.column,
        finding.code,
        finding.fingerprint,
    )


def _error_sort_key(error: AnalysisError) -> Tuple[str, str, str]:
    path = error.path.as_posix() if error.path is not None else ""
    return (path, error.kind, error.message)


def analyze(source: SourceFile, config: Optional[Config] = None) -> AnalysisResult:
    active_config = config if config is not None else Config()
    active_rules = active_config.resolved_select()
    normalized = normalize_source_text(source.text)
    encode_message = preflight_encode_error(normalized)
    if encode_message is not None:
        return AnalysisResult(
            findings=(),
            errors=(
                AnalysisError(
                    kind="encode",
                    path=source.path,
                    message=encode_message,
                ),
            ),
        )

    try:
        tree = ast.parse(normalized, filename=str(source.path))
    except SyntaxError as exc:
        return AnalysisResult(
            findings=(),
            errors=(
                AnalysisError(
                    kind="parse",
                    path=source.path,
                    message=str(exc),
                ),
            ),
        )

    try:
        parent_by_node_id = build_parent_map(tree)
        source_index = build_source_index(normalized)
        scope_tree = build_scope_tree(tree)
        candidates = build_candidates(tree, source_index, scope_tree, parent_by_node_id)
        refs: list[CandidateRef] = []
        scope_paths: list[str] = []
        candidate_norms: list[str] = []
        host_norms: list[str] = []
        for candidate in candidates.fingerprint_candidates():
            refs.append(candidate.ref)
            scope_paths.append(candidate.scope_path)
            candidate_norms.append(candidate.candidate_norm)
            host_norms.append(candidate.host_norm)
        fingerprints = build_fingerprint_table(
            path=source.path,
            refs=refs,
            scope_paths=scope_paths,
            candidate_norms=candidate_norms,
            host_norms=host_norms,
        )
        effects = (
            build_effect_index(scope_tree)
            if active_rules_require_effect_index(active_rules)
            else None
        )
        typevar_index = (
            build_typevar_index(scope_tree)
            if active_rules_require_typevar_index(active_rules)
            else None
        )
    except RecursionError as exc:
        return AnalysisResult(
            findings=(),
            errors=(
                AnalysisError(
                    kind="limit",
                    path=source.path,
                    message=str(exc),
                ),
            ),
        )
    except Exception as exc:  # noqa: BLE001 - public boundary
        return AnalysisResult(
            findings=(),
            errors=(
                AnalysisError(
                    kind="internal",
                    path=source.path,
                    message=str(exc),
                ),
            ),
        )

    normalized_source = SourceFile(path=source.path, text=normalized, encoding=source.encoding)
    context = AnalysisContext(
        source=normalized_source,
        tree=tree,
        parent_by_node_id=parent_by_node_id,
        source_index=source_index,
        scope_tree=scope_tree,
        candidates=candidates,
        fingerprints=fingerprints,
        effects=effects,
        typevar_index=typevar_index,
        config=active_config,
    )

    findings: list[Finding] = []
    errors: list[AnalysisError] = []
    for rule in RULES:
        if rule.code not in active_rules:
            continue
        try:
            findings.extend(rule.check(context))
        except Exception as exc:  # noqa: BLE001 - rule isolation boundary
            errors.append(
                AnalysisError(
                    kind="internal",
                    path=source.path,
                    message=f"{rule.code}: {exc}",
                )
            )

    findings.sort(key=_finding_sort_key)
    errors.sort(key=_error_sort_key)
    return AnalysisResult(findings=tuple(findings), errors=tuple(errors))
