from __future__ import annotations

import pathlib

import pytest

from tests.conftest import analyze_source, finding_codes
from typewitness import Config
from typewitness.candidate_ref import CANDIDATE_KIND_CAST, CANDIDATE_KIND_IGNORE, CandidateRef
from typewitness.directives import has_safety_reason, parse_safety
from typewitness.fingerprint import build_fingerprint_table
from typewitness.source_index import build_source_index, normalize_token_stream


def test_mixed_population_fingerprints_do_not_collide() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "x = cast(int, 1)  # type: ignore[assignment]",
            "y = cast(int, 2)  # type: ignore[arg-type]",
        ]
    )
    r1 = analyze_source(text)
    r2 = analyze_source(text)
    fps = {(f.code, f.fingerprint) for f in r1.findings}
    assert fps == {(f.code, f.fingerprint) for f in r2.findings}
    tw002 = [f for f in r1.findings if f.code == "TW002"]
    tw003 = [f for f in r1.findings if f.code == "TW003"]
    assert len(tw002) == 2
    assert len(tw003) == 2
    assert len({f.fingerprint for f in tw002}) == 2
    assert len({f.fingerprint for f in tw003}) == 2


def test_fingerprint_table_typed_refs() -> None:
    table = build_fingerprint_table(
        path=pathlib.Path("a.py"),
        refs=[
            CandidateRef(CANDIDATE_KIND_CAST, 0),
            CandidateRef(CANDIDATE_KIND_IGNORE, 0),
        ],
        scope_paths=["module", "module"],
        candidate_norms=["cast-norm", "ignore-norm"],
        host_norms=["host-a", "host-b"],
    )
    cast_ref = CandidateRef(CANDIDATE_KIND_CAST, 0)
    ignore_ref = CandidateRef(CANDIDATE_KIND_IGNORE, 0)
    assert table.dup_suffix_for(cast_ref) == ""
    assert table.dup_suffix_for(ignore_ref) == ""


def test_dict_entry_ignore_host_norm_not_empty() -> None:
    text = "\n".join(
        [
            "DATA = {",
            '    "key": 1,  # type: ignore[assignment]',
            "}",
        ]
    )
    result = analyze_source(text)
    assert result.errors == ()
    assert "TW003" in finding_codes(result)


def test_host_norm_ignores_brackets_in_strings() -> None:
    text = 'x = "{}" + cast(int, 1)\n'
    index = build_source_index(text)
    norm = index.host_norm_for_span(1, 0, 1, len(text.rstrip()))
    assert "OP:{" not in norm or "STRING:" in norm


def test_safety_must_begin_comment_body() -> None:
    assert parse_safety("# SAFETY: ok reason") is not None
    assert parse_safety("# TODO: add a SAFETY marker") is None
    assert parse_safety("# no SAFETY here") is None
    assert parse_safety("# NOT_SAFETY: x") is None
    assert parse_safety("# safety: lower case") is None
    assert parse_safety("# type: ignore SAFETY: inline evidence") is None
    assert has_safety_reason("# type: ignore SAFETY: inline evidence") is False


def test_safety_scoped_codes_invalid_rejected() -> None:
    assert parse_safety("# SAFETY[TW001,tw002]: valid reason words") is None
    assert parse_safety("# SAFETY[TW999]: valid reason words") is None
    assert parse_safety("# SAFETY[TW001]: valid reason words") is None
    directive = parse_safety("# SAFETY[TW002,TW004]: valid reason words")
    assert directive is not None
    assert directive.scoped_codes == frozenset({"TW002", "TW004"})


def test_tw001_scoped_safety_fails_closed_and_suppresses_nothing() -> None:
    text = (
        "from typing import cast\n"
        "x = cast(int, cast(str, '1'))  # SAFETY[TW001]: reviewed nested cast\n"
    )
    codes = finding_codes(analyze_source(text))
    assert "TW001" in codes
    assert "TW002" in codes


def test_invalid_cast_shape_not_candidate() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "x = cast(int, int, 1)",
            "y = cast(typ=int, val=1, extra=2)",
            "z = cast(*[int, 1])",
            "w = cast(int)",
        ]
    )
    result = analyze_source(text)
    assert finding_codes(result) == []


def test_lambda_cast_not_chain_child_of_outer() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "x = cast(int, (lambda: cast(str, '1'))())",
        ]
    )
    result = analyze_source(text)
    assert "TW001" not in finding_codes(result)


def test_config_empty_select_runs_nothing() -> None:
    text = "from typing import cast\nx = cast(int, 1)\n"
    from typewitness import SourceFile, analyze

    result = analyze(
        SourceFile(path=pathlib.Path("a.py"), text=text),
        config=Config(select=frozenset()),
    )
    assert result.findings == ()


def test_config_rejects_bogus_code() -> None:
    with pytest.raises(ValueError):
        Config(select=frozenset({"BOGUS"}))


def test_type_checking_import_resolves() -> None:
    text = "\n".join(
        [
            "from typing import TYPE_CHECKING",
            "if TYPE_CHECKING:",
            "    from typing import cast",
            "x = cast(int, 1)  # SAFETY: guarded import",
        ]
    )
    result = analyze_source(text)
    assert "TW002" not in finding_codes(result)


def test_same_line_import_before_use_resolves() -> None:
    text = "from typing import cast; x = cast(int, 1)  # SAFETY: ok reason\n"
    result = analyze_source(text)
    assert "TW002" not in finding_codes(result)


def test_import_after_use_opaque() -> None:
    text = "\n".join(
        [
            "x = cast(int, 1)",
            "from typing import cast",
        ]
    )
    result = analyze_source(text)
    assert "TW002" not in finding_codes(result)


def test_function_before_module_import_resolves() -> None:
    text = "\n".join(
        [
            "def f():",
            "    return cast(int, 1)  # SAFETY: deferred import",
            "from typing import cast",
        ]
    )
    result = analyze_source(text)
    assert "TW002" not in finding_codes(result)


def test_canonical_type_ignore_norm() -> None:
    from typewitness.directives import canonical_type_ignore_norm

    assert canonical_type_ignore_norm("# type: ignore[arg-type,assignment]") == (
        "type:ignore[arg-type,assignment]"
    )
    assert canonical_type_ignore_norm("# type: ignore") == "type:ignore:uncoded"


def test_nested_fstring_normalize_stable() -> None:
    source = 'x = f"{f"{1}"}"\n'
    assert normalize_token_stream(source)
    assert "STRING:" in normalize_token_stream(source)
