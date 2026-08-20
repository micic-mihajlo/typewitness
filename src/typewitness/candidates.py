from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from typewitness._instrumentation import record
from typewitness.candidate_ref import (
    CANDIDATE_KIND_CAST,
    CANDIDATE_KIND_IGNORE,
    CandidateRef,
)
from typewitness.directives import canonical_type_ignore_norm
from typewitness.models import SourceLocation, SourceRange
from typewitness.scopes import ScopeTree
from typewitness.source_index import CommentInfo, SourceIndex


@dataclass(frozen=True)
class CastCandidate:
    ref: CandidateRef
    node: ast.Call
    scope_index: int
    scope_path: str
    source_range: SourceRange
    candidate_norm: str
    host_norm: str
    parent_ref: Optional[CandidateRef]
    child_refs: Tuple[CandidateRef, ...]
    is_chain_child: bool


@dataclass(frozen=True)
class IgnoreCandidate:
    ref: CandidateRef
    comment_line: int
    comment_column: int
    comment_text: str
    scope_index: int
    scope_path: str
    source_range: SourceRange
    candidate_norm: str
    host_norm: str


@dataclass
class CandidateSet:
    cast_candidates: Tuple[CastCandidate, ...]
    ignore_candidates: Tuple[IgnoreCandidate, ...]
    _cast_by_ref: Dict[CandidateRef, CastCandidate]

    def cast_by_ref(self, ref: CandidateRef) -> CastCandidate:
        return self._cast_by_ref[ref]


def build_candidates(
    tree: ast.Module,
    source_index: SourceIndex,
    scope_tree: ScopeTree,
    parent_by_node_id: Optional[Dict[int, ast.AST]] = None,
) -> CandidateSet:
    parents = parent_by_node_id if parent_by_node_id is not None else build_parent_map(tree)
    cast_builder = _CastCandidateBuilder(tree, source_index, scope_tree, parents)
    ignore_builder = _IgnoreCandidateBuilder(source_index, scope_tree)
    return CandidateSet(
        cast_candidates=tuple(cast_builder.candidates),
        ignore_candidates=tuple(ignore_builder.candidates),
        _cast_by_ref={candidate.ref: candidate for candidate in cast_builder.candidates},
    )


def is_valid_cast_call_shape(node: ast.Call) -> bool:
    typ_count = 0
    val_count = 0
    positional = 0
    for arg in node.args:
        if isinstance(arg, ast.Starred):
            return False
        positional += 1
        if positional > 2:
            return False
        if positional == 1:
            typ_count += 1
        else:
            val_count += 1
    for keyword in node.keywords:
        if keyword.arg is None:
            return False
        if keyword.arg == "typ":
            typ_count += 1
        elif keyword.arg == "val":
            val_count += 1
        else:
            return False
    return typ_count == 1 and val_count == 1


class _CastCandidateBuilder:
    def __init__(
        self,
        tree: ast.Module,
        source_index: SourceIndex,
        scope_tree: ScopeTree,
        parent_by_node_id: Dict[int, ast.AST],
    ) -> None:
        self.source_index = source_index
        self.scope_tree = scope_tree
        self.parent_by_node_id = parent_by_node_id
        self.candidates: List[CastCandidate] = []
        self._next_id = 0
        self._node_to_ref: Dict[int, CandidateRef] = {}
        self._visit(tree)

    def _visit(self, node: ast.AST) -> None:
        if isinstance(node, ast.Call):
            scope_index = self.scope_tree.scope_for_node(node)
            if is_valid_cast_call_shape(node) and self.scope_tree.is_resolved_cast_call(
                node, scope_index
            ):
                candidate = self._make_candidate(node, scope_index)
                self.candidates.append(candidate)
                self._node_to_ref[id(node)] = candidate.ref
        for child in ast.iter_child_nodes(node):
            self._visit(child)
        if isinstance(node, ast.Call) and id(node) in self._node_to_ref:
            self._link_chain(node)

    def _make_candidate(self, node: ast.Call, scope_index: int) -> CastCandidate:
        ref = CandidateRef(kind=CANDIDATE_KIND_CAST, index=self._next_id)
        self._next_id += 1
        source_range = self.source_index.node_range(node)
        candidate_norm = self.source_index.norm_for_span(
            source_range.start.line,
            source_range.start.column,
            source_range.end.line,
            source_range.end.column,
        )
        host_norm = _host_norm(node, self.source_index, self.parent_by_node_id)
        return CastCandidate(
            ref=ref,
            node=node,
            scope_index=scope_index,
            scope_path=self.scope_tree.scope_path(scope_index),
            source_range=source_range,
            candidate_norm=candidate_norm,
            host_norm=host_norm,
            parent_ref=None,
            child_refs=(),
            is_chain_child=False,
        )

    def _link_chain(self, node: ast.Call) -> None:
        parent_ref = self._node_to_ref.get(id(node))
        if parent_ref is None:
            return
        record("chain_ref_lookups")
        parent_index = parent_ref.index
        parent = self.candidates[parent_index]
        _, value_arg = _extract_cast_args(node)
        child_ref = _direct_cast_ref(value_arg, self._node_to_ref)
        if child_ref is None:
            return
        record("chain_ref_lookups")
        child_index = child_ref.index
        child = self.candidates[child_index]
        if child.scope_index != parent.scope_index:
            return
        self.candidates[child_index] = CastCandidate(
            ref=child.ref,
            node=child.node,
            scope_index=child.scope_index,
            scope_path=child.scope_path,
            source_range=child.source_range,
            candidate_norm=child.candidate_norm,
            host_norm=child.host_norm,
            parent_ref=parent_ref,
            child_refs=child.child_refs,
            is_chain_child=True,
        )
        self.candidates[parent_index] = CastCandidate(
            ref=parent.ref,
            node=parent.node,
            scope_index=parent.scope_index,
            scope_path=parent.scope_path,
            source_range=parent.source_range,
            candidate_norm=parent.candidate_norm,
            host_norm=parent.host_norm,
            parent_ref=parent.parent_ref,
            child_refs=(child_ref,),
            is_chain_child=parent.is_chain_child,
        )


