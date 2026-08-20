from __future__ import annotations

from tests.conftest import analyze_source, analyze_tw004, finding_codes

# --- TW001/TW002 scope resolution ---


def test_async_function_cast_resolution() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "async def f():",
            "    return cast(int, cast(str, '1'))  # SAFETY: chain cast",
        ]
    )
    result = analyze_source(text)
    assert "TW001" in finding_codes(result)


def test_conflicting_import_shadows_cast() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "import other as cast",
            "x = cast(int, cast(str, '1'))  # SAFETY: chain cast",
        ]
    )
    result = analyze_source(text)
    assert "TW001" not in finding_codes(result)


def test_def_name_shadows_cast() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "def cast():",
            "    pass",
            "x = cast(int, cast(str, '1'))  # SAFETY: chain cast",
        ]
    )
    result = analyze_source(text)
    assert "TW001" not in finding_codes(result)


def test_class_name_shadows_typing_module() -> None:
    text = "\n".join(
        [
            "import typing",
            "class typing:",
            "    pass",
            "x = typing.cast(int, typing.cast(str, '1'))  # SAFETY: chain cast",
        ]
    )
    result = analyze_source(text)
    assert "TW001" not in finding_codes(result)


def test_recursive_unpack_shadows_any() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f():",
            "    a, (Any, b) = 1, ([1], 2)",
            "    w: Any = [1]",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_tw004(text)
    assert "TW004" not in finding_codes(result)


def test_for_target_shadows_cast() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "def f():",
            "    for cast in []:",
            "        pass",
            "    return cast(int, '1')",
        ]
    )
    result = analyze_source(text)
    assert "TW002" not in finding_codes(result)


def test_with_target_shadows_cast() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "def f():",
            "    with open('/dev/null') as cast:",
            "        pass",
            "    return cast(int, '1')",
        ]
    )
    result = analyze_source(text)
    assert "TW002" not in finding_codes(result)


def test_except_name_shadows_cast() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "def f():",
            "    try:",
            "        pass",
            "    except Exception as cast:",
            "        pass",
            "    return cast(int, '1')",
        ]
    )
    result = analyze_source(text)
    assert "TW002" not in finding_codes(result)


def test_walrus_shadows_cast() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "def f():",
            "    if (cast := 1):",
            "        pass",
            "    return cast(int, '1')",
        ]
    )
    result = analyze_source(text)
    assert "TW002" not in finding_codes(result)


def test_comprehension_target_does_not_resolve_cast() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "def f():",
            "    return [cast(int, x) for cast in 'abc']",
        ]
    )
    result = analyze_source(text)
    assert "TW002" not in finding_codes(result)


# --- TW002 chained cast suppression ---


def test_double_nested_cast_one_tw002() -> None:
    text = "from typing import cast\nx = cast(int, cast(str, '1'))\n"
    result = analyze_source(text)
    tw002 = [f for f in result.findings if f.code == "TW002"]
    assert len(tw002) == 1


def test_triple_nested_cast_one_tw002() -> None:
    text = "from typing import cast\nx = cast(int, cast(str, cast(bytes, b'1')))\n"
    result = analyze_source(text)
    tw002 = [f for f in result.findings if f.code == "TW002"]
    assert len(tw002) == 1


def test_triple_nested_cast_still_tw001() -> None:
    text = "from typing import cast\nx = cast(int, cast(str, cast(bytes, b'1')))\n"
    result = analyze_source(text)
    assert "TW001" in finding_codes(result)


# --- TW003 directive parsing ---


def test_prototype_ignore_not_type_ignore() -> None:
    text = "x = 1  # prototype: ignore SAFETY: fake\n"
    result = analyze_source(text)
    assert "TW003" not in finding_codes(result)


def test_rejects_empty_type_ignore_code() -> None:
    text = "x = 1  # type: ignore[] SAFETY: reason\n"
    result = analyze_source(text)
    assert "TW003" in finding_codes(result)


def test_rejects_malformed_type_ignore_punctuation() -> None:
    text = "x = 1  # type: ignore[assignment,] SAFETY: reason\n"
    result = analyze_source(text)
    assert "TW003" in finding_codes(result)


def test_accepts_comma_separated_codes_with_spaces() -> None:
    text = "\n".join(
        [
            "# SAFETY: legacy code",
            "x = 1  # type: ignore[assignment, arg-type]",
        ]
    )
    result = analyze_source(text)
    assert "TW003" not in finding_codes(result)


