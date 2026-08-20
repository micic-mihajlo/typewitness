from __future__ import annotations

import pytest

from tests.conftest import ALL_RULES, DEFAULT_RULESET, analyze_source, analyze_tw004, finding_codes
from typewitness.models import AnalysisResult

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


# --- TW007 checker disable ---


def test_tw007_ignores_pyright_strengthening_directive() -> None:
    text = "# pyright: strict\nimport x\n"
    result = analyze_source(text)
    assert "TW007" not in finding_codes(result)


def test_tw007_mypy_disable_error_code_underscore_form() -> None:
    text = "# mypy: disable_error_code=assignment\nimport x\n"
    result = analyze_source(text)
    assert "TW007" in finding_codes(result)


def test_tw007_fingerprint_stable_on_unrelated_insert() -> None:
    original = "# mypy: ignore-errors\nimport x\n"
    modified = "# header\n" + original
    first = next(f for f in analyze_source(original).findings if f.code == "TW007")
    second = next(f for f in analyze_source(modified).findings if f.code == "TW007")
    assert first.fingerprint == second.fingerprint


# --- TW008 no_type_check ---


def test_tw008_import_star_resolves_no_type_check() -> None:
    text = "\n".join(
        [
            "from typing import *",
            "@no_type_check",
            "def f():",
            "    return 1",
        ]
    )
    result = analyze_source(text)
    assert "TW008" in finding_codes(result)


def test_tw008_rebound_name_stays_silent() -> None:
    text = "\n".join(
        [
            "from typing import no_type_check",
            "no_type_check = lambda fn: fn",
            "@no_type_check",
            "def f():",
            "    return 1",
        ]
    )
    result = analyze_source(text)
    assert "TW008" not in finding_codes(result)


def test_tw009_shadowed_patch_stays_silent() -> None:
    text = "\n".join(
        [
            "def patch(*args, **kwargs):",
            "    return None",
            "patch('pkg.mod.target', create=True)",
        ]
    )
    result = analyze_source(text)
    assert "TW009" not in finding_codes(result)


def test_tw012_shadowed_patch_object_stays_silent() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch",
            "patch = lambda *args, **kwargs: None",
            "patch.object(object(), 'attr')",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" not in finding_codes(result)


def test_tw009_fingerprint_stable_when_unrelated_line_inserted() -> None:
    base = "\n".join(
        [
            "from unittest.mock import patch",
            "patch('pkg.mod.target', create=True)",
        ]
    )
    modified = "# header\n" + base
    first = next(f for f in analyze_source(base).findings if f.code == "TW009")
    second = next(f for f in analyze_source(modified).findings if f.code == "TW009")
    assert first.fingerprint == second.fingerprint


def test_tw012_positional_new_corpus_style_patch() -> None:
    text = "\n".join(
        [
            "from unittest.mock import patch, MagicMock",
            "",
            "def test_service():",
            "    mock_client = MagicMock()",
            "    with patch('myapp.client.get_client', mock_client):",
            "        pass",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" not in finding_codes(result)


def test_tw012_unittest_mock_import_corpus_style() -> None:
    text = "\n".join(
        [
            "import unittest.mock",
            "",
            "def test_hook():",
            "    with unittest.mock.patch('os.path.exists') as exists:",
            "        exists.return_value = True",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW012"}))
    assert "TW012" in finding_codes(result)


# --- TW010 constant narrowing ---


def test_tw010_ignores_shadowed_type_guard_import() -> None:
    text = "\n".join(
        [
            "from typing import TypeGuard",
            "TypeGuard = int",
            "def is_str(x: object) -> TypeGuard[str]:",
            "    return True",
        ]
    )
    result = analyze_source(text)
    assert "TW010" not in finding_codes(result)


def test_tw010_fingerprint_stable_when_header_inserted() -> None:
    base = "\n".join(
        [
            "from typing import TypeGuard",
            "def is_str(x: object) -> TypeGuard[str]:",
            "    return True",
        ]
    )
    modified = "# header\n" + base
    first = next(f for f in analyze_source(base).findings if f.code == "TW010")
    second = next(f for f in analyze_source(modified).findings if f.code == "TW010")
    assert first.fingerprint == second.fingerprint


# --- TW013 cast-to-typevar ---


def test_tw013_ignores_imported_typevar_alias() -> None:
    text = "\n".join(
        [
            "from typing import TypeVar as T, cast",
            "x = cast(T, payload)",
        ]
    )
    result = analyze_source(text, select=ALL_RULES | frozenset({"TW013"}))
    assert "TW013" not in finding_codes(result)


def analyze_tw013(text: str, path: str = "sample.py") -> AnalysisResult:
    return analyze_source(text, path=path, select=ALL_RULES | frozenset({"TW013"}))


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
def test_tw013_ignores_local_shadows(body: str) -> None:
    text = "\n".join(
        [
            "from typing import TypeVar, cast",
            "T = TypeVar('T')",
            body,
        ]
    )
    result = analyze_tw013(text)
    assert "TW013" not in finding_codes(result)


# --- TW006 discarded-cast ---


def analyze_tw006(text: str, path: str = "sample.py") -> AnalysisResult:
    return analyze_source(text, path=path, select=DEFAULT_RULESET)


def test_tw006_flags_discarded_cast_in_corpus_style_module() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "",
            "def load(payload):",
            "    cast(int, payload)",
        ]
    )
    result = analyze_tw006(text)
    assert "TW006" in finding_codes(result)


def test_tw006_ignores_shadowed_cast_name() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "def cast():",
            "    pass",
            "cast(int, payload)",
        ]
    )
    result = analyze_tw006(text)
    assert "TW006" not in finding_codes(result)


