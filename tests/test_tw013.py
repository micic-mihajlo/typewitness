from __future__ import annotations

import pytest

from tests.conftest import ALL_RULES, analyze_source, finding_codes
from typewitness.models import AnalysisResult


def analyze_tw013(text: str, path: str = "sample.py") -> AnalysisResult:
    return analyze_source(text, path=path, select=ALL_RULES | frozenset({"TW013"}))


def test_flags_cast_to_local_typevar() -> None:
    text = "\n".join(
        [
            "from typing import TypeVar, cast",
            "T = TypeVar('T')",
            "def f(x):",
            "    return cast(T, x)",
        ]
    )
    result = analyze_tw013(text)
    assert "TW013" in finding_codes(result)


def test_flags_cast_in_function_scope_typevar() -> None:
    text = "\n".join(
        [
            "from typing import TypeVar, cast",
            "def f():",
            "    T = TypeVar('T')",
            "    return cast(T, 1)",
        ]
    )
    result = analyze_tw013(text)
    assert "TW013" in finding_codes(result)


def test_ignores_cast_to_concrete_type() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "x = cast(int, payload)",
        ]
    )
    result = analyze_tw013(text)
    assert "TW013" not in finding_codes(result)


def test_ignores_subscripted_typevar_target() -> None:
    text = "\n".join(
        [
            "from typing import TypeVar, cast",
            "T = TypeVar('T')",
            "x = cast(list[T], payload)",
        ]
    )
    result = analyze_tw013(text)
    assert "TW013" not in finding_codes(result)


def test_ignores_imported_typevar_name() -> None:
    text = "\n".join(
        [
            "from typing import TypeVar as T, cast",
            "x = cast(T, payload)",
        ]
    )
    result = analyze_tw013(text)
    assert "TW013" not in finding_codes(result)


def test_ignores_reassigned_typevar() -> None:
    text = "\n".join(
        [
            "from typing import TypeVar, cast",
            "T = TypeVar('T')",
            "T = int",
            "x = cast(T, payload)",
        ]
    )
    result = analyze_tw013(text)
    assert "TW013" not in finding_codes(result)


def test_ignores_conditional_typevar_binding() -> None:
    text = "\n".join(
        [
            "from typing import TypeVar, cast",
            "if True:",
            "    T = TypeVar('T')",
            "x = cast(T, payload)",
        ]
    )
    result = analyze_tw013(text)
    assert "TW013" not in finding_codes(result)


def test_ignores_multiple_typevar_bindings() -> None:
    text = "\n".join(
        [
            "from typing import TypeVar, cast",
            "def f(flag):",
            "    if flag:",
            "        T = TypeVar('T1')",
            "    else:",
            "        T = TypeVar('T2')",
            "    return cast(T, 1)",
        ]
    )
    result = analyze_tw013(text)
    assert "TW013" not in finding_codes(result)


def test_ignores_string_cast_target() -> None:
    text = "\n".join(
        [
            "from typing import TypeVar, cast",
            "T = TypeVar('T')",
            "x = cast('T', payload)",
        ]
    )
    result = analyze_tw013(text)
    assert "TW013" not in finding_codes(result)


def test_ignores_newtype_alias() -> None:
    text = "\n".join(
        [
            "from typing import NewType, cast",
            "UserId = NewType('UserId', int)",
            "x = cast(UserId, payload)",
        ]
    )
    result = analyze_tw013(text)
    assert "TW013" not in finding_codes(result)


def test_allows_explicit_scoped_suppression() -> None:
    text = "\n".join(
        [
            "from typing import TypeVar, cast",
            "T = TypeVar('T')",
            "x = cast(T, payload)  # SAFETY[TW013]: reviewed generic cast",
        ]
    )
    result = analyze_tw013(text)
    assert "TW013" not in finding_codes(result)


def test_bare_safety_does_not_suppress() -> None:
    text = "\n".join(
        [
            "from typing import TypeVar, cast",
            "T = TypeVar('T')",
            "x = cast(T, payload)  # SAFETY: reviewed generic cast",
        ]
    )
    result = analyze_tw013(text)
    assert "TW013" in finding_codes(result)


def test_not_enabled_by_default() -> None:
    text = "\n".join(
        [
            "from typing import TypeVar, cast",
            "T = TypeVar('T')",
            "x = cast(T, payload)",
        ]
    )
    result = analyze_source(text)
    assert "TW013" not in finding_codes(result)


@pytest.mark.parametrize(
    "body",
    [
        "def f(T):\n    return cast(T, x)",
        "def f():\n    for T in []:\n        pass\n    return cast(T, x)",
        "def f():\n    with open('/dev/null') as T:\n        pass\n    return cast(T, x)",
        (
            "def f():\n"
            "    try:\n"
            "        pass\n"
            "    except Exception as T:\n"
            "        pass\n"
            "    return cast(T, x)"
        ),
        "def f():\n    assert (T := 1)\n    return cast(T, x)",
        "def T():\n    return cast(T, x)",
    ],
)
def test_ignores_local_typevar_shadows(body: str) -> None:
    text = "\n".join(
        [
            "from typing import TypeVar, cast",
            "T = TypeVar('T')",
            body,
        ]
    )
    result = analyze_tw013(text)
    assert "TW013" not in finding_codes(result)
