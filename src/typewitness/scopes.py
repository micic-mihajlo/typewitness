from __future__ import annotations

import ast
import heapq
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Dict, List, Mapping, Optional, Set, Tuple, Union

from typewitness._instrumentation import record

FunctionDefNode = Union[ast.FunctionDef, ast.AsyncFunctionDef]
ComprehensionExpr = Union[ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp]
ScopeNode = Union[ast.Module, ast.ClassDef, FunctionDefNode, ast.Lambda, ast.comprehension]

TryStar = getattr(ast, "TryStar", None)
Match = getattr(ast, "Match", None)
MatchAs = getattr(ast, "MatchAs", None)
MatchStar = getattr(ast, "MatchStar", None)
MatchMapping = getattr(ast, "MatchMapping", None)
TypeAlias = getattr(ast, "TypeAlias", None)
TypeVar = getattr(ast, "TypeVar", None)
TypeVarTuple = getattr(ast, "TypeVarTuple", None)
ParamSpec = getattr(ast, "ParamSpec", None)

TYPING_SYMBOLS = frozenset(
    {
        "Annotated",
        "Any",
        "Callable",
        "ClassVar",
        "Concatenate",
        "Final",
        "ForwardRef",
        "Generic",
        "Literal",
        "Optional",
        "ParamSpec",
        "Protocol",
        "Type",
        "TypeAlias",
        "TypeGuard",
        "TypeVar",
        "TypeVarTuple",
        "Union",
        "cast",
        "no_type_check",
        "overload",
        "runtime_checkable",
    }
)


class ResolutionKind(str, Enum):
    CAST_FN = "cast_fn"
    ANY_TYPE = "any_type"
    TYPING_MODULE = "typing_module"
    TYPING_EXT_MODULE = "typing_extensions_module"
    BUILTIN_OBJECT = "builtin_object"
    OPAQUE = "opaque"


class SymbolIdentity(str, Enum):
    UNKNOWN = "unknown"
    TYPING_NO_TYPE_CHECK = "typing.no_type_check"
    TYPING_TYPE_GUARD = "typing.TypeGuard"
    TYPING_TYPE_IS = "typing.TypeIs"
    TYPING_TYPE_VAR = "typing.TypeVar"
    TYPING_OVERLOAD = "typing.overload"
    TYPING_PROTOCOL = "typing.Protocol"
    TYPING_ANY = "typing.Any"
    MOCK_PATCH = "mock.patch"
    MOCK_PATCH_OBJECT = "mock.patch.object"
    MOCK_MODULE = "mock"
    JSON_MODULE = "json"
    JSON_LOAD = "json.load"
    JSON_LOADS = "json.loads"
    PICKLE_MODULE = "pickle"
    PICKLE_LOAD = "pickle.load"
    PICKLE_LOADS = "pickle.loads"
    MARSHAL_MODULE = "marshal"
    MARSHAL_LOAD = "marshal.load"
    MARSHAL_LOADS = "marshal.loads"
    TOMLLIB_MODULE = "tomllib"
    TOMLLIB_LOAD = "tomllib.load"
    TOMLLIB_LOADS = "tomllib.loads"
    PLISTLIB_MODULE = "plistlib"
    PLISTLIB_LOAD = "plistlib.load"
    PLISTLIB_LOADS = "plistlib.loads"
    AST_MODULE = "ast"
    AST_LITERAL_EVAL = "ast.literal_eval"
    UNITTEST_MODULE = "unittest"


_RESOLVABLE_SYMBOL_IDENTITIES = tuple(
    identity for identity in SymbolIdentity if identity is not SymbolIdentity.UNKNOWN
)
_SYMBOL_IDENTITY_BITS = {
    identity: 1 << index for index, identity in enumerate(_RESOLVABLE_SYMBOL_IDENTITIES)
}
_SYMBOL_IDENTITY_BY_BIT = {bit: identity for identity, bit in _SYMBOL_IDENTITY_BITS.items()}
_SYMBOL_IDENTITY_CONFLICT_BIT = 1 << len(_RESOLVABLE_SYMBOL_IDENTITIES)

_TYPING_SYMBOL_IDENTITIES = {
    "no_type_check": SymbolIdentity.TYPING_NO_TYPE_CHECK,
    "TypeGuard": SymbolIdentity.TYPING_TYPE_GUARD,
    "TypeIs": SymbolIdentity.TYPING_TYPE_IS,
    "TypeVar": SymbolIdentity.TYPING_TYPE_VAR,
    "overload": SymbolIdentity.TYPING_OVERLOAD,
    "Protocol": SymbolIdentity.TYPING_PROTOCOL,
    "Any": SymbolIdentity.TYPING_ANY,
}

_STDLIB_MODULE_IDENTITIES = {
    "json": SymbolIdentity.JSON_MODULE,
    "pickle": SymbolIdentity.PICKLE_MODULE,
    "marshal": SymbolIdentity.MARSHAL_MODULE,
    "tomllib": SymbolIdentity.TOMLLIB_MODULE,
    "plistlib": SymbolIdentity.PLISTLIB_MODULE,
    "ast": SymbolIdentity.AST_MODULE,
}

_STDLIB_FUNCTION_IDENTITIES = {
    ("json", "load"): SymbolIdentity.JSON_LOAD,
    ("json", "loads"): SymbolIdentity.JSON_LOADS,
    ("pickle", "load"): SymbolIdentity.PICKLE_LOAD,
    ("pickle", "loads"): SymbolIdentity.PICKLE_LOADS,
    ("marshal", "load"): SymbolIdentity.MARSHAL_LOAD,
    ("marshal", "loads"): SymbolIdentity.MARSHAL_LOADS,
    ("tomllib", "load"): SymbolIdentity.TOMLLIB_LOAD,
    ("tomllib", "loads"): SymbolIdentity.TOMLLIB_LOADS,
    ("plistlib", "load"): SymbolIdentity.PLISTLIB_LOAD,
    ("plistlib", "loads"): SymbolIdentity.PLISTLIB_LOADS,
    ("ast", "literal_eval"): SymbolIdentity.AST_LITERAL_EVAL,
}

