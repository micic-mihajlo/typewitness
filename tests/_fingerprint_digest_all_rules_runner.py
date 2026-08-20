from __future__ import annotations

import json
from pathlib import Path

from typewitness import SourceFile, analyze
from typewitness.catalog import VALID_RULE_CODES
from typewitness.models import Config

ALL_RULES = VALID_RULE_CODES

text = """# mypy: ignore-errors
from typing import Any, TypeGuard, TypeVar, cast, no_type_check
import json
from unittest.mock import patch

untyped = 1  # type: ignore[assignment]
erased = cast(Any, payload)
cast(int, orphan)
chained = cast(int, cast(str, raw))


def widen_then_cast():
    w: Any = [1, 2]
    return cast(list, w)


@no_type_check
def unchecked():
    return 1


patch("pkg.mod.target", create=True)


def is_str(x: object) -> TypeGuard[str]:
    return True


parsed = cast(dict[str, int], json.loads(raw))
projected = cast(str, json.loads(raw)["key"])
patch("pkg.mod.other")

T = TypeVar("T")


def generic(x):
    return cast(T, x)
"""
result = analyze(
    SourceFile(path=Path("all_rules.py"), text=text),
    config=Config(select=ALL_RULES, ignore=frozenset()),
)
payload = sorted((finding.code, finding.fingerprint) for finding in result.findings)
print(json.dumps(payload))
