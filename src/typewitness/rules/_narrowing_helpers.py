from __future__ import annotations

import ast
from typing import List, Optional, Union

from typewitness.candidates import NarrowingFunctionCandidate
from typewitness.context import AnalysisContext
from typewitness.models import SourceLocation, SourceRange
from typewitness.rules._finding_helpers import statement_safety_suppresses
from typewitness.scopes import ScopeKind, ScopeTree, SymbolIdentity
from typewitness.source_index import SourceIndex

FunctionDefNode = Union[ast.FunctionDef, ast.AsyncFunctionDef]
_NARROWING_IDENTITIES = frozenset({SymbolIdentity.TYPING_TYPE_GUARD, SymbolIdentity.TYPING_TYPE_IS})


def should_report_constant_narrowing(
    context: AnalysisContext,
    candidate: NarrowingFunctionCandidate,
    rule_code: str,
) -> bool:
    if statement_safety_suppresses(context, candidate, rule_code):
        return False
    node = candidate.node
    if node.returns is None or _is_string_annotation(node.returns):
        return False
    narrowing_kind = resolve_narrowing_annotation_base(context, candidate)
    if narrowing_kind is None:
        return False
    if _has_overload_decorator(node, context.scope_tree, candidate.scope_index):
        return False
    if _is_in_protocol_class(context.scope_tree, candidate.scope_index):
        return False
    return _body_is_single_literal_bool_return(node.body) is not None


def _resolve_narrowing_annotation_base(
    annotation: ast.expr | None,
    scope_tree: ScopeTree,
    scope_index: int,
    use_line: int,
    use_col: int,
) -> Optional[SymbolIdentity]:
    if annotation is None or _is_string_annotation(annotation):
        return None
    base = _annotation_base(annotation)
    if base is None:
        return None
    identity = scope_tree.resolve_simple_symbol_identity(
        base,
        scope_index,
        use_line,
        use_col,
    )
    if identity in _NARROWING_IDENTITIES:
        return identity
    return None


def resolve_narrowing_annotation_base(
    context: AnalysisContext,
    candidate: NarrowingFunctionCandidate,
) -> Optional[SymbolIdentity]:
    node = candidate.node
    if node.returns is None:
        return None
    annotation_scope = context.scope_tree.scope_for_node(node.returns)
    use_line = getattr(node.returns, "lineno", candidate.source_range.start.line)
    use_col = getattr(node.returns, "col_offset", candidate.source_range.start.column)
    return _resolve_narrowing_annotation_base(
        node.returns,
        context.scope_tree,
        annotation_scope,
        use_line,
        use_col,
    )


def _annotation_base(annotation: ast.expr) -> Optional[ast.expr]:
    if isinstance(annotation, ast.Subscript):
        return annotation.value
    if isinstance(annotation, ast.Name):
        return annotation
    if isinstance(annotation, ast.Attribute):
        return annotation
    return None


def _is_string_annotation(annotation: ast.expr) -> bool:
    return isinstance(annotation, ast.Constant) and isinstance(annotation.value, str)


def _has_overload_decorator(
    node: FunctionDefNode,
    scope_tree: ScopeTree,
    scope_index: int,
) -> bool:
    for decorator in node.decorator_list:
        use_line = getattr(decorator, "lineno", 1)
        use_col = getattr(decorator, "col_offset", 0)
        if (
            scope_tree.resolve_simple_symbol_identity(
                decorator,
                scope_index,
                use_line,
                use_col,
            )
            is SymbolIdentity.TYPING_OVERLOAD
        ):
            return True
    return False


def _is_in_protocol_class(scope_tree: ScopeTree, function_scope_index: int) -> bool:
    current = scope_tree.scopes[function_scope_index].parent_index
    while current >= 0:
        scope = scope_tree.scopes[current]
        if scope.kind == ScopeKind.CLASS:
            if not isinstance(scope.node, ast.ClassDef):
                return False
            return _class_inherits_protocol(scope.node, scope_tree, current)
        current = scope.parent_index
    return False


def _class_inherits_protocol(
    node: ast.ClassDef,
    scope_tree: ScopeTree,
    scope_index: int,
) -> bool:
    use_line = node.lineno
    use_col = node.col_offset
    for base in node.bases:
        if (
            scope_tree.resolve_simple_symbol_identity(
                base,
                scope_index,
                use_line,
                use_col,
            )
            is SymbolIdentity.TYPING_PROTOCOL
        ):
            return True
    return False


def _body_is_single_literal_bool_return(body: List[ast.stmt]) -> Optional[bool]:
    statements = list(body)
    if statements and _is_docstring_stmt(statements[0]):
        statements = statements[1:]
    if len(statements) != 1:
        return None
    stmt = statements[0]
    if not isinstance(stmt, ast.Return):
        return None
    if stmt.value is None:
        return None
    return _literal_bool(stmt.value)


def _is_docstring_stmt(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _literal_bool(expr: ast.expr) -> Optional[bool]:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, bool):
        return expr.value
    return None


def function_header_range(
    node: FunctionDefNode,
    source_index: SourceIndex,
) -> SourceRange:
    start_line = node.lineno
    start_col = node.col_offset
    if node.body:
        end_line = node.body[0].lineno - 1
    else:
        end_line = start_line
    if end_line < start_line:
        end_line = start_line
    end_line_text = source_index.lines[end_line - 1]
    return SourceRange(
        start=SourceLocation(line=start_line, column=start_col),
        end=SourceLocation(line=end_line, column=len(end_line_text)),
    )


def narrowing_candidate_norm(
    node: FunctionDefNode,
    narrowing_kind: SymbolIdentity,
) -> str:
    target_kind = "async" if isinstance(node, ast.AsyncFunctionDef) else "function"
    annotation_kind = "TypeIs" if narrowing_kind is SymbolIdentity.TYPING_TYPE_IS else "TypeGuard"
    return f"{annotation_kind}|{target_kind}|{node.name}"
