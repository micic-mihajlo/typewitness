from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import analyze_source, finding_codes
from typewitness.directives import (
    canonical_type_ignore_norm,
    parse_safety,
)
from typewitness.scopes import build_scope_tree
from typewitness.source_index import build_source_index, normalize_source_text

ROOT = Path(__file__).resolve().parents[1]


def _cast_module(n: int) -> str:
    lines = ["from typing import cast"]
    for index in range(n):
        lines.append(f"x_{index} = cast(int, {index})  # SAFETY: test evidence evidence")
    return "\n".join(lines) + "\n"


def _ignore_module(n: int) -> str:
    lines = []
    for index in range(n):
        lines.append(f"x_{index} = {index}  # type: ignore[assignment]")
    return "\n".join(lines) + "\n"


def test_host_norm_multiline_logical_end() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "x = cast(",
            "    int,",
            "    1)",
        ]
    )
    index = build_source_index(text)
    from typewitness.candidates import _host_norm_for_line

    host = _host_norm_for_line(index, 2)
    assert "NAME:cast" in host
    assert "NAME:int" in host
    assert "NUMBER:1" in host


def test_multiline_host_fingerprint_stable_on_sibling_delete() -> None:
    original = "\n".join(
        [
            "from typing import cast",
            "x = cast(",
            "    int,",
            "    1)",
            "y = 2",
        ]
    )
    modified = "\n".join(
        [
            "from typing import cast",
            "x = cast(",
            "    int,",
            "    1)",
        ]
    )
    fp_original = next(
        f.fingerprint for f in analyze_source(original).findings if f.code == "TW002"
    )
    fp_modified = next(
        f.fingerprint for f in analyze_source(modified).findings if f.code == "TW002"
    )
    assert fp_original == fp_modified


def test_unknown_safety_scope_suppresses_nothing() -> None:
    assert parse_safety("# SAFETY[TW999]: valid reason words") is None
    assert parse_safety("# SAFETY[TW03]: valid reason words") is None
    assert parse_safety("# SAFETY[tw002]: valid reason words") is None
    text = "x = 1  # type: ignore[assignment]\n"
    with_unknown = text.replace(
        "assignment]",
        "assignment]  # SAFETY[TW999]: valid reason words",
    )
    assert "TW003" in finding_codes(analyze_source(text))
    assert "TW003" in finding_codes(analyze_source(with_unknown))


def test_safety_requires_single_hash_prefix() -> None:
    assert parse_safety("## SAFETY: valid reason words") is None
    assert parse_safety("### SAFETY: valid reason words") is None


def test_safety_reason_requires_two_words() -> None:
    assert parse_safety("# SAFETY: one") is None
    directive = parse_safety("# SAFETY: two words")
    assert directive is not None
    assert directive.reason == "two words"


def test_type_ignore_inline_safety_grammar_only() -> None:
    valid = "x = 1  # type: ignore[assignment] SAFETY: inline evidence\n"
    invalid = "x = 1  # type: ignore[assignment] rationale SAFETY: inline evidence\n"
    assert "TW003" not in finding_codes(analyze_source(valid))
    assert "TW003" in finding_codes(analyze_source(invalid))


def test_canonical_ignore_distinguishes_invalid_shapes() -> None:
    assert canonical_type_ignore_norm("# type: ignore") == "type:ignore:uncoded"
    assert canonical_type_ignore_norm("# type: ignore[]") == "type:ignore:invalid-codes"
    assert canonical_type_ignore_norm("# type: ignore[assignment,]") == "type:ignore:invalid-codes"
    assert (
        canonical_type_ignore_norm("# type: ignore[assignment,arg-type]")
        == "type:ignore[arg-type,assignment]"
    )
    assert (
        canonical_type_ignore_norm("# type: ignore[assignment,arg-type,]")
        == "type:ignore:invalid-codes"
    )


