from __future__ import annotations

import json
from pathlib import Path

from typewitness import SourceFile, analyze
from typewitness.catalog import DEFAULT_RULESET, VALID_RULE_CODES
from typewitness.models import Config

ALL_RULES = VALID_RULE_CODES

text = """from typing import cast
msg = f"hi {1}"
cast(int, msg)
x = 1  # type: ignore[assignment]
y = cast(int, cast(str, "1"))
"""
result = analyze(
    SourceFile(path=Path("mod.py"), text=text),
    config=Config(
        select=DEFAULT_RULESET,
        ignore=frozenset(),
    ),
)
payload = sorted((finding.code, finding.fingerprint) for finding in result.findings)
print(json.dumps(payload))