_MODULE_ATTRIBUTE_IDENTITIES = {
    (SymbolIdentity.JSON_MODULE, "load"): SymbolIdentity.JSON_LOAD,
    (SymbolIdentity.JSON_MODULE, "loads"): SymbolIdentity.JSON_LOADS,
    (SymbolIdentity.PICKLE_MODULE, "load"): SymbolIdentity.PICKLE_LOAD,
    (SymbolIdentity.PICKLE_MODULE, "loads"): SymbolIdentity.PICKLE_LOADS,
    (SymbolIdentity.MARSHAL_MODULE, "load"): SymbolIdentity.MARSHAL_LOAD,
    (SymbolIdentity.MARSHAL_MODULE, "loads"): SymbolIdentity.MARSHAL_LOADS,
    (SymbolIdentity.TOMLLIB_MODULE, "load"): SymbolIdentity.TOMLLIB_LOAD,
    (SymbolIdentity.TOMLLIB_MODULE, "loads"): SymbolIdentity.TOMLLIB_LOADS,
    (SymbolIdentity.PLISTLIB_MODULE, "load"): SymbolIdentity.PLISTLIB_LOAD,
    (SymbolIdentity.PLISTLIB_MODULE, "loads"): SymbolIdentity.PLISTLIB_LOADS,
    (SymbolIdentity.AST_MODULE, "literal_eval"): SymbolIdentity.AST_LITERAL_EVAL,
    (SymbolIdentity.UNITTEST_MODULE, "mock"): SymbolIdentity.MOCK_MODULE,
    (SymbolIdentity.MOCK_MODULE, "patch"): SymbolIdentity.MOCK_PATCH,
    (SymbolIdentity.MOCK_PATCH, "object"): SymbolIdentity.MOCK_PATCH_OBJECT,
}


