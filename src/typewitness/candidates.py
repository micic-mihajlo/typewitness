from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from typing import Dict, Iterator, List, Optional, Tuple, Union

from typewitness._instrumentation import record
from typewitness.candidate_ref import (
    CANDIDATE_KIND_CAST,
    CANDIDATE_KIND_CHECKER_DISABLE,
    CANDIDATE_KIND_IGNORE,
    CANDIDATE_KIND_MOCK_PATCH,
    CANDIDATE_KIND_NARROWING_FUNCTION,
    CANDIDATE_KIND_NO_TYPE_CHECK,
    CandidateRef,
)
from typewitness.directives import canonical_type_ignore_norm
from typewitness.disable_directives import (
    CheckerDisableDirective,
    parse_checker_disable,
)
from typewitness.models import SourceLocation, SourceRange
from typewitness.scopes import ScopeKind, ScopeTree, SymbolIdentity
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
    type_arg: ast.expr
    value_arg: ast.expr
    is_entire_expr_value: bool


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


@dataclass(frozen=True)
class CheckerDisableCandidate:
    ref: CandidateRef
    comment_line: int
    comment_column: int
    comment_text: str
    checker: str
    scope_index: int
    scope_path: str
    source_range: SourceRange
    candidate_norm: str
    host_norm: str


@dataclass(frozen=True)
class NoTypeCheckCandidate:
    ref: CandidateRef
    decorator: ast.expr
    target_kind: str
    scope_index: int
    scope_path: str
    source_range: SourceRange
    candidate_norm: str
    host_norm: str


MOCK_PATCH_FIDELITY_KEYWORDS = frozenset(
    {"autospec", "spec", "spec_set", "new", "new_callable", "wraps"}
)


@dataclass(frozen=True)
class MockPatchCandidate:
    ref: CandidateRef
    node: ast.Call
    patch_form: str
    scope_index: int
    scope_path: str
    source_range: SourceRange
    candidate_norm: str
    host_norm: str
    has_literal_create_true: bool
    has_fidelity_keyword: bool
    has_kwargs_splat: bool


@dataclass(frozen=True)
class NarrowingFunctionCandidate:
    ref: CandidateRef
    node: ast.FunctionDef | ast.AsyncFunctionDef
    scope_index: int
    scope_path: str
    source_range: SourceRange
    candidate_norm: str
    host_norm: str


FingerprintCandidate = Union[
    CastCandidate,
    IgnoreCandidate,
    CheckerDisableCandidate,
    NoTypeCheckCandidate,
    MockPatchCandidate,
    NarrowingFunctionCandidate,
]


@dataclass
class CandidateSet:
    cast_candidates: Tuple[CastCandidate, ...]
    ignore_candidates: Tuple[IgnoreCandidate, ...]
    checker_disable_candidates: Tuple[CheckerDisableCandidate, ...]
    no_type_check_candidates: Tuple[NoTypeCheckCandidate, ...]
    mock_patch_candidates: Tuple[MockPatchCandidate, ...]
    narrowing_function_candidates: Tuple[NarrowingFunctionCandidate, ...]
    _cast_by_ref: Dict[CandidateRef, CastCandidate]

    def cast_by_ref(self, ref: CandidateRef) -> CastCandidate:
        return self._cast_by_ref[ref]

    def fingerprint_candidates(self) -> Tuple[FingerprintCandidate, ...]:
        return (
            *self.cast_candidates,
            *self.ignore_candidates,
            *self.checker_disable_candidates,
            *self.no_type_check_candidates,
            *self.mock_patch_candidates,
            *self.narrowing_function_candidates,
        )


