from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Set

from typewitness.scopes import BindingForm, BindingSite, Scope, ScopeKind, ScopeTree, SymbolIdentity


def _site_before_use(site: BindingSite, use_line: int, use_col: int) -> bool:
    return site.line < use_line or (site.line == use_line and site.column < use_col)


@dataclass
class TypeVarIndex:
    _scope_tree: ScopeTree
    proven_names_by_scope: Dict[int, FrozenSet[str]] = field(default_factory=dict)

    def is_proven_local_typevar(
        self,
        scope_index: int,
        name: str,
        use_line: int,
        use_col: int = 0,
    ) -> bool:
        current = scope_index
        origin_skips_class = self._scope_tree._origin_skips_class(scope_index)
        while current >= 0:
            scope = self._scope_tree.scopes[current]
            if scope.kind == ScopeKind.CLASS and origin_skips_class and current != scope_index:
                current = scope.parent_index
                continue

            sites = scope.binding_sites_by_name.get(name)
            if sites:
                module_deferred = (
                    scope.kind == ScopeKind.MODULE
                    and self._scope_tree._scope_in_function_body(  # noqa: E501
                        scope_index
                    )
                )
                if module_deferred:
                    visible = tuple(sites)
                else:
                    visible = tuple(
                        site for site in sites if _site_before_use(site, use_line, use_col)
                    )
                if not visible:
                    current = scope.parent_index
                    continue

                if len(visible) != 1:
                    return False
                site = visible[0]
                if name not in self.proven_names_by_scope.get(current, frozenset()):
                    return False
                if not _proven_typevar_site(site, current, scope, self._scope_tree):
                    return False
                return True

            current = scope.parent_index
        return False


def build_typevar_index(scope_tree: ScopeTree) -> TypeVarIndex:
    proven_by_scope: Dict[int, Set[str]] = {}
    for scope_index, scope in enumerate(scope_tree.scopes):
        if scope.kind not in (ScopeKind.MODULE, ScopeKind.FUNCTION):
            continue
        for name, sites in scope.binding_sites_by_name.items():
            if len(sites) != 1:
                continue
            site = sites[0]
            if not _proven_typevar_site(site, scope_index, scope, scope_tree):
                continue
            proven_by_scope.setdefault(scope_index, set()).add(name)
    return TypeVarIndex(
        _scope_tree=scope_tree,
        proven_names_by_scope={
            scope_index: frozenset(names) for scope_index, names in proven_by_scope.items()
        },
    )


def _proven_typevar_site(
    site: BindingSite,
    scope_index: int,
    scope: Scope,
    scope_tree: ScopeTree,
) -> bool:
    if site.binding_form != BindingForm.ASSIGN.value:
        return False
    if not _site_binds_typevar_call(site, scope_index, scope_tree):
        return False
    if scope.kind == ScopeKind.FUNCTION:
        if not site.direct_body or not site.unconditional:
            return False
    elif scope.kind == ScopeKind.MODULE:
        if not _is_direct_module_binding(site, scope.node):
            return False
    else:
        return False
    return True


def _is_direct_module_binding(site: BindingSite, scope_node: ast.AST) -> bool:
    if not isinstance(scope_node, ast.Module):
        return False
    for stmt in scope_node.body:
        if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            continue
        if stmt.lineno != site.line:
            continue
        if _site_matches_assignment_target(site, stmt):
            return True
    return False


def _site_matches_assignment_target(site: BindingSite, stmt: ast.Assign | ast.AnnAssign) -> bool:
    targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
    for target in targets:
        if isinstance(target, ast.Name) and target.id == site.name:
            return site.origin_node_id in (0, id(target))
    return False


def _site_binds_typevar_call(
    site: BindingSite,
    scope_index: int,
    scope_tree: ScopeTree,
) -> bool:
    value = scope_tree.site_values.get(site.site_id)
    if not isinstance(value, ast.Call):
        return False
    use_line = site.line
    use_col = site.column
    return (
        scope_tree.resolve_simple_symbol_identity(
            value.func,
            scope_index,
            use_line,
            use_col,
        )
        is SymbolIdentity.TYPING_TYPE_VAR
    )