class ScopeKind(str, Enum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    LAMBDA = "lambda"
    COMPREHENSION = "comprehension"


class BindingForm(str, Enum):
    IMPORT = "import"
    PARAM = "param"
    ASSIGN = "assign"
    ANN_ASSIGN = "ann_assign"
    AUG_ASSIGN = "aug_assign"
    DELETE = "delete"
    FOR = "for"
    WITH = "with"
    EXCEPT = "except"
    EXCEPT_STAR = "except_star"
    MATCH = "match"
    WALRUS = "walrus"
    DEF = "def"
    CLASS = "class"
    GLOBAL = "global"
    NONLOCAL = "nonlocal"
    NONLOCAL_WRITE = "nonlocal_write"
    SHADOW = "shadow"


_RESOLUTION_KIND_BITS = {kind: 1 << index for index, kind in enumerate(ResolutionKind)}
_RESOLUTION_KIND_BY_BIT = {bit: kind for kind, bit in _RESOLUTION_KIND_BITS.items()}


def _resolution_for_mask(kind_mask: int) -> ResolutionKind:
    if kind_mask > 0 and kind_mask & (kind_mask - 1) == 0:
        return _RESOLUTION_KIND_BY_BIT[kind_mask]
    return ResolutionKind.OPAQUE


def _symbol_identity_for_mask(identity_mask: int) -> SymbolIdentity:
    if identity_mask & _SYMBOL_IDENTITY_CONFLICT_BIT:
        return SymbolIdentity.UNKNOWN
    masked = identity_mask & ~_SYMBOL_IDENTITY_CONFLICT_BIT
    if masked > 0 and masked & (masked - 1) == 0:
        return _SYMBOL_IDENTITY_BY_BIT[masked]
    return SymbolIdentity.UNKNOWN


def _symbol_identity_for_module_import(module_name: str) -> SymbolIdentity:
    if module_name == "mock":
        return SymbolIdentity.MOCK_MODULE
    if module_name == "unittest":
        return SymbolIdentity.UNITTEST_MODULE
    return _STDLIB_MODULE_IDENTITIES.get(module_name, SymbolIdentity.UNKNOWN)


def _symbol_identity_for_import_from(module: str, symbol: str) -> SymbolIdentity:
    if module in ("typing", "typing_extensions"):
        return _TYPING_SYMBOL_IDENTITIES.get(symbol, SymbolIdentity.UNKNOWN)
    if module in ("unittest.mock", "mock") and symbol == "patch":
        return SymbolIdentity.MOCK_PATCH
    if module == "unittest" and symbol == "mock":
        return SymbolIdentity.MOCK_MODULE
    return _STDLIB_FUNCTION_IDENTITIES.get((module, symbol), SymbolIdentity.UNKNOWN)


@dataclass(frozen=True)
class BindingSite:
    site_id: int
    name: str
    owner_scope_index: int
    kind: ResolutionKind
    line: int
    column: int = 0
    unconditional: bool = True
    binding_form: str = BindingForm.SHADOW.value
    direct_body: bool = False
    widened: bool = False
    origin_node_id: int = 0
    symbol_identity: SymbolIdentity = SymbolIdentity.UNKNOWN
    ambiguous_identity: bool = False


@dataclass(frozen=True)
class BindingResolutionIndex:
    positions: Tuple[Tuple[int, int], ...]
    unconditional_prefix_masks: Tuple[int, ...]
    conditional_prefix_masks: Tuple[int, ...]

    def kind_mask_before(self, line: int, column: int) -> int:
        target = (line, column)
        lo = 0
        hi = len(self.positions)
        while lo < hi:
            record("name_site_steps")
            mid = (lo + hi) // 2
            if self.positions[mid] < target:
                lo = mid + 1
            else:
                hi = mid
        unconditional = self.unconditional_prefix_masks[lo]
        return unconditional or self.conditional_prefix_masks[lo]

    def complete_kind_mask(self) -> int:
        record("name_site_steps")
        unconditional = self.unconditional_prefix_masks[-1]
        return unconditional or self.conditional_prefix_masks[-1]


@dataclass
class Scope:
    kind: ScopeKind
    name: str
    node: ScopeNode
    parent_index: int
    bindings: Dict[str, List[ResolutionKind]] = field(default_factory=dict)
    binding_sites: List[BindingSite] = field(default_factory=list)
    binding_sites_by_name: Mapping[str, Tuple[BindingSite, ...]] = field(default_factory=dict)
    binding_resolution_by_name: Mapping[str, BindingResolutionIndex] = field(default_factory=dict)
    symbol_identity_resolution_by_name: Mapping[str, BindingResolutionIndex] = field(
        default_factory=dict
    )
    children: List[int] = field(default_factory=list)
    predeclared_locals: Set[str] = field(default_factory=set)


@dataclass
class ScopeTree:
    scopes: List[Scope]
    node_scope: Dict[int, int]
    module_index: int
    scope_node_index: Dict[int, int] = field(default_factory=dict)
    line_scope_by_line: Tuple[int, ...] = ()
    site_values: Dict[int, Optional[ast.expr]] = field(default_factory=dict)

    def scope_path(self, scope_index: int) -> str:
        parts: List[str] = []
        chain: List[Scope] = []
        current = scope_index
        while current >= 0:
            chain.append(self.scopes[current])
            current = self.scopes[current].parent_index
        for scope in reversed(chain):
            if scope.kind == ScopeKind.CLASS:
                parts.append(f"class:{scope.name}")
            elif scope.kind in (ScopeKind.FUNCTION, ScopeKind.LAMBDA):
                parts.append(f"fn:{scope.name}")
            elif scope.kind == ScopeKind.COMPREHENSION:
                parts.append("comp:<comp>")
        return "@".join(parts) if parts else "module"

    def scope_for_node(self, node: ast.AST) -> int:
        return self.node_scope.get(id(node), self.module_index)

    def scope_index_for_node(self, node: ScopeNode) -> int:
        return self.scope_node_index.get(id(node), self.module_index)

    def scope_index_for_line(self, line: int, column: int = 0) -> int:
        del column
        record("line_scope_lookups")
        if 0 <= line < len(self.line_scope_by_line):
            return self.line_scope_by_line[line]
        return self.module_index

    def resolve_name(
        self,
        name: str,
        scope_index: int,
        use_line: int,
        use_col: int = 0,
    ) -> ResolutionKind:
        current = scope_index
        origin_skips_class = self._origin_skips_class(scope_index)
        while current >= 0:
            scope = self.scopes[current]
            if scope.kind == ScopeKind.CLASS and origin_skips_class and current != scope_index:
                current = scope.parent_index
                continue
            record("name_site_lookups")
            local_index = scope.binding_resolution_by_name.get(name)
            if local_index is not None:
                module_deferred = scope.kind == ScopeKind.MODULE and self._scope_in_function_body(
                    scope_index
                )
                if module_deferred:
                    kind_mask = local_index.complete_kind_mask()
                else:
                    kind_mask = local_index.kind_mask_before(use_line, use_col)
                if kind_mask == 0:
                    return ResolutionKind.OPAQUE
                return _resolution_for_mask(kind_mask)
            current = scope.parent_index
        if name == "object":
            return ResolutionKind.BUILTIN_OBJECT
        return ResolutionKind.OPAQUE

    def resolve_symbol_identity(
        self,
        name: str,
        scope_index: int,
        use_line: int,
        use_col: int = 0,
    ) -> SymbolIdentity:
        current = scope_index
        origin_skips_class = self._origin_skips_class(scope_index)
        while current >= 0:
            scope = self.scopes[current]
            if scope.kind == ScopeKind.CLASS and origin_skips_class and current != scope_index:
                current = scope.parent_index
                continue
            record("name_site_lookups")
            local_index = scope.symbol_identity_resolution_by_name.get(name)
            if local_index is not None:
                module_deferred = scope.kind == ScopeKind.MODULE and self._scope_in_function_body(
                    scope_index
                )
                if module_deferred:
                    identity_mask = local_index.complete_kind_mask()
                else:
                    identity_mask = local_index.kind_mask_before(use_line, use_col)
                if identity_mask == 0:
                    return SymbolIdentity.UNKNOWN
                return _symbol_identity_for_mask(identity_mask)
            current = scope.parent_index
        return SymbolIdentity.UNKNOWN

    def resolve_symbol_attribute(
        self,
        module_name: str,
        attr: str,
        scope_index: int,
        use_line: int,
        use_col: int = 0,
    ) -> SymbolIdentity:
        module_identity = self.resolve_symbol_identity(
            module_name,
            scope_index,
            use_line,
            use_col,
        )
        attribute_identity = _MODULE_ATTRIBUTE_IDENTITIES.get((module_identity, attr))
        if attribute_identity is not None:
            return attribute_identity
        module_kind = self.resolve_name(module_name, scope_index, use_line, use_col)
        if module_kind in (ResolutionKind.TYPING_MODULE, ResolutionKind.TYPING_EXT_MODULE):
            return _TYPING_SYMBOL_IDENTITIES.get(attr, SymbolIdentity.UNKNOWN)
        return SymbolIdentity.UNKNOWN

    def resolve_simple_symbol_identity(
        self,
        expr: ast.expr,
        scope_index: int,
        use_line: int,
        use_col: int = 0,
    ) -> SymbolIdentity:
        if isinstance(expr, ast.Name):
            return self.resolve_symbol_identity(expr.id, scope_index, use_line, use_col)
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
            return self.resolve_symbol_attribute(
                expr.value.id,
                expr.attr,
                scope_index,
                use_line,
                use_col,
            )
        return SymbolIdentity.UNKNOWN

    def resolve_expression_symbol_identity(
        self,
        expr: ast.expr,
        scope_index: int,
        use_line: int,
        use_col: int = 0,
    ) -> SymbolIdentity:
        if isinstance(expr, ast.Name):
            return self.resolve_symbol_identity(expr.id, scope_index, use_line, use_col)
        if isinstance(expr, ast.Attribute):
            base_identity = self.resolve_expression_symbol_identity(
                expr.value,
                scope_index,
                use_line,
                use_col,
            )
            if base_identity is SymbolIdentity.UNKNOWN:
                return SymbolIdentity.UNKNOWN
            attribute_identity = _MODULE_ATTRIBUTE_IDENTITIES.get((base_identity, expr.attr))
            if attribute_identity is not None:
                return attribute_identity
            return SymbolIdentity.UNKNOWN
        return SymbolIdentity.UNKNOWN

    def _origin_skips_class(self, scope_index: int) -> bool:
        return self.scopes[scope_index].kind in (
            ScopeKind.FUNCTION,
            ScopeKind.LAMBDA,
            ScopeKind.COMPREHENSION,
        )

    def _scope_in_function_body(self, scope_index: int) -> bool:
        current = scope_index
        while current >= 0:
            if self.scopes[current].kind == ScopeKind.FUNCTION:
                return True
            if self.scopes[current].kind == ScopeKind.MODULE:
                return False
            current = self.scopes[current].parent_index
        return False

    def function_binding_sites(self, scope_index: int) -> Tuple[BindingSite, ...]:
        scope = self.scopes[scope_index]
        if scope.kind != ScopeKind.FUNCTION:
            return ()
        return tuple(scope.binding_sites)

    def sites_for_name(self, scope_index: int, name: str) -> Tuple[BindingSite, ...]:
        record("name_site_lookups")
        return self.scopes[scope_index].binding_sites_by_name.get(name, ())

    def is_resolved_cast_call(self, node: ast.Call, scope_index: int) -> bool:
        use_line = getattr(node, "lineno", 1)
        use_col = getattr(node, "col_offset", 0)
        func = node.func
        if isinstance(func, ast.Name):
            return (
                self.resolve_name(func.id, scope_index, use_line, use_col) == ResolutionKind.CAST_FN
            )
        if isinstance(func, ast.Attribute) and func.attr == "cast":
            if isinstance(func.value, ast.Name):
                module_kind = self.resolve_name(func.value.id, scope_index, use_line, use_col)
                return module_kind in (
                    ResolutionKind.TYPING_MODULE,
                    ResolutionKind.TYPING_EXT_MODULE,
                )
        return False

    def is_resolved_no_type_check(
        self,
        node: ast.expr,
        scope_index: int,
    ) -> bool:
        use_line = getattr(node, "lineno", 1)
        use_col = getattr(node, "col_offset", 0)
        return (
            self.resolve_simple_symbol_identity(node, scope_index, use_line, use_col)
            is SymbolIdentity.TYPING_NO_TYPE_CHECK
        )

    def is_resolved_any_annotation(
        self, node: ast.AST, scope_index: int, use_line: int, use_col: int = 0
    ) -> bool:
        if isinstance(node, ast.Name):
            return (
                self.resolve_name(node.id, scope_index, use_line, use_col)
                == ResolutionKind.ANY_TYPE
            )
        if isinstance(node, ast.Attribute) and node.attr == "Any":
            if isinstance(node.value, ast.Name):
                module_kind = self.resolve_name(node.value.id, scope_index, use_line, use_col)
                return module_kind in (
                    ResolutionKind.TYPING_MODULE,
                    ResolutionKind.TYPING_EXT_MODULE,
                )
        return False

    def is_builtin_object_annotation(
        self, node: ast.AST, scope_index: int, use_line: int, use_col: int = 0
    ) -> bool:
        if not isinstance(node, ast.Name) or node.id != "object":
            return False
        return (
            self.resolve_name("object", scope_index, use_line, use_col)
            == ResolutionKind.BUILTIN_OBJECT
        )

    def resolve_mock_patch_call(
        self,
        node: ast.Call,
        scope_index: int,
    ) -> Optional[SymbolIdentity]:
        use_line = getattr(node, "lineno", 1)
        use_col = getattr(node, "col_offset", 0)
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in ("dict", "multiple", "stopall"):
            return None
        identity = self.resolve_expression_symbol_identity(func, scope_index, use_line, use_col)
        if identity in (SymbolIdentity.MOCK_PATCH, SymbolIdentity.MOCK_PATCH_OBJECT):
            return identity
        return None


def build_scope_tree(tree: ast.Module) -> ScopeTree:
    return _ScopeBuilder().build(tree)


def _binding_conflicts_with_known_identity(
    prior_sites: List[BindingSite],
    binding_form: str,
) -> bool:
    if binding_form in (
        BindingForm.GLOBAL.value,
        BindingForm.NONLOCAL.value,
        BindingForm.NONLOCAL_WRITE.value,
    ):
        return False
    return any(site.symbol_identity is not SymbolIdentity.UNKNOWN for site in prior_sites)


class _ScopeBuilder:
    """One semantic walk builds both the binding census and node ownership map.

    All statement and expression child traversal lives in `_visit_stmt`, `_visit_expr`,
    and `_visit_aux`. Unknown AST forms use `_visit_aux`, which conservatively assigns
    semantic descendants to the current scope.
    """

    def __init__(self) -> None:
        self.scopes: List[Scope] = []
        self.node_scope: Dict[int, int] = {}
        self._scope_node_index: Dict[int, int] = {}
        self._sites_by_scope_name: List[Dict[str, List[BindingSite]]] = []
        self._resolution_masks_by_scope_name: List[Dict[str, Tuple[int, int]]] = []
        self._site_values: Dict[int, Optional[ast.expr]] = {}
        self._scope_nonlocal: Dict[int, Set[str]] = {}
        self._scope_global: Dict[int, Set[str]] = {}
        self._current = -1
        self._site_counter = 0

    def build(self, tree: ast.Module) -> ScopeTree:
        module_index = self._push(ScopeKind.MODULE, "<module>", tree)
        self._assign_scope(tree, module_index)
        for stmt in tree.body:
            self._visit_stmt(stmt, conditional=False)
        self._finalize_nonlocal_writes()
        self._freeze_site_indexes()
        line_scope_by_line = _build_line_scope_map(self.scopes, tree, module_index)
        return ScopeTree(
            scopes=self.scopes,
            node_scope=self.node_scope,
            module_index=module_index,
            scope_node_index=dict(self._scope_node_index),
            line_scope_by_line=line_scope_by_line,
            site_values=dict(self._site_values),
        )

    def _push(self, kind: ScopeKind, name: str, node: ScopeNode) -> int:
        parent_index = self._current
        index = len(self.scopes)
        self.scopes.append(Scope(kind=kind, name=name, node=node, parent_index=parent_index))
        self._sites_by_scope_name.append({})
        self._resolution_masks_by_scope_name.append({})
        self._scope_node_index[id(node)] = index
        if parent_index >= 0:
            self.scopes[parent_index].children.append(index)
        self._current = index
        return index

    def _pop(self) -> None:
        self._current = self.scopes[self._current].parent_index

    def _assign_scope(self, node: ast.AST, scope_index: Optional[int] = None) -> None:
        owner = self._current if scope_index is None else scope_index
        self.node_scope[id(node)] = owner

    def _record_site(
        self,
        scope_index: int,
        name: str,
        binding_form: str,
        line: int,
        column: int = 0,
        *,
        kind: ResolutionKind = ResolutionKind.OPAQUE,
        unconditional: bool = True,
        direct_body: bool = False,
        widened: bool = False,
        value: Optional[ast.expr] = None,
        origin_node: Optional[ast.AST] = None,
        update_resolution: bool = True,
        symbol_identity: SymbolIdentity = SymbolIdentity.UNKNOWN,
    ) -> BindingSite:
        ambiguous_identity = False
        prior_sites = self._sites_by_scope_name[scope_index].get(name, [])
        if symbol_identity is not SymbolIdentity.UNKNOWN:
            if prior_sites:
                known_prior = [
                    site.symbol_identity
                    for site in prior_sites
                    if site.symbol_identity is not SymbolIdentity.UNKNOWN
                    and not site.ambiguous_identity
                ]
                if known_prior:
                    if any(prior_identity is not symbol_identity for prior_identity in known_prior):
                        ambiguous_identity = True
                        symbol_identity = SymbolIdentity.UNKNOWN
                elif any(site.binding_form != BindingForm.IMPORT.value for site in prior_sites):
                    ambiguous_identity = True
                    symbol_identity = SymbolIdentity.UNKNOWN
        elif _binding_conflicts_with_known_identity(prior_sites, binding_form):
            ambiguous_identity = True
        site = BindingSite(
            site_id=self._site_counter,
            name=name,
            owner_scope_index=scope_index,
            kind=kind,
            line=line,
            column=column,
            unconditional=unconditional,
            binding_form=binding_form,
            direct_body=direct_body,
            widened=widened,
            origin_node_id=id(origin_node) if origin_node is not None else 0,
            symbol_identity=symbol_identity,
            ambiguous_identity=ambiguous_identity,
        )
        self._site_counter += 1
        self.scopes[scope_index].binding_sites.append(site)
        self._sites_by_scope_name[scope_index].setdefault(name, []).append(site)
        unconditional_mask, conditional_mask = self._resolution_masks_by_scope_name[
            scope_index
        ].get(name, (0, 0))
        kind_mask = _RESOLUTION_KIND_BITS[site.kind]
        if site.unconditional:
            unconditional_mask |= kind_mask
        else:
            conditional_mask |= kind_mask
        self._resolution_masks_by_scope_name[scope_index][name] = (
            unconditional_mask,
            conditional_mask,
        )
        if value is not None:
            self._site_values[site.site_id] = value
        elif binding_form in (BindingForm.ASSIGN.value, BindingForm.ANN_ASSIGN.value):
            self._site_values[site.site_id] = None
        if update_resolution and kind != ResolutionKind.OPAQUE:
            self.scopes[scope_index].bindings.setdefault(name, []).append(kind)
        if binding_form not in (
            BindingForm.GLOBAL.value,
            BindingForm.NONLOCAL.value,
            BindingForm.IMPORT.value,
        ):
            self.scopes[scope_index].predeclared_locals.add(name)
        return site

    def _bind_import(
        self,
        name: str,
        kind: ResolutionKind,
        line: int,
        column: int,
        unconditional: bool,
        origin_node: ast.AST,
        *,
        symbol_identity: SymbolIdentity = SymbolIdentity.UNKNOWN,
    ) -> None:
        self._record_site(
            self._current,
            name,
            BindingForm.IMPORT.value,
            line,
            column,
            kind=kind,
            unconditional=unconditional,
            direct_body=self._direct_body(False),
            origin_node=origin_node,
            symbol_identity=symbol_identity,
        )

    def _bind_shadow(
        self,
        name: str,
        line: int,
        column: int,
        binding_form: str,
        *,
        scope_index: Optional[int] = None,
        unconditional: bool = True,
        direct_body: bool = False,
        widened: bool = False,
        value: Optional[ast.expr] = None,
        origin_node: Optional[ast.AST] = None,
    ) -> None:
        owner = self._current if scope_index is None else scope_index
        self._record_site(
            owner,
            name,
            binding_form,
            line,
            column,
            unconditional=unconditional,
            direct_body=direct_body,
            widened=widened,
            value=value,
            origin_node=origin_node,
        )

    def _direct_body(self, conditional: bool) -> bool:
        return self.scopes[self._current].kind == ScopeKind.FUNCTION and not conditional

    def _visit_stmt(self, node: ast.stmt, *, conditional: bool) -> None:
        self._assign_scope(node)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            self._visit_import(node, unconditional=not conditional)
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._visit_function(node, conditional=conditional)
            return
        if isinstance(node, ast.ClassDef):
            self._visit_class(node, conditional=conditional)
            return
        if isinstance(node, ast.Assign):
            for target in node.targets:
                self._visit_store_target(
                    target,
                    BindingForm.ASSIGN.value,
                    conditional,
                    value=node.value,
                )
            self._visit_expr(node.value)
            return
        if isinstance(node, ast.AnnAssign):
            widened = self._is_widened_annotation(
                node.annotation,
                getattr(node.target, "lineno", node.lineno),
                getattr(node.target, "col_offset", node.col_offset),
            )
            self._visit_store_target(
                node.target,
                BindingForm.ANN_ASSIGN.value,
                conditional,
                value=node.value,
                widened=widened,
            )
            self._visit_expr(node.annotation)
            if node.value is not None:
                self._visit_expr(node.value)
            return
        if isinstance(node, ast.AugAssign):
            self._visit_store_target(node.target, BindingForm.AUG_ASSIGN.value, conditional)
            self._visit_expr(node.value)
            return
        if isinstance(node, ast.Delete):
            for target in node.targets:
                self._visit_delete_target(target, conditional)
            return
        if isinstance(node, (ast.For, ast.AsyncFor)):
            self._visit_expr(node.iter)
            self._visit_store_target(node.target, BindingForm.FOR.value, conditional)
            self._visit_stmt_lists(node.body, node.orelse, conditional=True)
            return
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                self._assign_scope(item)
                self._visit_expr(item.context_expr)
                if item.optional_vars is not None:
                    self._visit_store_target(
                        item.optional_vars,
                        BindingForm.WITH.value,
                        conditional,
                    )
            for child in node.body:
                self._visit_stmt(child, conditional=True)
            return
        if _is_try_node(node):
            self._visit_try(node)
            return
        if Match is not None and isinstance(node, Match):
            self._visit_expr(node.subject)
            for case in node.cases:
                self._visit_match_case(case)
            return
        if isinstance(node, ast.Global):
            declarations = self._scope_global.setdefault(self._current, set())
            for name in node.names:
                declarations.add(name)
                self.scopes[self._current].predeclared_locals.discard(name)
                self._record_site(
                    self._current,
                    name,
                    BindingForm.GLOBAL.value,
                    node.lineno,
                    node.col_offset,
                    direct_body=self._direct_body(conditional),
                    origin_node=node,
                    update_resolution=False,
                )
            return
        if isinstance(node, ast.Nonlocal):
            declarations = self._scope_nonlocal.setdefault(self._current, set())
            for name in node.names:
                declarations.add(name)
                self.scopes[self._current].predeclared_locals.discard(name)
                self._record_site(
                    self._current,
                    name,
                    BindingForm.NONLOCAL.value,
                    node.lineno,
                    node.col_offset,
                    direct_body=self._direct_body(conditional),
                    origin_node=node,
                    update_resolution=False,
                )
            return
        if TypeAlias is not None and isinstance(node, TypeAlias):
            self._visit_type_alias(node, conditional)
            return
        if isinstance(node, (ast.If, ast.While)):
            self._visit_expr(node.test)
            self._visit_stmt_lists(node.body, node.orelse, conditional=True)
            return
        if isinstance(node, ast.Expr):
            self._visit_expr(node.value)
            return
        if isinstance(node, ast.Return):
            if node.value is not None:
                self._visit_expr(node.value)
            return
        if isinstance(node, ast.Raise):
            if node.exc is not None:
                self._visit_expr(node.exc)
            if node.cause is not None:
                self._visit_expr(node.cause)
            return
        if isinstance(node, ast.Assert):
            self._visit_expr(node.test)
            if node.msg is not None:
                self._visit_expr(node.msg)
            return
        # Mandatory conservative fallback for future statement syntax.
        self._visit_unknown_children(node, conditional=conditional)

    def _visit_stmt_lists(
        self,
        first: List[ast.stmt],
        second: List[ast.stmt],
        *,
        conditional: bool,
    ) -> None:
        for child in first:
            self._visit_stmt(child, conditional=conditional)
        for child in second:
            self._visit_stmt(child, conditional=conditional)

    def _visit_function(self, node: FunctionDefNode, *, conditional: bool) -> None:
        self._bind_shadow(
            node.name,
            node.lineno,
            node.col_offset,
            BindingForm.DEF.value,
            direct_body=self._direct_body(conditional),
            origin_node=node,
        )
        outer_scope = self._current
        for decorator in node.decorator_list:
            self._visit_expr(decorator)
        for default in list(node.args.defaults) + list(node.args.kw_defaults):
            if default is not None:
                self._visit_expr(default)
        for arg in _argument_nodes(node.args):
            self._assign_scope(arg, outer_scope)
            if arg.annotation is not None:
                self._visit_expr(arg.annotation)
        if node.returns is not None:
            self._visit_expr(node.returns)

        function_index = self._push(ScopeKind.FUNCTION, node.name, node)
        for type_param in getattr(node, "type_params", ()):
            self._visit_type_param(type_param, function_index)
        for arg in _argument_nodes(node.args):
            self._bind_shadow(
                arg.arg,
                node.lineno,
                getattr(arg, "col_offset", node.col_offset),
                BindingForm.PARAM.value,
                direct_body=True,
                origin_node=arg,
            )
        for stmt in node.body:
            self._visit_stmt(stmt, conditional=False)
        self._pop()
        self._current = outer_scope

    def _visit_class(self, node: ast.ClassDef, *, conditional: bool) -> None:
        self._bind_shadow(
            node.name,
            node.lineno,
            node.col_offset,
            BindingForm.CLASS.value,
            direct_body=self._direct_body(conditional),
            origin_node=node,
        )
        outer_scope = self._current
        for decorator in node.decorator_list:
            self._visit_expr(decorator)
        for base in node.bases:
            self._visit_expr(base)
        for keyword in node.keywords:
            self._visit_aux(keyword)

        class_index = self._push(ScopeKind.CLASS, node.name, node)
        for type_param in getattr(node, "type_params", ()):
            self._visit_type_param(type_param, class_index)
        for stmt in node.body:
            self._visit_stmt(stmt, conditional=False)
        self._pop()
        self._current = outer_scope

    def _visit_import(
        self,
        node: Union[ast.Import, ast.ImportFrom],
        *,
        unconditional: bool,
    ) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                if alias.name == "typing":
                    kind = ResolutionKind.TYPING_MODULE
                elif alias.name == "typing_extensions":
                    kind = ResolutionKind.TYPING_EXT_MODULE
                else:
                    kind = ResolutionKind.OPAQUE
                if alias.name == "unittest.mock":
                    symbol_identity = (
                        SymbolIdentity.MOCK_MODULE
                        if alias.asname is not None
                        else SymbolIdentity.UNITTEST_MODULE
                    )
                else:
                    symbol_identity = _symbol_identity_for_module_import(alias.name)
                self._bind_import(
                    bound,
                    kind,
                    node.lineno,
                    node.col_offset,
                    unconditional,
                    node,
                    symbol_identity=symbol_identity,
                )
            return

        module = node.module or ""
        relative_import = node.level > 0
        for alias in node.names:
            if alias.name == "*":
                if module not in ("typing", "typing_extensions"):
                    continue
                for symbol in TYPING_SYMBOLS:
                    if symbol == "cast":
                        kind = ResolutionKind.CAST_FN
                    elif symbol == "Any":
                        kind = ResolutionKind.ANY_TYPE
                    else:
                        kind = ResolutionKind.OPAQUE
                    if relative_import:
                        symbol_identity = SymbolIdentity.UNKNOWN
                    else:
                        symbol_identity = _TYPING_SYMBOL_IDENTITIES.get(
                            symbol, SymbolIdentity.UNKNOWN
                        )
                    self._bind_import(
                        symbol,
                        kind,
                        node.lineno,
                        node.col_offset,
                        unconditional,
                        node,
                        symbol_identity=symbol_identity,
                    )
                continue
            bound = alias.asname or alias.name
            if module in ("typing", "typing_extensions") and alias.name == "cast":
                kind = ResolutionKind.CAST_FN
            elif module in ("typing", "typing_extensions") and alias.name == "Any":
                kind = ResolutionKind.ANY_TYPE
            else:
                kind = ResolutionKind.OPAQUE
            if relative_import:
                symbol_identity = SymbolIdentity.UNKNOWN
            else:
                symbol_identity = _symbol_identity_for_import_from(module, alias.name)
            self._bind_import(
                bound,
                kind,
                node.lineno,
                node.col_offset,
                unconditional,
                node,
                symbol_identity=symbol_identity,
            )

    def _visit_try(self, node: ast.stmt) -> None:
        for child in getattr(node, "body", ()):
            self._visit_stmt(child, conditional=True)
        except_form = (
            BindingForm.EXCEPT_STAR.value
            if TryStar is not None and isinstance(node, TryStar)
            else BindingForm.EXCEPT.value
        )
        for handler in getattr(node, "handlers", ()):
            self._assign_scope(handler)
            if handler.type is not None:
                self._visit_expr(handler.type)
            if handler.name is not None:
                self._bind_shadow(
                    handler.name,
                    handler.lineno,
                    handler.col_offset,
                    except_form,
                    direct_body=False,
                    origin_node=handler,
                )
            for child in handler.body:
                self._visit_stmt(child, conditional=True)
        for child in getattr(node, "orelse", ()):
            self._visit_stmt(child, conditional=True)
        for child in getattr(node, "finalbody", ()):
            self._visit_stmt(child, conditional=True)

    def _visit_match_case(self, case: ast.AST) -> None:
        self._assign_scope(case)
        pattern = getattr(case, "pattern", None)
        if pattern is not None:
            self._visit_pattern(pattern)
        guard = getattr(case, "guard", None)
        if guard is not None:
            self._visit_expr(guard)
        for stmt in getattr(case, "body", ()):
            self._visit_stmt(stmt, conditional=True)

    def _visit_pattern(self, pattern: ast.AST) -> None:
        self._assign_scope(pattern)
        if MatchAs is not None and isinstance(pattern, MatchAs):
            if pattern.name is not None:
                self._bind_shadow(
                    pattern.name,
                    pattern.lineno,
                    pattern.col_offset,
                    BindingForm.MATCH.value,
                    direct_body=False,
                    origin_node=pattern,
                )
        elif MatchStar is not None and isinstance(pattern, MatchStar):
            if pattern.name is not None:
                self._bind_shadow(
                    pattern.name,
                    pattern.lineno,
                    getattr(pattern, "col_offset", 0),
                    BindingForm.MATCH.value,
                    direct_body=False,
                    origin_node=pattern,
                )
        elif MatchMapping is not None and isinstance(pattern, MatchMapping):
            if pattern.rest is not None:
                self._bind_shadow(
                    pattern.rest,
                    pattern.lineno,
                    getattr(pattern, "col_offset", 0),
                    BindingForm.MATCH.value,
                    direct_body=False,
                    origin_node=pattern,
                )
        for child in ast.iter_child_nodes(pattern):
            if isinstance(child, ast.expr):
                self._visit_expr(child)
            elif _is_pattern_node(child):
                self._visit_pattern(child)
            else:
                self._visit_aux(child)

    def _visit_type_alias(self, node: ast.AST, conditional: bool) -> None:
        name_node = getattr(node, "name", None)
        if isinstance(name_node, ast.Name):
            self._assign_scope(name_node)
            self._bind_shadow(
                name_node.id,
                name_node.lineno,
                name_node.col_offset,
                BindingForm.ASSIGN.value,
                direct_body=self._direct_body(conditional),
                origin_node=node,
            )
        for type_param in getattr(node, "type_params", ()):
            self._visit_type_param(type_param, self._current)
        value = getattr(node, "value", None)
        if isinstance(value, ast.expr):
            self._visit_expr(value)
        else:
            self._visit_unknown_children(node, conditional=conditional, skip_ids={id(name_node)})

    def _visit_type_param(self, param: ast.AST, scope_index: int) -> None:
        self._assign_scope(param, scope_index)
        name = getattr(param, "name", None)
        if isinstance(name, str):
            self._bind_shadow(
                name,
                getattr(param, "lineno", 0),
                getattr(param, "col_offset", 0),
                BindingForm.PARAM.value,
                scope_index=scope_index,
                direct_body=True,
                origin_node=param,
            )
        for field_name in ("bound", "default_value"):
            value = getattr(param, field_name, None)
            if isinstance(value, ast.expr):
                self._visit_expr_in_scope(value, scope_index)
            elif isinstance(value, ast.AST):
                self._visit_aux_in_scope(value, scope_index)

    def _visit_store_target(
        self,
        target: ast.expr,
        binding_form: str,
        conditional: bool,
        *,
        value: Optional[ast.expr] = None,
        widened: bool = False,
    ) -> None:
        self._assign_scope(target)
        if isinstance(target, ast.Name):
            self._bind_shadow(
                target.id,
                target.lineno,
                target.col_offset,
                binding_form,
                direct_body=self._direct_body(conditional),
                widened=widened,
                value=value,
                origin_node=target,
            )
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._visit_store_target(
                    element,
                    binding_form,
                    conditional,
                    value=value,
                    widened=widened,
                )
            return
        if isinstance(target, ast.Starred):
            self._visit_store_target(
                target.value,
                binding_form,
                conditional,
                value=value,
                widened=widened,
            )
            return
        if isinstance(target, ast.Attribute):
            self._visit_expr(target.value)
            return
        if isinstance(target, ast.Subscript):
            self._visit_expr(target.value)
            self._visit_expr(target.slice)
            return
        # Unknown future target forms still expose their semantic expressions.
        self._visit_unknown_children(target, conditional=conditional)

    def _visit_delete_target(self, target: ast.expr, conditional: bool) -> None:
        self._assign_scope(target)
        if isinstance(target, ast.Name):
            self._bind_shadow(
                target.id,
                target.lineno,
                target.col_offset,
                BindingForm.DELETE.value,
                direct_body=self._direct_body(conditional),
                origin_node=target,
            )
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._visit_delete_target(element, conditional)
            return
        if isinstance(target, ast.Starred):
            self._visit_delete_target(target.value, conditional)
            return
        if isinstance(target, ast.Attribute):
            self._visit_expr(target.value)
            return
        if isinstance(target, ast.Subscript):
            self._visit_expr(target.value)
            self._visit_expr(target.slice)
            return
        self._visit_unknown_children(target, conditional=conditional)

    def _visit_expr(self, node: ast.expr) -> None:
        self._assign_scope(node)
        if isinstance(node, ast.NamedExpr):
            owner = self._walrus_owner(self._current)
            self._assign_scope(node.target, owner)
            if isinstance(node.target, ast.Name):
                self._bind_shadow(
                    node.target.id,
                    node.target.lineno,
                    node.target.col_offset,
                    BindingForm.WALRUS.value,
                    scope_index=owner,
                    direct_body=False,
                    value=node.value,
                    origin_node=node,
                )
            else:
                saved = self._current
                self._current = owner
                self._visit_store_target(node.target, BindingForm.WALRUS.value, True)
                self._current = saved
            self._visit_expr(node.value)
            return
        if isinstance(node, ast.Lambda):
            self._visit_lambda(node)
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            self._visit_comprehension(node)
            return
        # This generic expression fallback is the shared child-field inventory.
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                self._visit_expr(child)
            elif isinstance(child, ast.comprehension):
                self._visit_aux(child)
            else:
                self._visit_aux(child)

    def _visit_lambda(self, node: ast.Lambda) -> None:
        outer_scope = self._current
        for default in list(node.args.defaults) + list(node.args.kw_defaults):
            if default is not None:
                self._visit_expr(default)
        for arg in _argument_nodes(node.args):
            self._assign_scope(arg, outer_scope)
            if arg.annotation is not None:
                self._visit_expr(arg.annotation)
        lambda_index = self._push(ScopeKind.LAMBDA, "<lambda>", node)
        for arg in _argument_nodes(node.args):
            self._bind_shadow(
                arg.arg,
                node.lineno,
                getattr(arg, "col_offset", node.col_offset),
                BindingForm.PARAM.value,
                direct_body=True,
                origin_node=arg,
            )
        self._visit_expr(node.body)
        self._pop()
        self._current = outer_scope
        self.node_scope[id(node)] = outer_scope
        self._scope_node_index[id(node)] = lambda_index

    def _visit_comprehension(self, node: ComprehensionExpr) -> None:
        outer_scope = self._current
        first_generator = node.generators[0]
        self._visit_expr(first_generator.iter)
        comp_index = self._push(ScopeKind.COMPREHENSION, "<comp>", first_generator)
        for index, generator in enumerate(node.generators):
            self._assign_scope(generator, comp_index)
            if index > 0:
                self._visit_expr(generator.iter)
            self._visit_store_target(generator.target, BindingForm.FOR.value, True)
            for if_clause in generator.ifs:
                self._visit_expr(if_clause)
        if isinstance(node, ast.DictComp):
            self._visit_expr(node.key)
            self._visit_expr(node.value)
        else:
            self._visit_expr(node.elt)
        self._pop()
        self._current = outer_scope
        self.node_scope[id(node)] = outer_scope
        self._scope_node_index[id(first_generator)] = comp_index

    def _visit_expr_in_scope(self, node: ast.expr, scope_index: int) -> None:
        saved = self._current
        self._current = scope_index
        self._visit_expr(node)
        self._current = saved

    def _visit_aux(self, node: ast.AST) -> None:
        self._assign_scope(node)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                self._visit_stmt(child, conditional=True)
            elif isinstance(child, ast.expr):
                self._visit_expr(child)
            elif _is_pattern_node(child):
                self._visit_pattern(child)
            else:
                self._visit_aux(child)

    def _visit_aux_in_scope(self, node: ast.AST, scope_index: int) -> None:
        saved = self._current
        self._current = scope_index
        self._visit_aux(node)
        self._current = saved

    def _visit_unknown_children(
        self,
        node: ast.AST,
        *,
        conditional: bool,
        skip_ids: Optional[Set[int]] = None,
    ) -> None:
        skipped = skip_ids or set()
        for child in ast.iter_child_nodes(node):
            if id(child) in skipped:
                continue
            if isinstance(child, ast.stmt):
                self._visit_stmt(child, conditional=conditional)
            elif isinstance(child, ast.expr):
                self._visit_expr(child)
            elif _is_pattern_node(child):
                self._visit_pattern(child)
            else:
                self._visit_aux(child)

    def _walrus_owner(self, scope_index: int) -> int:
        current = scope_index
        while current >= 0 and self.scopes[current].kind == ScopeKind.COMPREHENSION:
            current = self.scopes[current].parent_index
        return current if current >= 0 else scope_index

    def _is_widened_annotation(self, annotation: ast.expr, line: int, column: int) -> bool:
        if isinstance(annotation, ast.Name):
            expected = (
                ResolutionKind.BUILTIN_OBJECT
                if annotation.id == "object"
                else ResolutionKind.ANY_TYPE
            )
            return self._resolve_in_scope(annotation.id, self._current, line, column) == expected
        if isinstance(annotation, ast.Attribute) and annotation.attr == "Any":
            if isinstance(annotation.value, ast.Name):
                resolved = self._resolve_in_scope(
                    annotation.value.id,
                    self._current,
                    line,
                    column,
                )
                return resolved in (
                    ResolutionKind.TYPING_MODULE,
                    ResolutionKind.TYPING_EXT_MODULE,
                )
        return False

    def _resolve_in_scope(
        self,
        name: str,
        scope_index: int,
        use_line: int,
        use_col: int,
    ) -> ResolutionKind:
        current = scope_index
        while current >= 0:
            record("name_site_lookups")
            masks = self._resolution_masks_by_scope_name[current].get(name)
            if masks is not None:
                unconditional_mask, conditional_mask = masks
                kind_mask = unconditional_mask | conditional_mask
                return _resolution_for_mask(kind_mask)
            current = self.scopes[current].parent_index
        if name == "object":
            return ResolutionKind.BUILTIN_OBJECT
        return ResolutionKind.OPAQUE

    def _finalize_nonlocal_writes(self) -> None:
        original_sites = [tuple(scope.binding_sites) for scope in self.scopes]
        for scope_index, names in self._scope_nonlocal.items():
            for site in original_sites[scope_index]:
                if site.name not in names or site.binding_form in (
                    BindingForm.NONLOCAL.value,
                    BindingForm.GLOBAL.value,
                    BindingForm.IMPORT.value,
                    BindingForm.DEF.value,
                    BindingForm.CLASS.value,
                ):
                    continue
                target = self._find_nonlocal_target(scope_index, site.name)
                if target is None:
                    continue
                self._record_site(
                    target,
                    site.name,
                    BindingForm.NONLOCAL_WRITE.value,
                    site.line,
                    site.column,
                    direct_body=False,
                    update_resolution=False,
                )

    def _find_nonlocal_target(self, scope_index: int, name: str) -> Optional[int]:
        current = self.scopes[scope_index].parent_index
        while current >= 0:
            scope = self.scopes[current]
            if scope.kind == ScopeKind.FUNCTION:
                if name in self._sites_by_scope_name[current] or name in scope.predeclared_locals:
                    return current
            current = scope.parent_index
        return None

    def _freeze_site_indexes(self) -> None:
        for scope, by_name in zip(
            self.scopes,
            self._sites_by_scope_name,
        ):
            frozen_sites: Dict[str, Tuple[BindingSite, ...]] = {}
            resolution_indexes: Dict[str, BindingResolutionIndex] = {}
            symbol_identity_indexes: Dict[str, BindingResolutionIndex] = {}
            for name, sites in by_name.items():
                ordered_sites = tuple(
                    sorted(sites, key=lambda site: (site.line, site.column, site.site_id))
                )
                frozen_sites[name] = ordered_sites
                unconditional_masks = [0]
                conditional_masks = [0]
                identity_unconditional_masks = [0]
                identity_conditional_masks = [0]
                for site in ordered_sites:
                    unconditional = unconditional_masks[-1]
                    conditional = conditional_masks[-1]
                    if site.unconditional:
                        unconditional |= _RESOLUTION_KIND_BITS[site.kind]
                    else:
                        conditional |= _RESOLUTION_KIND_BITS[site.kind]
                    unconditional_masks.append(unconditional)
                    conditional_masks.append(conditional)
                    identity_unconditional = identity_unconditional_masks[-1]
                    identity_conditional = identity_conditional_masks[-1]
                    if site.ambiguous_identity:
                        identity_unconditional |= _SYMBOL_IDENTITY_CONFLICT_BIT
                        identity_conditional |= _SYMBOL_IDENTITY_CONFLICT_BIT
                    elif site.symbol_identity is not SymbolIdentity.UNKNOWN:
                        identity_bit = _SYMBOL_IDENTITY_BITS[site.symbol_identity]
                        if site.unconditional:
                            identity_unconditional |= identity_bit
                        else:
                            identity_conditional |= identity_bit
                    identity_unconditional_masks.append(identity_unconditional)
                    identity_conditional_masks.append(identity_conditional)
                resolution_indexes[name] = BindingResolutionIndex(
                    positions=tuple((site.line, site.column) for site in ordered_sites),
                    unconditional_prefix_masks=tuple(unconditional_masks),
                    conditional_prefix_masks=tuple(conditional_masks),
                )
                symbol_identity_indexes[name] = BindingResolutionIndex(
                    positions=tuple((site.line, site.column) for site in ordered_sites),
                    unconditional_prefix_masks=tuple(identity_unconditional_masks),
                    conditional_prefix_masks=tuple(identity_conditional_masks),
                )
            scope.binding_sites_by_name = MappingProxyType(frozen_sites)
            scope.binding_resolution_by_name = MappingProxyType(resolution_indexes)
            scope.symbol_identity_resolution_by_name = MappingProxyType(symbol_identity_indexes)


def _is_try_node(node: ast.AST) -> bool:
    return isinstance(node, ast.Try) or (TryStar is not None and isinstance(node, TryStar))


def _is_pattern_node(node: ast.AST) -> bool:
    pattern_type = getattr(ast, "pattern", None)
    return pattern_type is not None and isinstance(node, pattern_type)


def _argument_nodes(args: ast.arguments) -> List[ast.arg]:
    nodes = list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
    if args.vararg is not None:
        nodes.append(args.vararg)
    if args.kwarg is not None:
        nodes.append(args.kwarg)
    return nodes


def _scope_depth(scopes: List[Scope], scope_index: int) -> int:
    depth = 0
    current = scope_index
    while current >= 0:
        depth += 1
        current = scopes[current].parent_index
    return depth


def _build_line_scope_map(
    scopes: List[Scope],
    tree: ast.Module,
    module_index: int,
) -> Tuple[int, ...]:
    max_line = max((getattr(node, "end_lineno", 0) or 0 for node in ast.walk(tree)), default=0)
    starts: Dict[int, List[Tuple[int, int, int]]] = {}
    for index, scope in enumerate(scopes):
        node = scope.node
        start_line = getattr(node, "lineno", None)
        if start_line is None:
            continue
        end_line = getattr(node, "end_lineno", None) or start_line
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            start_line = getattr(node.body[0], "lineno", start_line)
        starts.setdefault(start_line, []).append((_scope_depth(scopes, index), end_line, index))

    result = [module_index] * (max_line + 1)
    active: List[Tuple[int, int, int]] = []
    for line in range(1, max_line + 1):
        for depth, end_line, scope_index in starts.get(line, ()):
            heapq.heappush(active, (-depth, end_line, scope_index))
        while active and active[0][1] < line:
            heapq.heappop(active)
        if active:
            result[line] = active[0][2]
    return tuple(result)
