from __future__ import annotations

from typewitness.rules.tw001 import NoChainedCastRule
from typewitness.rules.tw002 import CastNeedsEvidenceRule
from typewitness.rules.tw003 import TypedIgnoreNeedsEvidenceRule
from typewitness.rules.tw004 import NoWidenThenCastRule

RULES = (
    NoChainedCastRule(),
    CastNeedsEvidenceRule(),
    TypedIgnoreNeedsEvidenceRule(),
    NoWidenThenCastRule(),
)

__all__ = ["RULES"]
