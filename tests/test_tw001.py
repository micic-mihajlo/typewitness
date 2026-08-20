from __future__ import annotations

from tests.conftest import analyze_source, finding_codes


def test_flags_nested_cast() -> None:
    text = "from typing import cast\nx = cast(int, cast(str, '1'))  # SAFETY: chain cast\n"
    result = analyze_source(text)
    assert "TW001" in finding_codes(result)


def test_allows_single_cast() -> None:
    text = "from typing import cast\nx = cast(int, '1')  # SAFETY: ok reason\n"
    result = analyze_source(text)
    assert "TW001" not in finding_codes(result)


def test_resolves_import_typing_attribute() -> None:
    text = "import typing\nx = typing.cast(int, typing.cast(str, '1'))  # SAFETY: ok reason\n"
    result = analyze_source(text)
    assert "TW001" in finding_codes(result)


def test_resolves_import_typing_alias() -> None:
    text = "import typing as t\nx = t.cast(int, t.cast(str, '1'))  # SAFETY: ok reason\n"
    result = analyze_source(text)
    assert "TW001" in finding_codes(result)


def test_resolves_from_import_cast_alias() -> None:
    text = "from typing import cast as c\nx = c(int, c(str, '1'))  # SAFETY: ok reason\n"
    result = analyze_source(text)
    assert "TW001" in finding_codes(result)


def test_resolves_typing_extensions() -> None:
    text = (
        "from typing_extensions import cast\nx = cast(int, cast(str, '1'))  # SAFETY: ok reason\n"
    )
    result = analyze_source(text)
    assert "TW001" in finding_codes(result)


def test_resolves_typing_extensions_module_alias() -> None:
    text = (
        "import typing_extensions as te\nx = te.cast(int, te.cast(str, '1'))  # SAFETY: ok reason\n"
    )
    result = analyze_source(text)
    assert "TW001" in finding_codes(result)


def test_ignores_shadowed_cast_name() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "def f(cast):",
            "    return cast(int, cast(str, '1'))",
        ]
    )
    result = analyze_source(text)
    assert "TW001" not in finding_codes(result)


def test_ignores_unresolved_cast_name() -> None:
    text = "def f():\n    return cast(int, cast(str, '1'))\n"
    result = analyze_source(text)
    assert "TW001" not in finding_codes(result)


def test_flags_only_outer_cast_in_chain() -> None:
    text = (
        "from typing import cast\nx = cast(int, cast(str, cast(bytes, b'1')))  # SAFETY: x reason\n"
    )
    result = analyze_source(text)
    tw001 = [f for f in result.findings if f.code == "TW001"]
    assert len(tw001) == 1


def test_does_not_flag_non_cast_second_arg() -> None:
    text = "from typing import cast\nx = cast(int, '1')  # SAFETY: ok reason\n"
    result = analyze_source(text)
    assert "TW001" not in finding_codes(result)
