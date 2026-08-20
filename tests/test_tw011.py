from __future__ import annotations

import sys

import pytest

from tests.conftest import ALL_RULES, analyze_source, finding_codes
from typewitness.models import AnalysisResult


def analyze_tw011(text: str, path: str = "sample.py") -> AnalysisResult:
    return analyze_source(text, path=path, select=ALL_RULES)


def test_flags_cast_of_json_loads() -> None:
    text = "import json\nfrom typing import cast\nx = cast(dict[str, int], json.loads(raw))\n"
    result = analyze_tw011(text)
    assert "TW011" in finding_codes(result)


def test_flags_cast_of_json_load() -> None:
    text = "\n".join(
        [
            "import json",
            "from typing import cast",
            "with open(path) as handle:",
            "    x = cast(dict[str, int], json.load(handle))",
        ]
    )
    result = analyze_tw011(text)
    assert "TW011" in finding_codes(result)


def test_flags_subscript_projection() -> None:
    text = "\n".join(
        [
            "import json",
            "from typing import cast",
            "x = cast(str, json.loads(raw)['key'])",
        ]
    )
    result = analyze_tw011(text)
    assert "TW011" in finding_codes(result)


def test_flags_nested_subscript_projection() -> None:
    text = "\n".join(
        [
            "import json",
            "from typing import cast",
            "x = cast(str, json.loads(raw)['a']['b'])",
        ]
    )
    result = analyze_tw011(text)
    assert "TW011" in finding_codes(result)


def test_ignores_method_call_on_boundary_result() -> None:
    text = "\n".join(
        [
            "import json",
            "from typing import cast",
            "x = cast(list[str], json.loads(raw).keys())",
        ]
    )
    result = analyze_tw011(text)
    assert "TW011" not in finding_codes(result)


def test_ignores_intervening_call() -> None:
    text = "\n".join(
        [
            "import json",
            "from typing import cast",
            "def validate(value):",
            "    return value",
            "x = cast(dict[str, int], validate(json.loads(raw)))",
        ]
    )
    result = analyze_tw011(text)
    assert "TW011" not in finding_codes(result)


def test_ignores_cast_to_any() -> None:
    text = "\n".join(
        [
            "import json",
            "from typing import Any, cast",
            "x = cast(Any, json.loads(raw))",
        ]
    )
    result = analyze_tw011(text)
    assert "TW011" not in finding_codes(result)


def test_ignores_cast_to_object() -> None:
    text = "\n".join(
        [
            "import json",
            "from typing import cast",
            "x = cast(object, json.loads(raw))",
        ]
    )
    result = analyze_tw011(text)
    assert "TW011" not in finding_codes(result)


def test_resolves_from_import() -> None:
    text = "from json import loads\nfrom typing import cast\nx = cast(dict[str, int], loads(raw))\n"
    result = analyze_tw011(text)
    assert "TW011" in finding_codes(result)


def test_resolves_module_qualified_call() -> None:
    text = "import ast\nfrom typing import cast\nx = cast(int, ast.literal_eval(raw))\n"
    result = analyze_tw011(text)
    assert "TW011" in finding_codes(result)


def test_ignores_shadowed_loads() -> None:
    text = "\n".join(
        [
            "from json import loads",
            "from typing import cast",
            "def f(loads):",
            "    return cast(dict[str, int], loads(raw))",
        ]
    )
    result = analyze_tw011(text)
    assert "TW011" not in finding_codes(result)


def test_ignores_ambiguous_loads_import() -> None:
    text = "\n".join(
        [
            "from json import loads",
            "from yaml import loads",
            "from typing import cast",
            "x = cast(dict[str, int], loads(raw))",
        ]
    )
    result = analyze_tw011(text)
    assert "TW011" not in finding_codes(result)


def test_allows_explicit_scoped_suppression() -> None:
    text = "\n".join(
        [
            "import json",
            "from typing import cast",
            "x = cast(dict[str, int], json.loads(raw))  # SAFETY[TW011]: schema validated upstream",
        ]
    )
    result = analyze_tw011(text)
    assert "TW011" not in finding_codes(result)


def test_bare_safety_does_not_suppress() -> None:
    text = "\n".join(
        [
            "import json",
            "from typing import cast",
            "x = cast(dict[str, int], json.loads(raw))  # SAFETY: schema validated upstream",
        ]
    )
    result = analyze_tw011(text)
    assert "TW011" in finding_codes(result)


def test_not_enabled_by_default() -> None:
    text = "import json\nfrom typing import cast\nx = cast(dict[str, int], json.loads(raw))\n"
    result = analyze_source(text)
    assert "TW011" not in finding_codes(result)


def test_flags_pickle_loads() -> None:
    text = "import pickle\nfrom typing import cast\nx = cast(dict[str, int], pickle.loads(raw))\n"
    result = analyze_tw011(text)
    assert "TW011" in finding_codes(result)


def test_flags_marshal_loads() -> None:
    text = "import marshal\nfrom typing import cast\nx = cast(dict[str, int], marshal.loads(raw))\n"
    result = analyze_tw011(text)
    assert "TW011" in finding_codes(result)


def test_flags_plistlib_loads() -> None:
    text = "\n".join(
        [
            "import plistlib",
            "from typing import cast",
            "x = cast(dict[str, int], plistlib.loads(raw))",
        ]
    )
    result = analyze_tw011(text)
    assert "TW011" in finding_codes(result)


@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib requires Python 3.11+")
def test_flags_tomllib_loads() -> None:
    text = "\n".join(
        [
            "import tomllib",
            "from typing import cast",
            "x = cast(dict[str, int], tomllib.loads(raw))",
        ]
    )
    result = analyze_tw011(text)
    assert "TW011" in finding_codes(result)


def test_finding_range_on_cast_call() -> None:
    text = "import json\nfrom typing import cast\nx = cast(dict[str, int], json.loads(raw))\n"
    result = analyze_tw011(text)
    finding = next(f for f in result.findings if f.code == "TW011")
    assert finding.range.start.line == 3
    assert finding.range.start.column == 4
    assert finding.fingerprint