# --- TW004 flow analysis ---


def test_branch_widen_does_not_leak() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f(flag):",
            "    if flag:",
            "        w: Any = [1, 2]",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_tw004(text)
    assert "TW004" not in finding_codes(result)


def test_else_only_widen_does_not_leak() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f(flag):",
            "    w = [1]",
            "    if flag:",
            "        pass",
            "    else:",
            "        w: Any = [1, 2]",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_tw004(text)
    assert "TW004" not in finding_codes(result)


def test_loop_assignment_invalidates_widen() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f():",
            "    w: Any = [1, 2]",
            "    for _ in range(1):",
            "        w = [3]",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_tw004(text)
    assert "TW004" not in finding_codes(result)


def test_try_assignment_invalidates_widen() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f():",
            "    w: Any = [1, 2]",
            "    try:",
            "        w = [3]",
            "    except Exception:",
            "        pass",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_tw004(text)
    assert "TW004" not in finding_codes(result)


def test_reassignment_before_cast_invalidates() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f():",
            "    w: Any = [1, 2]",
            "    w = [3]",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_tw004(text)
    assert "TW004" not in finding_codes(result)


def test_module_qualified_any_widen() -> None:
    text = "\n".join(
        [
            "import typing",
            "from typing import cast",
            "def f():",
            "    w: typing.Any = [1, 2]",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_tw004(text)
    assert "TW004" in finding_codes(result)


def test_typing_extensions_module_qualified_any() -> None:
    text = "\n".join(
        [
            "import typing_extensions as te",
            "from typing import cast",
            "def f():",
            "    w: te.Any = [1, 2]",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_tw004(text)
    assert "TW004" in finding_codes(result)


def test_shadowed_object_not_widen() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "def f():",
            "    object = int",
            "    w: object = {'a': 1}",
            "    return cast(dict[str, int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_tw004(text)
    assert "TW004" not in finding_codes(result)


def test_unary_literal_positive() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f():",
            "    w: Any = +1",
            "    return cast(int, w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_tw004(text)
    assert "TW004" in finding_codes(result)


def test_unary_literal_negative() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f():",
            "    w: Any = -1",
            "    return cast(int, w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_tw004(text)
    assert "TW004" in finding_codes(result)


# --- fingerprint stability ---


def test_ast_fingerprint_stable_on_unrelated_insert() -> None:
    original = "\n".join(
        [
            "from typing import cast",
            "def f():",
            "    return cast(int, 1)",
        ]
    )
    modified = "\n".join(
        [
            "from typing import cast",
            "def f():",
            "    pass",
            "    return cast(int, 1)",
        ]
    )
    fp_original = analyze_source(original).findings[0].fingerprint
    fp_modified = analyze_source(modified).findings[0].fingerprint
    assert fp_original == fp_modified


def test_ast_fingerprint_differs_for_duplicate_violation() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "def f():",
            "    cast(int, 1)",
            "    cast(int, 2)",
        ]
    )
    fps = [f.fingerprint for f in analyze_source(text).findings if f.code == "TW002"]
    assert len(fps) == 2
    assert fps[0] != fps[1]


def test_tw003_fingerprint_stable_on_unrelated_ignore_insert() -> None:
    original = "\n".join(
        [
            "x = 1  # type: ignore[assignment]",
            "y = 2  # type: ignore[arg-type]",
        ]
    )
    modified = "\n".join(
        [
            "z = 0  # type: ignore[misc] SAFETY: unrelated",
            "x = 1  # type: ignore[assignment]",
            "y = 2  # type: ignore[arg-type]",
        ]
    )
    result_original = analyze_source(original)
    result_modified = analyze_source(modified)
    fp_original = next(f.fingerprint for f in result_original.findings if f.range.start.line == 2)
    fp_modified = next(f.fingerprint for f in result_modified.findings if f.range.start.line == 3)
    assert fp_original == fp_modified


def test_tw003_fingerprint_differs_for_identical_comments() -> None:
    text = "\n".join(
        [
            "x = 1  # type: ignore[assignment]",
            "y = 2  # type: ignore[assignment]",
        ]
    )
    result = analyze_source(text)
    tw003 = [f for f in result.findings if f.code == "TW003"]
    assert len(tw003) == 2
    assert tw003[0].fingerprint != tw003[1].fingerprint