class _IgnoreCandidateBuilder:
    def __init__(
        self,
        source_index: SourceIndex,
        scope_tree: ScopeTree,
    ) -> None:
        self.source_index = source_index
        self.scope_tree = scope_tree
        self.candidates: List[IgnoreCandidate] = []
        self._next_id = 0
        for comment in source_index.comments:
            if not comment.type_ignore:
                continue
            self._add_comment(comment)

    def _add_comment(self, comment: CommentInfo) -> None:
        scope_index = self.scope_tree.scope_index_for_line(comment.line, comment.column)
        source_range = SourceRange(
            start=SourceLocation(line=comment.line, column=comment.column),
            end=SourceLocation(
                line=comment.line,
                column=comment.column + len(comment.text),
            ),
        )
        candidate_norm = canonical_type_ignore_norm(comment.text)
        host_norm = _host_norm_for_line(self.source_index, comment.line)
        ref = CandidateRef(kind=CANDIDATE_KIND_IGNORE, index=self._next_id)
        self._next_id += 1
        self.candidates.append(
            IgnoreCandidate(
                ref=ref,
                comment_line=comment.line,
                comment_column=comment.column,
                comment_text=comment.text,
                scope_index=scope_index,
                scope_path=self.scope_tree.scope_path(scope_index),
                source_range=source_range,
                candidate_norm=candidate_norm,
                host_norm=host_norm,
            )
        )


def _extract_cast_args(node: ast.Call) -> Tuple[Optional[ast.expr], Optional[ast.expr]]:
    if not is_valid_cast_call_shape(node):
        return None, None
    typ_arg: Optional[ast.expr] = None
    value_arg: Optional[ast.expr] = None
    positional = 0
    for arg in node.args:
        positional += 1
        if positional == 1:
            typ_arg = arg
        elif positional == 2:
            value_arg = arg
    for keyword in node.keywords:
        if keyword.arg == "typ":
            typ_arg = keyword.value
        elif keyword.arg == "val":
            value_arg = keyword.value
    return typ_arg, value_arg


def _direct_cast_ref(
    value_arg: Optional[ast.expr],
    node_to_ref: Dict[int, CandidateRef],
) -> Optional[CandidateRef]:
    if isinstance(value_arg, ast.Call):
        return node_to_ref.get(id(value_arg))
    return None


def _host_norm(
    node: ast.AST,
    source_index: SourceIndex,
    parent_by_node_id: Dict[int, ast.AST],
) -> str:
    stmt = _enclosing_stmt(node, parent_by_node_id)
    if stmt is None or not hasattr(stmt, "lineno"):
        return ""
    source_range = source_index.node_range(stmt)
    return source_index.host_norm_for_span(
        source_range.start.line,
        source_range.start.column,
        source_range.end.line,
        source_range.end.column,
    )


def _host_norm_for_line(source_index: SourceIndex, line: int) -> str:
    logical_start = source_index.logical_start_line(line)
    logical_end = source_index.logical_end_line(line)
    end_line_text = source_index.lines[logical_end - 1]
    end_col = len(end_line_text)
    return source_index.host_norm_for_span(logical_start, 0, logical_end, end_col)


def _enclosing_stmt(
    node: ast.AST,
    parent_by_node_id: Dict[int, ast.AST],
) -> Optional[ast.stmt]:
    current: Optional[ast.AST] = node
    while current is not None:
        if isinstance(current, ast.stmt):
            return current
        current = parent_by_node_id.get(id(current))
    return None


def build_parent_map(tree: ast.AST) -> Dict[int, ast.AST]:
    parents: Dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent
    return parents
