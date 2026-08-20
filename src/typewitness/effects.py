from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from typewitness.scopes import BindingForm, BindingSite, ScopeKind, ScopeTree

MAX_LITERAL_ALIAS_DEPTH = 8


@dataclass(frozen=True)
class BindingEvidence:
    name: str
    site: BindingSite
    literal: Optional[ast.expr] = None


@dataclass
class FunctionEffectIndex:
    scope_index: int
    evidence_by_name: Dict[str, BindingEvidence] = field(default_factory=dict)
    evidence_eligible: Set[str] = field(default_factory=set)


@dataclass
class EffectIndex:
    functions: Dict[int, FunctionEffectIndex]

    def is_evidence_eligible(
        self,
        scope_index: int,
        name: str,
        use_line: int,
        use_col: int = 0,
    ) -> bool:
        fn_index = self.functions.get(scope_index)
        if fn_index is None:
            return False
        if name not in fn_index.evidence_eligible:
            return False
        evidence = fn_index.evidence_by_name.get(name)
        if evidence is None:
            return False
        site = evidence.site
        if site.line > use_line:
            return False
        if site.line == use_line and site.column >= use_col:
            return False
        return True


def build_effect_index(scope_tree: ScopeTree) -> EffectIndex:
    functions: Dict[int, FunctionEffectIndex] = {}
    for scope_index, scope in enumerate(scope_tree.scopes):
        if scope.kind != ScopeKind.FUNCTION:
            continue
        functions[scope_index] = _build_function_effect(scope_index, scope_tree)
    return EffectIndex(functions=functions)


def _build_function_effect(scope_index: int, scope_tree: ScopeTree) -> FunctionEffectIndex:
    sites_by_name: Dict[str, List[BindingSite]] = {}
    for site in scope_tree.scopes[scope_index].binding_sites:
        sites_by_name.setdefault(site.name, []).append(site)

    index = FunctionEffectIndex(scope_index=scope_index)
    for name, sites in sites_by_name.items():
        if len(sites) != 1:
            continue
        site = sites[0]
        if site.binding_form != BindingForm.ANN_ASSIGN.value:
            continue
        if not site.direct_body:
            continue
        if not site.widened:
            continue
        literal = _resolve_literal_for_site(site, scope_index, scope_tree, depth=0)
        if literal is None:
            continue
        index.evidence_eligible.add(name)
        index.evidence_by_name[name] = BindingEvidence(name=name, site=site, literal=literal)
    return index


def _resolve_literal_for_site(
    site: BindingSite,
    scope_index: int,
    scope_tree: ScopeTree,
    depth: int,
) -> Optional[ast.expr]:
    value = scope_tree.site_values.get(site.site_id)
    if value is None:
        return None
    return _resolve_literal_expr(value, scope_index, scope_tree, depth, before=site)


def _resolve_literal_expr(
    value: ast.expr,
    scope_index: int,
    scope_tree: ScopeTree,
    depth: int,
    *,
    before: BindingSite,
) -> Optional[ast.expr]:
    if _is_known_literal(value):
        return value
    if depth >= MAX_LITERAL_ALIAS_DEPTH:
        return None
    if not isinstance(value, ast.Name):
        return None
    alias_sites = scope_tree.sites_for_name(scope_index, value.id)
    if len(alias_sites) != 1:
        return None
    alias = alias_sites[0]
    if alias.binding_form != BindingForm.ASSIGN.value:
        return None
    if not alias.direct_body:
        return None
    if not _site_before(alias, before):
        return None
    alias_value = scope_tree.site_values.get(alias.site_id)
    if alias_value is None:
        return None
    return _resolve_literal_expr(
        alias_value,
        scope_index,
        scope_tree,
        depth + 1,
        before=before,
    )


def _site_before(left: BindingSite, right: BindingSite) -> bool:
    if left.line < right.line:
        return True
    if left.line == right.line and left.column < right.column:
        return True
    return False


def _is_known_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _is_known_literal(node.operand)
    if isinstance(node, ast.List):
        return all(_is_known_literal(element) for element in node.elts)
    if isinstance(node, ast.Tuple):
        return all(_is_known_literal(element) for element in node.elts)
    if isinstance(node, ast.Set):
        return all(_is_known_literal(element) for element in node.elts)
    if isinstance(node, ast.Dict):
        keys = node.keys
        if keys is None:
            return False
        return all(
            key is not None and _is_known_literal(key) and _is_known_literal(val)
            for key, val in zip(keys, node.values)
        )
    return False
