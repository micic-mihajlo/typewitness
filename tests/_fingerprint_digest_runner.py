from __future__ import annotations

import json
from pathlib import Path

from typewitness import SourceFile, analyze
from typewitness.models import Config

text = """from typing import cast
msg = f"hi {1}"
cast(int, msg)
x = 1  # type: ignore[assignment]
y = cast(int, cast(str, "1"))
"""
result = analyze(
    SourceFile(path=Path("mod.py"), text=text),
    config=Config(select=frozenset({"TW001", "TW002", "TW003"}), ignore=frozenset()),
)
payload = sorted((finding.code, finding.fingerprint) for finding in result.findings)
print(json.dumps(payload))
