from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Tuple

DOCS_BASE_URL = "https://github.com/micic-mihajlo/typewitness"


def heading_anchor(heading: str) -> str:
    return "".join(
        char if (char.isalnum() or char in "-_") else ("-" if char == " " else "")
        for char in heading.lower()
    )


@dataclass(frozen=True)
class RuleDescriptor:
    code: str
    name: str
    summary: str
    help_heading: str
    default_enabled: bool
    experimental: bool
    suppressible: bool
    scoped_only_suppression: bool
    requires_effect_index: bool
    requires_typevar_index: bool

    @property
    def help_uri(self) -> str:
        return f"{DOCS_BASE_URL}#{heading_anchor(self.help_heading)}"

    @property
    def level(self) -> str:
        return "note" if self.experimental else "warning"


RULE_DESCRIPTORS: Tuple[RuleDescriptor, ...] = (
    RuleDescriptor(
        code="TW001",
        name="no-chained-cast",
        summary="A typing.cast call whose value argument is directly another cast.",
        help_heading="TW001 — no-chained-cast",
        default_enabled=True,
        experimental=False,
        suppressible=False,
        scoped_only_suppression=False,
        requires_effect_index=False,
        requires_typevar_index=False,
    ),
    RuleDescriptor(
        code="TW002",
        name="cast-needs-evidence",
        summary="A resolved typing.cast call with no SAFETY evidence on its statement.",
        help_heading="TW002 — cast-needs-evidence",
        default_enabled=True,
        experimental=False,
        suppressible=True,
        scoped_only_suppression=False,
        requires_effect_index=False,
        requires_typevar_index=False,
    ),
    RuleDescriptor(
        code="TW003",
        name="typed-ignore-needs-evidence",
        summary="A type: ignore comment missing error codes, SAFETY evidence, or both.",
        help_heading="TW003 — typed-ignore-needs-evidence",
        default_enabled=True,
        experimental=False,
        suppressible=True,
        scoped_only_suppression=False,
        requires_effect_index=False,
        requires_typevar_index=False,
    ),
    RuleDescriptor(
        code="TW004",
        name="no-widen-then-cast",
        summary="A cast of a local name that was widened to Any or object from a literal.",
        help_heading="TW004 — no-widen-then-cast (experimental)",
        default_enabled=False,
        experimental=True,
        suppressible=True,
        scoped_only_suppression=True,
        requires_effect_index=True,
        requires_typevar_index=False,
    ),
    RuleDescriptor(
        code="TW005",
        name="cast-to-any",
        summary="A resolved typing.cast whose type argument resolves to typing.Any.",
        help_heading="TW005 — cast-to-any",
        default_enabled=True,
        experimental=False,
        suppressible=True,
        scoped_only_suppression=True,
        requires_effect_index=False,
        requires_typevar_index=False,
    ),
    RuleDescriptor(
        code="TW006",
        name="discarded-cast",
        summary="A resolved cast whose result is the entire value of an expression statement.",
        help_heading="TW006 — discarded-cast",
        default_enabled=True,
        experimental=False,
        suppressible=True,
        scoped_only_suppression=True,
        requires_effect_index=False,
        requires_typevar_index=False,
    ),
    RuleDescriptor(
        code="TW007",
        name="checker-disable-needs-evidence",
        summary=(
            "A scope-wide mypy or pyright disable comment at column 0 anywhere in the "
            "module with no immediately preceding SAFETY evidence."
        ),
        help_heading="TW007 — checker-disable-needs-evidence",
        default_enabled=True,
        experimental=False,
        suppressible=True,
        scoped_only_suppression=False,
        requires_effect_index=False,
        requires_typevar_index=False,
    ),
    RuleDescriptor(
        code="TW008",
        name="no-type-check-needs-evidence",
        summary=(
            "A resolved @no_type_check decorator on a function or class with no SAFETY evidence."
        ),
        help_heading="TW008 — no-type-check-needs-evidence",
        default_enabled=True,
        experimental=False,
        suppressible=True,
        scoped_only_suppression=False,
        requires_effect_index=False,
        requires_typevar_index=False,
    ),
    RuleDescriptor(
        code="TW009",
        name="mock-patch-create-needs-evidence",
        summary=(
            "A resolved unittest.mock.patch or patch.object call with literal create=True "
            "and no SAFETY evidence."
        ),
        help_heading="TW009 — mock-patch-create-needs-evidence",
        default_enabled=True,
        experimental=False,
        suppressible=True,
        scoped_only_suppression=False,
        requires_effect_index=False,
        requires_typevar_index=False,
    ),
    RuleDescriptor(
        code="TW010",
        name="constant-type-guard",
        summary=(
            "A narrowing function whose body is only return True or return False "
            "after an optional docstring."
        ),
        help_heading="TW010 — constant-type-guard",
        default_enabled=True,
        experimental=False,
        suppressible=True,
        scoped_only_suppression=True,
        requires_effect_index=False,
        requires_typevar_index=False,
    ),
    RuleDescriptor(
        code="TW011",
        name="unvalidated-boundary-cast",
        summary="A cast of an allowlisted stdlib boundary parse without validation.",
        help_heading="TW011 — unvalidated-boundary-cast (experimental)",
        default_enabled=False,
        experimental=True,
        suppressible=True,
        scoped_only_suppression=True,
        requires_effect_index=False,
        requires_typevar_index=False,
    ),
    RuleDescriptor(
        code="TW012",
        name="mock-patch-needs-spec",
        summary=(
            "A resolved patch or patch.object call with no explicit autospec, spec, spec_set, "
            "new, new_callable, or wraps keyword."
        ),
        help_heading="TW012 — mock-patch-needs-spec (experimental)",
        default_enabled=False,
        experimental=True,
        suppressible=True,
        scoped_only_suppression=False,
        requires_effect_index=False,
        requires_typevar_index=False,
    ),
    RuleDescriptor(
        code="TW013",
        name="cast-to-typevar",
        summary=(
            "A resolved cast whose bare Name target is a locally bound TypeVar "
            "from a single unconditional TypeVar(...) assignment."
        ),
        help_heading="TW013 — cast-to-typevar (experimental)",
        default_enabled=False,
        experimental=True,
        suppressible=True,
        scoped_only_suppression=True,
        requires_effect_index=False,
        requires_typevar_index=True,
    ),
)

