from __future__ import annotations

from typewitness.catalog import validate_rule_registration
from typewitness.rules.tw001 import NoChainedCastRule
from typewitness.rules.tw002 import CastNeedsEvidenceRule
from typewitness.rules.tw003 import TypedIgnoreNeedsEvidenceRule
from typewitness.rules.tw004 import NoWidenThenCastRule
from typewitness.rules.tw005 import CastToAnyRule
from typewitness.rules.tw006 import DiscardedCastRule
from typewitness.rules.tw007 import CheckerDisableNeedsEvidenceRule
from typewitness.rules.tw008 import NoTypeCheckNeedsEvidenceRule
from typewitness.rules.tw009 import MockPatchCreateNeedsEvidenceRule
from typewitness.rules.tw010 import ConstantTypeGuardRule
from typewitness.rules.tw011 import UnvalidatedBoundaryCastRule
from typewitness.rules.tw012 import MockPatchNeedsSpecRule
from typewitness.rules.tw013 import CastToTypeVarRule

RULES = (
    NoChainedCastRule(),
    CastNeedsEvidenceRule(),
    TypedIgnoreNeedsEvidenceRule(),
    NoWidenThenCastRule(),
    CastToAnyRule(),
    DiscardedCastRule(),
    CheckerDisableNeedsEvidenceRule(),
    NoTypeCheckNeedsEvidenceRule(),
    MockPatchCreateNeedsEvidenceRule(),
    ConstantTypeGuardRule(),
    UnvalidatedBoundaryCastRule(),
    MockPatchNeedsSpecRule(),
    CastToTypeVarRule(),
)

validate_rule_registration(frozenset(rule.code for rule in RULES))

__all__ = ["RULES"]