def test_indirect_cast_not_chain() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "def helper(v):",
            "    return v",
            "x = cast(int, helper(cast(str, '1')))",
        ]
    )
    result = analyze_source(text)
    assert "TW001" not in finding_codes(result)
    assert finding_codes(result).count("TW002") == 2


def test_sibling_cast_args_not_chain() -> None:
    text = "from typing import cast\nx = cast(int, 1, cast(str, '2'))\n"
    result = analyze_source(text)
    assert "TW001" not in finding_codes(result)


def test_triple_direct_chain_tw001_once() -> None:
    text = "from typing import cast\nx = cast(int, cast(str, cast(bytes, b'1')))\n"
    result = analyze_source(text)
    assert finding_codes(result).count("TW001") == 1
    assert finding_codes(result).count("TW002") == 1


def test_cast_keyword_forms_valid() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "a = cast(T=int, val=1)  # SAFETY: keyword form",
            "b = cast(val=1, typ=int)  # SAFETY: reversed keys",
            "c = cast(int, val=1)  # SAFETY: mixed positional",
        ]
    )
    result = analyze_source(text)
    assert finding_codes(result).count("TW002") == 0


def test_default_param_cast_resolves_module_import() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "def f(cast=[cast(int, x) for x in [1]]):  # SAFETY: default evidence",
            "    return cast(int, 1)",
        ]
    )
    result = analyze_source(text)
    tw002_lines = [
        finding.range.start.line for finding in result.findings if finding.code == "TW002"
    ]
    assert 3 not in tw002_lines


@pytest.mark.skipif(sys.version_info < (3, 12), reason="PEP695 type params require 3.12+")
def test_type_param_nodes_have_scope_assignment() -> None:
    type_var = getattr(ast, "TypeVar", None)
    type_var_tuple = getattr(ast, "TypeVarTuple", None)
    param_spec = getattr(ast, "ParamSpec", None)
    node_types = tuple(cls for cls in (type_var, type_var_tuple, param_spec) if cls is not None)
    text = "class C[T]: pass\n"
    tree = ast.parse(normalize_source_text(text))
    scope_tree = build_scope_tree(tree)
    type_params = [node for node in ast.walk(tree) if isinstance(node, node_types)]
    assert type_params
    for node in type_params:
        assert id(node) in scope_tree.node_scope


def test_deep_nonlocal_write_targets_outer_function() -> None:
    text = "\n".join(
        [
            "def outer():",
            "    w = 1",
            "    class C:",
            "        def inner():",
            "            nonlocal w",
            "            w = 2",
        ]
    )
    tree = ast.parse(normalize_source_text(text))
    scope_tree = build_scope_tree(tree)
    outer_index = next(i for i, scope in enumerate(scope_tree.scopes) if scope.name == "outer")
    forms = [
        site.binding_form
        for site in scope_tree.sites_for_name(outer_index, "w")
        if site.binding_form != "param"
    ]
    assert "nonlocal_write" in forms


@pytest.mark.skipif(sys.version_info < (3, 10), reason="MatchClass kwd_patterns require 3.10+")
def test_matchclass_keyword_pattern_binds() -> None:
    text = "\n".join(
        [
            "def f(x):",
            "    match x:",
            "        case Point(x=val):",
            "            return val",
        ]
    )
    tree = ast.parse(normalize_source_text(text))
    scope_tree = build_scope_tree(tree)
    fn_index = next(i for i, scope in enumerate(scope_tree.scopes) if scope.name == "f")
    forms = [site.binding_form for site in scope_tree.sites_for_name(fn_index, "val")]
    assert "match" in forms


def test_mixed_kind_conditional_import_documented_opaque() -> None:
    text = "\n".join(
        [
            "def f():",
            "    if True:",
            "        from typing import cast",
            "    else:",
            "        def cast():",
            "            pass",
            "    return cast(int, 1)",
        ]
    )
    result = analyze_source(text)
    assert "TW002" not in finding_codes(result)