RULE_BY_CODE: Dict[str, RuleDescriptor] = {
    descriptor.code: descriptor for descriptor in RULE_DESCRIPTORS
}

VALID_RULE_CODES: FrozenSet[str] = frozenset(RULE_BY_CODE)
DEFAULT_RULESET: FrozenSet[str] = frozenset(
    descriptor.code for descriptor in RULE_DESCRIPTORS if descriptor.default_enabled
)
SUPPRESSIBLE_RULE_CODES: FrozenSet[str] = frozenset(
    descriptor.code for descriptor in RULE_DESCRIPTORS if descriptor.suppressible
)
SCOPED_ONLY_SUPPRESSION_RULE_CODES: FrozenSet[str] = frozenset(
    descriptor.code for descriptor in RULE_DESCRIPTORS if descriptor.scoped_only_suppression
)
EFFECT_INDEX_RULE_CODES: FrozenSet[str] = frozenset(
    descriptor.code for descriptor in RULE_DESCRIPTORS if descriptor.requires_effect_index
)
TYPEVAR_INDEX_RULE_CODES: FrozenSet[str] = frozenset(
    descriptor.code for descriptor in RULE_DESCRIPTORS if descriptor.requires_typevar_index
)


def active_rules_require_effect_index(active_rules: FrozenSet[str]) -> bool:
    return bool(active_rules & EFFECT_INDEX_RULE_CODES)


def active_rules_require_typevar_index(active_rules: FrozenSet[str]) -> bool:
    return bool(active_rules & TYPEVAR_INDEX_RULE_CODES)


def validate_rule_registration(implemented_codes: FrozenSet[str]) -> None:
    catalog_codes = VALID_RULE_CODES
    if implemented_codes != catalog_codes:
        missing = sorted(catalog_codes - implemented_codes)
        extra = sorted(implemented_codes - catalog_codes)
        details: list[str] = []
        if missing:
            details.append(f"missing implementations: {', '.join(missing)}")
        if extra:
            details.append(f"unknown implementations: {', '.join(extra)}")
        raise RuntimeError("rule registration mismatch: " + "; ".join(details))
