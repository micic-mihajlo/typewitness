from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Dict

from typewitness.candidates import CandidateSet
from typewitness.effects import EffectIndex
from typewitness.fingerprint import FingerprintTable
from typewitness.models import Config, SourceFile
from typewitness.scopes import ScopeTree
from typewitness.source_index import SourceIndex


@dataclass(frozen=True)
class AnalysisContext:
    source: SourceFile
    tree: ast.Module
    parent_by_node_id: Dict[int, ast.AST]
    source_index: SourceIndex
    scope_tree: ScopeTree
    candidates: CandidateSet
    fingerprints: FingerprintTable
    effects: EffectIndex | None
    config: Config