def test_candidate_density_near_linear() -> None:
    import ast

    from typewitness.candidates import build_candidates
    from typewitness.scopes import build_scope_tree
    from typewitness.source_index import build_source_index, normalize_source_text

    def measure(source: str) -> tuple[int, int]:
        from typewitness._instrumentation import disable, reset, snapshot

        reset()
        normalized = normalize_source_text(source)
        tree = ast.parse(normalized)
        index = build_source_index(normalized)
        scope_tree = build_scope_tree(tree)
        candidates = build_candidates(tree, index, scope_tree)
        visits = snapshot()["token_visits"]
        disable()
        return len(candidates.cast_candidates) + len(candidates.ignore_candidates), visits

    base_candidates, base_visits = measure(_cast_module(250))
    assert base_candidates > 0
    assert base_visits > 0
    prev_candidates, prev_visits = base_candidates, base_visits
    for size in (500, 1000, 2000):
        candidates, visits = measure(_cast_module(size))
        ratio = max(candidates / prev_candidates, visits / prev_visits)
        assert ratio <= 3.25, f"size={size} ratio={ratio:.2f}"
        prev_candidates, prev_visits = candidates, visits


def test_cross_version_runner_does_not_mutate_project_venv() -> None:
    venv_python = ROOT / ".venv" / "bin" / "python"
    if not venv_python.exists():
        pytest.skip("project .venv not present")
    before = venv_python.read_bytes()
    script = ROOT / "tests" / "_fingerprint_digest_runner.py"
    interpreter = subprocess.check_output(
        ["uv", "python", "find", "3.9"],
        cwd=ROOT,
        text=True,
    ).strip()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [interpreter, str(script)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 72:
        pytest.skip("Python 3.9 unavailable")
    assert completed.returncode == 0, completed.stderr
    after = venv_python.read_bytes()
    assert before == after


@pytest.mark.skipif(sys.version_info < (3, 11), reason="match requires 3.11+")
def test_match_case_ignore_reorder_fingerprint_stable() -> None:
    first = "\n".join(
        [
            "def f(x):",
            "    match x:",
            "        case 1:",
            "            y = 1  # type: ignore[assignment]",
            "        case 2:",
            "            z = 2  # type: ignore[arg-type]",
        ]
    )
    second = "\n".join(
        [
            "def f(x):",
            "    match x:",
            "        case 2:",
            "            z = 2  # type: ignore[arg-type]",
            "        case 1:",
            "            y = 1  # type: ignore[assignment]",
        ]
    )

    def tw003_fps(text: str) -> set[str]:
        return {
            finding.fingerprint
            for finding in analyze_source(text).findings
            if finding.code == "TW003"
        }

    assert tw003_fps(first) == tw003_fps(second)


def _adversarial_safety_comment(padding: int) -> str:
    return f"# SAFETY:{' ' * padding}alpha beta"


def test_safety_parsing_scales_near_linear_on_adversarial_comments() -> None:
    import time

    sizes = (2000, 8000, 32000)
    durations: list[float] = []
    for size in sizes:
        comment = _adversarial_safety_comment(size)
        start = time.perf_counter()
        for _ in range(200):
            assert parse_safety(comment) is not None
        durations.append(time.perf_counter() - start)

    ratio_large = durations[2] / durations[1]
    ratio_small = durations[1] / durations[0]
    assert ratio_large / ratio_small < 6.0


def test_cli_reaches_cast_on_line_after_adversarial_safety_comment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tests._integration_support import make_root, write_project
    from typewitness.cli import main

    source = (
        _adversarial_safety_comment(8000) + "\nfrom typing import cast\n\nvalue = cast(int, 1)\n"
    )
    root = write_project(make_root(tmp_path, "project"), {"mod.py": source})
    monkeypatch.chdir(root)

    assert main(["--format", "json", "mod.py"]) == 1
    captured = capsys.readouterr()
    assert "TW002" in captured.out
