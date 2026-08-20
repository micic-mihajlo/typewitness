from __future__ import annotations

from typing import Protocol, Tuple

from typewitness.context import AnalysisContext
from typewitness.models import Finding


class Rule(Protocol):
    code: str
    name: str

    def check(self, context: AnalysisContext) -> Tuple[Finding, ...]: ...
