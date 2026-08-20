from __future__ import annotations

import pytest

from typewitness.catalog import RULE_BY_CODE, SCOPED_ONLY_SUPPRESSION_RULE_CODES
from typewitness.directives import SafetyDirective, evidence_suppresses_rule


@pytest.mark.parametrize(
    ("rule_code", "directive", "expected"),
    [
        ("TW002", SafetyDirective(reason="reviewed cast", scoped_codes=frozenset()), True),
        ("TW002", SafetyDirective(reason="reviewed cast", scoped_codes=frozenset({"TW002"})), True),
        ("TW005", SafetyDirective(reason="reviewed erasure", scoped_codes=frozenset()), False),
        (
            "TW005",
            SafetyDirective(reason="reviewed erasure", scoped_codes=frozenset({"TW005"})),
            True,
        ),
        ("TW007", SafetyDirective(reason="vendored stubs", scoped_codes=frozenset()), True),
        (
            "TW007",
            SafetyDirective(reason="vendored stubs", scoped_codes=frozenset({"TW007"})),
            True,
        ),
        (
            "TW009",
            SafetyDirective(reason="lazy attribute", scoped_codes=frozenset()),
            True,
        ),
        (
            "TW012",
            SafetyDirective(reason="reviewed mock", scoped_codes=frozenset({"TW012"})),
            True,
        ),
        ("TW001", SafetyDirective(reason="ignored chain", scoped_codes=frozenset()), False),
        (
            "TW004",
            SafetyDirective(reason="reviewed narrowing", scoped_codes=frozenset({"TW004"})),
            True,
        ),
        (
            "TW010",
            SafetyDirective(reason="reviewed guard", scoped_codes=frozenset({"TW010"})),
            True,
        ),
        (
            "TW013",
            SafetyDirective(reason="reviewed generic cast", scoped_codes=frozenset({"TW013"})),
            True,
        ),
    ],
)
def test_evidence_suppresses_rule_follows_catalog_policy(
    rule_code: str,
    directive: SafetyDirective,
    expected: bool,
) -> None:
    descriptor = RULE_BY_CODE[rule_code]
    assert evidence_suppresses_rule(directive, rule_code) is expected
    if descriptor.scoped_only_suppression:
        assert rule_code in SCOPED_ONLY_SUPPRESSION_RULE_CODES
        assert (
            evidence_suppresses_rule(
                SafetyDirective(reason="bare safety", scoped_codes=frozenset()),
                rule_code,
            )
            is False
        )
