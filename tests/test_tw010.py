from __future__ import annotations

from tests.conftest import analyze_source, finding_codes


def test_flags_constant_true_type_guard() -> None:
    text = "\n".join(
        [
            "from typing import TypeGuard",
            "def is_str(x: object) -> TypeGuard[str]:",
            "    return True",
        ]
    )
    result = analyze_source(text)
    assert "TW010" in finding_codes(result)


def test_flags_constant_false_type_is() -> None:
    text = "\n".join(
        [
            "from typing import TypeIs",
            "def is_int(x: object) -> TypeIs[int]:",
            "    return False",
        ]
    )
    result = analyze_source(text)
    assert "TW010" in finding_codes(result)


def test_flags_async_constant_type_guard() -> None:
    text = "\n".join(
        [
            "from typing import TypeGuard",
            "async def is_str(x: object) -> TypeGuard[str]:",
            "    return True",
        ]
    )
    result = analyze_source(text)
    assert "TW010" in finding_codes(result)


def test_flags_docstring_then_single_literal_return() -> None:
    text = "\n".join(
        [
            "from typing import TypeGuard",
            "def is_str(x: object) -> TypeGuard[str]:",
            '    """doc"""',
            "    return True",
        ]
    )
    result = analyze_source(text)
    assert "TW010" in finding_codes(result)


def test_flags_with_future_annotations_import() -> None:
    text = "\n".join(
        [
            "from __future__ import annotations",
            "from typing import TypeGuard",
            "def is_str(x: object) -> TypeGuard[str]:",
            "    return True",
        ]
    )
    result = analyze_source(text)
    assert "TW010" in finding_codes(result)


def test_ignores_branching_returns() -> None:
    text = "\n".join(
        [
            "from typing import TypeGuard",
            "def is_str(x: object) -> TypeGuard[str]:",
            "    if x:",
            "        return True",
            "    return True",
        ]
    )
    result = analyze_source(text)
    assert "TW010" not in finding_codes(result)


def test_ignores_non_constant_return() -> None:
    text = "\n".join(
        [
            "from typing import TypeGuard",
            "def is_str(x: object) -> TypeGuard[str]:",
            "    return isinstance(x, str)",
        ]
    )
    result = analyze_source(text)
    assert "TW010" not in finding_codes(result)


def test_ignores_mixed_boolean_returns() -> None:
    text = "\n".join(
        [
            "from typing import TypeGuard",
            "def is_str(x: object) -> TypeGuard[str]:",
            "    if x:",
            "        return True",
            "    return False",
        ]
    )
    result = analyze_source(text)
    assert "TW010" not in finding_codes(result)


def test_ignores_assert_before_return() -> None:
    text = "\n".join(
        [
            "from typing import TypeGuard",
            "def is_str(x: object) -> TypeGuard[str]:",
            "    assert x is not None",
            "    return True",
        ]
    )
    result = analyze_source(text)
    assert "TW010" not in finding_codes(result)


def test_ignores_try_except_return() -> None:
    text = "\n".join(
        [
            "from typing import TypeGuard",
            "def is_str(x: object) -> TypeGuard[str]:",
            "    try:",
            "        return True",
            "    except Exception:",
            "        return True",
        ]
    )
    result = analyze_source(text)
    assert "TW010" not in finding_codes(result)


def test_ignores_bare_return() -> None:
    text = "\n".join(
        [
            "from typing import TypeGuard",
            "def is_str(x: object) -> TypeGuard[str]:",
            "    return",
        ]
    )
    result = analyze_source(text)
    assert "TW010" not in finding_codes(result)


def test_ignores_no_return() -> None:
    text = "\n".join(
        [
            "from typing import TypeGuard",
            "def is_str(x: object) -> TypeGuard[str]:",
            "    pass",
        ]
    )
    result = analyze_source(text)
    assert "TW010" not in finding_codes(result)


def test_ignores_non_narrowing_return() -> None:
    text = "\n".join(
        [
            "def is_str(x: object) -> bool:",
            "    return True",
        ]
    )
    result = analyze_source(text)
    assert "TW010" not in finding_codes(result)