def build_candidates(
    tree: ast.Module,
    source_index: SourceIndex,
    scope_tree: ScopeTree,
    parent_by_node_id: Optional[Dict[int, ast.AST]] = None,
) -> CandidateSet:
    parents = parent_by_node_id if parent_by_node_id is not None else build_parent_map(tree)
    cast_builder = _CastCandidateBuilder(tree, source_index, scope_tree, parents)
    ignore_builder = _IgnoreCandidateBuilder(source_index, scope_tree)
    checker_disable_builder = _CheckerDisableCandidateBuilder(source_index, scope_tree)
    no_type_check_builder = _NoTypeCheckCandidateBuilder(tree, source_index, scope_tree)
    mock_patch_builder = _MockPatchCandidateBuilder(tree, source_index, scope_tree)
    narrowing_builder = _NarrowingFunctionCandidateBuilder(tree, source_index, scope_tree)
    return CandidateSet(
        cast_candidates=tuple(cast_builder.candidates),
        ignore_candidates=tuple(ignore_builder.candidates),
        checker_disable_candidates=tuple(checker_disable_builder.candidates),
        no_type_check_candidates=tuple(no_type_check_builder.candidates),
        mock_patch_candidates=tuple(mock_patch_builder.candidates),
        narrowing_function_candidates=tuple(narrowing_builder.candidates),
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
        typ_arg, value_arg = _extract_cast_args(node)
        assert typ_arg is not None and value_arg is not None
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
            type_arg=typ_arg,
            value_arg=value_arg,
            is_entire_expr_value=_is_entire_expr_value(node, self.parent_by_node_id),
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
        self.candidates[child_index] = replace(
            child,
            parent_ref=parent_ref,
            is_chain_child=True,
        )
        self.candidates[parent_index] = replace(
            parent,
            child_refs=(child_ref,),
        )


class _CheckerDisableCandidateBuilder:
    def __init__(
        self,
        source_index: SourceIndex,
        scope_tree: ScopeTree,
    ) -> None:
        self.source_index = source_index
        self.scope_tree = scope_tree
        self.candidates: List[CheckerDisableCandidate] = []
        self._next_id = 0
        for comment in source_index.comments:
            if comment.column != 0:
                continue
            directive = parse_checker_disable(comment.text)
            if directive is None:
                continue
            scope_index = self.scope_tree.scope_index_for_line(comment.line, comment.column)
            if scope_index != self.scope_tree.module_index:
                continue
            self._add_comment(comment, directive)

    def _add_comment(
        self,
        comment: CommentInfo,
        directive: CheckerDisableDirective,
    ) -> None:
        source_range = SourceRange(
            start=SourceLocation(line=comment.line, column=comment.column),
            end=SourceLocation(
                line=comment.line,
                column=comment.column + len(comment.text),
            ),
        )
        ref = CandidateRef(kind=CANDIDATE_KIND_CHECKER_DISABLE, index=self._next_id)
        self._next_id += 1
        self.candidates.append(
            CheckerDisableCandidate(
                ref=ref,
                comment_line=comment.line,
                comment_column=comment.column,
                comment_text=comment.text,
                checker=directive.checker,
                scope_index=self.scope_tree.module_index,
                scope_path=self.scope_tree.scope_path(self.scope_tree.module_index),
                source_range=source_range,
                candidate_norm=directive.candidate_norm,
                host_norm=_host_norm_for_line(self.source_index, comment.line),
            )
        )


class _NoTypeCheckCandidateBuilder:
    def __init__(
        self,
        tree: ast.Module,
        source_index: SourceIndex,
        scope_tree: ScopeTree,
    ) -> None:
        self.source_index = source_index
        self.scope_tree = scope_tree
        self.candidates: List[NoTypeCheckCandidate] = []
        self._next_id = 0
        for node in _iter_nodes_preorder(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._visit_decorators(node.decorator_list, "function", node)
            elif isinstance(node, ast.ClassDef):
                self._visit_decorators(node.decorator_list, "class", node)

    def _visit_decorators(
        self,
        decorators: List[ast.expr],
        target_kind: str,
        target_node: ast.AST,
    ) -> None:
        target_name = getattr(target_node, "name", "")
        for decorator in decorators:
            if isinstance(decorator, ast.Call):
                continue
            scope_index = self.scope_tree.scope_for_node(decorator)
            if not self.scope_tree.is_resolved_no_type_check(decorator, scope_index):
                continue
            source_range = self.source_index.node_range(decorator)
            ref = CandidateRef(kind=CANDIDATE_KIND_NO_TYPE_CHECK, index=self._next_id)
            self._next_id += 1
            self.candidates.append(
                NoTypeCheckCandidate(
                    ref=ref,
                    decorator=decorator,
                    target_kind=target_kind,
                    scope_index=scope_index,
                    scope_path=self.scope_tree.scope_path(scope_index),
                    source_range=source_range,
                    candidate_norm=_no_type_check_candidate_norm(
                        decorator,
                        target_kind,
                        target_name,
                    ),
                    host_norm=_host_norm_for_line(self.source_index, decorator.lineno),
                )
            )


def _no_type_check_candidate_norm(
    decorator: ast.expr,
    target_kind: str,
    target_name: str,
) -> str:
    if isinstance(decorator, ast.Name):
        decorator_part = "no_type_check"
    elif isinstance(decorator, ast.Attribute) and decorator.attr == "no_type_check":
        if isinstance(decorator.value, ast.Name):
            decorator_part = f"{decorator.value.id}.no_type_check"
        else:
            decorator_part = "no_type_check:unknown"
    else:
        decorator_part = "no_type_check:unknown"
    return f"{decorator_part}|{target_kind}|{target_name}"


class _MockPatchCandidateBuilder:
    def __init__(
        self,
        tree: ast.Module,
        source_index: SourceIndex,
        scope_tree: ScopeTree,
    ) -> None:
        self.source_index = source_index
        self.scope_tree = scope_tree
        self.candidates: List[MockPatchCandidate] = []
        self._next_id = 0
        for node in _iter_nodes_preorder(tree):
            if not isinstance(node, ast.Call):
                continue
            scope_index = self.scope_tree.scope_for_node(node)
            patch_identity = self.scope_tree.resolve_mock_patch_call(node, scope_index)
            if patch_identity is not None:
                self.candidates.append(self._make_candidate(node, scope_index, patch_identity))

    def _make_candidate(
        self,
        node: ast.Call,
        scope_index: int,
        patch_identity: SymbolIdentity,
    ) -> MockPatchCandidate:
        ref = CandidateRef(kind=CANDIDATE_KIND_MOCK_PATCH, index=self._next_id)
        self._next_id += 1
        source_range = self.source_index.node_range(node)
        patch_form = (
            "patch.object" if patch_identity is SymbolIdentity.MOCK_PATCH_OBJECT else "patch"
        )
        has_literal_create_true = _mock_patch_has_literal_create_true(node)
        has_fidelity_keyword = _mock_patch_has_fidelity_decision(node, patch_form)
        has_kwargs_splat = _mock_patch_has_kwargs_splat(node)
        return MockPatchCandidate(
            ref=ref,
            node=node,
            patch_form=patch_form,
            scope_index=scope_index,
            scope_path=self.scope_tree.scope_path(scope_index),
            source_range=source_range,
            candidate_norm=_mock_patch_candidate_norm(
                patch_form,
                has_literal_create_true,
                has_fidelity_keyword,
                has_kwargs_splat,
            ),
            host_norm=_host_norm_for_line(self.source_index, node.lineno),
            has_literal_create_true=has_literal_create_true,
            has_fidelity_keyword=has_fidelity_keyword,
            has_kwargs_splat=has_kwargs_splat,
        )


def _mock_patch_has_literal_create_true(node: ast.Call) -> bool:
    for keyword in node.keywords:
        if keyword.arg == "create" and isinstance(keyword.value, ast.Constant):
            return keyword.value.value is True
    return False


def _mock_patch_has_fidelity_decision(node: ast.Call, patch_form: str) -> bool:
    if any(keyword.arg in MOCK_PATCH_FIDELITY_KEYWORDS for keyword in node.keywords):
        return True
    positional_new_index = 2 if patch_form == "patch.object" else 1
    return len(node.args) > positional_new_index


def _mock_patch_has_kwargs_splat(node: ast.Call) -> bool:
    return any(keyword.arg is None for keyword in node.keywords)


def _mock_patch_candidate_norm(
    patch_form: str,
    has_literal_create_true: bool,
    has_fidelity_keyword: bool,
    has_kwargs_splat: bool,
) -> str:
    create_part = "true" if has_literal_create_true else "absent"
    fidelity_part = "present" if has_fidelity_keyword else "absent"
    kwargs_part = "present" if has_kwargs_splat else "absent"
    return f"{patch_form}|create={create_part}|fidelity={fidelity_part}|kwargs={kwargs_part}"


class _NarrowingFunctionCandidateBuilder:
    def __init__(
        self,
        tree: ast.Module,
        source_index: SourceIndex,
        scope_tree: ScopeTree,
    ) -> None:
        self.source_index = source_index
        self.scope_tree = scope_tree
        self.candidates: List[NarrowingFunctionCandidate] = []
        self._next_id = 0
        for node in _iter_nodes_preorder(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            function_scope_index = self.scope_tree.scope_index_for_node(node)
            if self.scope_tree.scopes[function_scope_index].kind == ScopeKind.FUNCTION:
                candidate = self._make_candidate(node, function_scope_index)
                if candidate is not None:
                    self.candidates.append(candidate)

    def _make_candidate(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        scope_index: int,
    ) -> NarrowingFunctionCandidate | None:
        from typewitness.rules._narrowing_helpers import (
            _resolve_narrowing_annotation_base,
            function_header_range,
            narrowing_candidate_norm,
        )

        source_range = function_header_range(node, self.source_index)
        annotation_scope = (
            self.scope_tree.scope_for_node(node.returns)
            if node.returns is not None
            else scope_index
        )
        use_line = getattr(node.returns, "lineno", source_range.start.line)
        use_col = getattr(node.returns, "col_offset", source_range.start.column)
        narrowing_kind = _resolve_narrowing_annotation_base(
            node.returns,
            self.scope_tree,
            annotation_scope,
            use_line,
            use_col,
        )
        if narrowing_kind is None:
            return None
        ref = CandidateRef(kind=CANDIDATE_KIND_NARROWING_FUNCTION, index=self._next_id)
        self._next_id += 1
        return NarrowingFunctionCandidate(
            ref=ref,
            node=node,
            scope_index=scope_index,
            scope_path=self.scope_tree.scope_path(scope_index),
            source_range=source_range,
            candidate_norm=narrowing_candidate_norm(node, narrowing_kind),
            host_norm=_host_norm_for_line(self.source_index, node.lineno),
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


def _is_entire_expr_value(node: ast.AST, parent_by_node_id: Dict[int, ast.AST]) -> bool:
    parent = parent_by_node_id.get(id(node))
    return isinstance(parent, ast.Expr) and parent.value is node


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


def _iter_nodes_preorder(node: ast.AST) -> Iterator[ast.AST]:
    yield node
    for child in ast.iter_child_nodes(node):
        yield from _iter_nodes_preorder(child)