def test_tw006_still_flags_when_relative_cast_resolves() -> None:
    text = "\n".join(
        [
            "from .typing import cast",
            "cast(int, payload)",
        ]
    )
    result = analyze_tw006(text)
    assert "TW006" in finding_codes(result)


def test_tw006_ignores_conditional_cast_import() -> None:
    text = "\n".join(
        [
            "try:",
            "    from typing import cast",
            "except ImportError:",
            "    def cast(*args):",
            "        return args[-1]",
            "cast(int, payload)",
        ]
    )
    result = analyze_tw006(text)
    assert "TW006" not in finding_codes(result)


def test_tw006_allows_scoped_suppression() -> None:
    text = "from typing import cast\ncast(int, payload)  # SAFETY[TW006]: intentional no-op\n"
    result = analyze_tw006(text)
    assert "TW006" not in finding_codes(result)


def test_tw006_skips_nested_chain_child() -> None:
    text = "from typing import cast\ncast(int, cast(str, payload))\n"
    result = analyze_tw006(text)
    assert finding_codes(result).count("TW006") == 1


def test_tw006_fingerprint_stable_when_header_inserted() -> None:
    base = "from typing import cast\ncast(int, payload)\n"
    modified = "# header\n" + base
    first = next(f for f in analyze_tw006(base).findings if f.code == "TW006")
    second = next(f for f in analyze_tw006(modified).findings if f.code == "TW006")
    assert first.fingerprint == second.fingerprint


# --- TW011 unvalidated-boundary-cast ---


def analyze_tw011(text: str, path: str = "sample.py") -> AnalysisResult:
    return analyze_source(text, path=path, select=ALL_RULES)


def test_tw011_flags_projection_chain_on_json_loads() -> None:
    text = "\n".join(
        [
            "import json",
            "from typing import cast",
            "cast(str, json.loads(raw)['a']['b'])",
        ]
    )
    result = analyze_tw011(text)
    assert "TW011" in finding_codes(result)


def test_tw011_ignores_intervening_validator_call() -> None:
    text = "\n".join(
        [
            "import json",
            "from typing import cast",
            "def validate(value):",
            "    return value",
            "cast(dict[str, int], validate(json.loads(raw)))",
        ]
    )
    result = analyze_tw011(text)
    assert "TW011" not in finding_codes(result)


def test_tw011_ignores_shadowed_loads_in_function() -> None:
    text = "\n".join(
        [
            "from json import loads",
            "from typing import cast",
            "def f(loads):",
            "    cast(dict[str, int], loads(raw))",
        ]
    )
    result = analyze_tw011(text)
    assert "TW011" not in finding_codes(result)


def test_tw011_ignores_relative_json_import() -> None:
    text = "\n".join(
        [
            "from .json import loads",
            "from typing import cast",
            "cast(dict[str, int], loads(raw))",
        ]
    )
    result = analyze_tw011(text)
    assert "TW011" not in finding_codes(result)


def test_tw011_ignores_ambiguous_loads_import() -> None:
    text = "\n".join(
        [
            "from json import loads",
            "from yaml import loads",
            "from typing import cast",
            "cast(dict[str, int], loads(raw))",
        ]
    )
    result = analyze_tw011(text)
    assert "TW011" not in finding_codes(result)


def test_tw011_allows_scoped_suppression() -> None:
    text = "\n".join(
        [
            "import json",
            "from typing import cast",
            "cast(dict[str, int], json.loads(raw))  # SAFETY[TW011]: schema validated upstream",
        ]
    )
    result = analyze_tw011(text)
    assert "TW011" not in finding_codes(result)


def test_tw011_fingerprint_stable_when_header_inserted() -> None:
    base = "import json\nfrom typing import cast\ncast(dict[str, int], json.loads(raw))\n"
    modified = "# header\n" + base
    first = next(f for f in analyze_tw011(base).findings if f.code == "TW011")
    second = next(f for f in analyze_tw011(modified).findings if f.code == "TW011")
    assert first.fingerprint == second.fingerprint