def test_ignores_nested_function_body() -> None:
    text = "\n".join(
        [
            "from typing import TypeGuard",
            "def outer(x: object) -> TypeGuard[str]:",
            "    def inner():",
            "        return True",
            "    return True",
        ]
    )
    result = analyze_source(text)
    assert "TW010" not in finding_codes(result)


def test_ignores_overload_stub_but_flags_implementation() -> None:
    text = "\n".join(
        [
            "from typing import TypeGuard, overload",
            "@overload",
            "def is_str(x: str) -> TypeGuard[str]: ...",
            "def is_str(x: object) -> TypeGuard[str]:",
            "    return True",
        ]
    )
    result = analyze_source(text)
    assert "TW010" in finding_codes(result)
    tw010_lines = [f.range.start.line for f in result.findings if f.code == "TW010"]
    assert 4 in tw010_lines
    assert 3 not in tw010_lines


def test_ignores_overload_decorator() -> None:
    text = "\n".join(
        [
            "from typing import TypeGuard, overload",
            "@overload",
            "def is_str(x: object) -> TypeGuard[str]:",
            "    return True",
        ]
    )
    result = analyze_source(text)
    assert "TW010" not in finding_codes(result)


def test_ignores_protocol_method() -> None:
    text = "\n".join(
        [
            "from typing import Protocol, TypeGuard",
            "class P(Protocol):",
            "    def check(self, x: object) -> TypeGuard[str]:",
            "        return True",
        ]
    )
    result = analyze_source(text)
    assert "TW010" not in finding_codes(result)


def test_ignores_stub_body() -> None:
    text = "\n".join(
        [
            "from typing import TypeGuard",
            "def is_str(x: object) -> TypeGuard[str]: ...",
        ]
    )
    result = analyze_source(text)
    assert "TW010" not in finding_codes(result)


def test_ignores_generator() -> None:
    text = "\n".join(
        [
            "from typing import TypeGuard",
            "def is_str(x: object) -> TypeGuard[str]:",
            "    yield True",
        ]
    )
    result = analyze_source(text)
    assert "TW010" not in finding_codes(result)


def test_ignores_explicit_string_annotation() -> None:
    text = "\n".join(
        [
            "from typing import TypeGuard",
            'def is_str(x: object) -> "TypeGuard[str]":',
            "    return True",
        ]
    )
    result = analyze_source(text)
    assert "TW010" not in finding_codes(result)


def test_ignores_shadowed_type_guard() -> None:
    text = "\n".join(
        [
            "from typing import TypeGuard",
            "def f(TypeGuard):",
            "    def is_str(x: object) -> TypeGuard[str]:",
            "        return True",
        ]
    )
    result = analyze_source(text)
    assert "TW010" not in finding_codes(result)


def test_allows_explicit_scoped_suppression() -> None:
    text = "\n".join(
        [
            "from typing import TypeGuard",
            "def is_str(x: object) -> TypeGuard[str]:  # SAFETY[TW010]: reviewed guard",
            "    return True",
        ]
    )
    result = analyze_source(text)
    assert "TW010" not in finding_codes(result)


def test_bare_safety_does_not_suppress() -> None:
    text = "\n".join(
        [
            "from typing import TypeGuard",
            "def is_str(x: object) -> TypeGuard[str]:  # SAFETY: reviewed guard",
            "    return True",
        ]
    )
    result = analyze_source(text)
    assert "TW010" in finding_codes(result)


def test_fingerprint_stable_when_header_inserted() -> None:
    original = "\n".join(
        [
            "from typing import TypeGuard",
            "def is_str(x: object) -> TypeGuard[str]:",
            "    return True",
        ]
    )
    modified = "# header\n" + original
    first = next(f for f in analyze_source(original).findings if f.code == "TW010")
    second = next(f for f in analyze_source(modified).findings if f.code == "TW010")
    assert first.fingerprint == second.fingerprint


def test_extra_statement_silences_finding() -> None:
    base = "\n".join(
        [
            "from typing import TypeGuard",
            "def is_str(x: object) -> TypeGuard[str]:",
            "    return True",
        ]
    )
    modified = "\n".join(
        [
            "from typing import TypeGuard",
            "def is_str(x: object) -> TypeGuard[str]:",
            "    _ = 1",
            "    return True",
        ]
    )
    assert "TW010" in finding_codes(analyze_source(base))
    assert "TW010" not in finding_codes(analyze_source(modified))
