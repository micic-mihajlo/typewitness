from __future__ import annotations

import ast
from typing import FrozenSet

from typewitness.candidates import CastCandidate
from typewitness.context import AnalysisContext
from typewitness.scopes import SymbolIdentity

BOUNDARY_PARSER_IDENTITIES: FrozenSet[SymbolIdentity] = frozenset(
    {
        SymbolIdentity.JSON_LOAD,
        SymbolIdentity.JSON_LOADS,
        SymbolIdentity.PICKLE_LOAD,
        SymbolIdentity.PICKLE_LOADS,
        SymbolIdentity.MARSHAL_LOAD,
        SymbolIdentity.MARSHAL_LOADS,
        SymbolIdentity.TOMLLIB_LOAD,
        SymbolIdentity.TOMLLIB_LOADS,
        SymbolIdentity.PLISTLIB_LOAD,
        SymbolIdentity.PLISTLIB_LOADS,
        SymbolIdentity.AST_LITERAL_EVAL,
    }
)


def is_cast_target_any(
    type_arg: ast.expr,
    context: AnalysisContext,
    candidate: CastCandidate,
) -> bool:
    line = candidate.source_range.start.line
    column = candidate.source_range.start.column
    scope_tree = context.scope_tree
    scope_index = candidate.scope_index
    return (
        scope_tree.resolve_simple_symbol_identity(type_arg, scope_index, line, column)
        is SymbolIdentity.TYPING_ANY
    )


def is_cast_target_any_or_object(
    type_arg: ast.expr,
    context: AnalysisContext,
    candidate: CastCandidate,
) -> bool:
    line = candidate.source_range.start.line
    column = candidate.source_range.start.column
    scope_tree = context.scope_tree
    return scope_tree.is_resolved_any_annotation(
        type_arg,
        candidate.scope_index,
        line,
        column,
    ) or scope_tree.is_builtin_object_annotation(
        type_arg,
        candidate.scope_index,
        line,
        column,
    )


def unwrap_projection_base(expr: ast.expr) -> ast.expr:
    current = expr
    while isinstance(current, (ast.Attribute, ast.Subscript)):
        current = current.value
    return current


def resolve_call_identity(
    node: ast.Call,
    context: AnalysisContext,
    candidate: CastCandidate,
) -> SymbolIdentity:
    line = candidate.source_range.start.line
    column = candidate.source_range.start.column
    scope_tree = context.scope_tree
    return scope_tree.resolve_simple_symbol_identity(
        node.func,
        candidate.scope_index,
        line,
        column,
    )


def value_expr_has_boundary_root(
    expr: ast.expr,
    context: AnalysisContext,
    candidate: CastCandidate,
) -> bool:
    root = unwrap_projection_base(expr)
    if not isinstance(root, ast.Call):
        return False
    identity = resolve_call_identity(root, context, candidate)
    return identity in BOUNDARY_PARSER_IDENTITIES
