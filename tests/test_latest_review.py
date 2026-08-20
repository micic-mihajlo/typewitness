from __future__ import annotations

import ast
import pathlib
import statistics
import sys
import textwrap
import time

import pytest

from tests.conftest import ALL_RULES, analyze_source, analyze_tw004, finding_codes
from typewitness import SourceFile, analyze
from typewitness.candidates import build_candidates
from typewitness.scopes import BindingForm, ScopeKind, build_scope_tree
from typewitness.source_index import build_source_index, normalize_source_text


def _scope_tree(text: str):  # type: ignore[no-untyped-def]
    tree = ast.parse(normalize_source_text(text))
    return tree, build_scope_tree(tree)


def _function_scope_index(scope_tree, name: str = "f") -> int:  # type: ignore[no-untyped-def]
    return next(
        index
        for index, scope in enumerate(scope_tree.scopes)
        if scope.kind == ScopeKind.FUNCTION and scope.name == name
    )


def test_delete_subscript_descendant_uses_local_shadow_scope() -> None:
    text = """
from typing import cast
def f(items):
    cast = lambda *args: 0
    del items[cast(int, 1)]
"""
    assert "TW002" not in finding_codes(analyze_source(text))


def test_delete_attribute_descendant_uses_local_import_scope() -> None:
    text = """
def f():
    from typing import cast
    del cast(int, object()).value
"""
    assert "TW002" in finding_codes(analyze_source(text))


@pytest.mark.parametrize(
    "statement",
    [
        "items[(cast := lambda *args: 0)] = 1",
        "items[(cast := lambda *args: 0)] += 1",
        "for items[(cast := lambda *args: 0)] in values:\n        pass",
        "holder((cast := lambda *args: 0)).value = 1",
    ],
)
def test_store_target_descendants_collect_walrus_binding(statement: str) -> None:
    text = "from typing import cast\ndef f(items, values, holder):\n"
    text += textwrap.indent(statement, "    ")
    text += "\n    return cast(int, 1)\n"
    tree, scope_tree = _scope_tree(text)
    function_index = _function_scope_index(scope_tree)
    forms = [site.binding_form for site in scope_tree.sites_for_name(function_index, "cast")]
    assert BindingForm.WALRUS.value in forms
    assert "TW002" not in finding_codes(analyze_source(text))
    for node in ast.walk(tree):
        if isinstance(node, (ast.expr, ast.comprehension)):
            assert id(node) in scope_tree.node_scope, ast.dump(node)


def test_lambda_walrus_remains_lambda_local_tw004_positive_control() -> None:
    text = """
from typing import Any, cast
def f():
    widened: Any = [1]
    mutate = lambda: (widened := [2])
    return cast(list[int], widened)  # SAFETY: narrow literal
"""
    assert "TW004" in finding_codes(analyze_tw004(text))


def test_scoped_tw004_safety_suppresses_tw004() -> None:
    text = """
from typing import Any, cast
def f():
    widened: Any = [1]
    return cast(list[int], widened)  # SAFETY[TW004]: reviewed narrowing
"""
    assert "TW004" not in finding_codes(analyze_tw004(text))


def test_multiline_ignore_host_uses_complete_logical_statement() -> None:
    source = """
first = call(
    1,
)  # type: ignore[assignment]
second = call(
    2,
)  # type: ignore[assignment]
"""
    normalized = normalize_source_text(source)
    tree = ast.parse(normalized)
    index = build_source_index(normalized)
    candidates = build_candidates(tree, index, build_scope_tree(tree))
    hosts = [candidate.host_norm for candidate in candidates.ignore_candidates]
    assert len(hosts) == 2
    assert "NUMBER:1" in hosts[0]
    assert "NUMBER:2" in hosts[1]
    assert hosts[0] != hosts[1]


def test_multiline_ignore_host_is_independent_of_comment_position() -> None:
    variants = [
        "value = call(1)  # type: ignore[assignment]\n",
        "value = call(  # type: ignore[assignment]\n    1)\n",
        "value = call(\n    1\n)  # type: ignore[assignment]\n",
    ]
    host_norms: list[str] = []
    for source in variants:
        tree = ast.parse(source)
        index = build_source_index(source)
        candidates = build_candidates(tree, index, build_scope_tree(tree))
        host_norms.append(candidates.ignore_candidates[0].host_norm)
    assert len(set(host_norms)) == 1


def test_trailing_multiline_ignore_fingerprint_survives_earlier_ignore_insert() -> None:
    original = """
first = call(
    1,
)  # type: ignore[assignment]
second = call(
    2,
)  # type: ignore[assignment]
"""
    modified = "unrelated = 0  # type: ignore[misc] SAFETY: unrelated evidence\n" + original

    def fingerprints_by_host(text: str) -> dict[str, str]:
        normalized = normalize_source_text(text)
        tree = ast.parse(normalized)
        index = build_source_index(normalized)
        scope_tree = build_scope_tree(tree)
        candidates = build_candidates(tree, index, scope_tree)
        result = analyze_source(text)
        findings_by_line = {
            finding.range.start.line: finding.fingerprint
            for finding in result.findings
            if finding.code == "TW003"
        }
        return {
            candidate.host_norm: findings_by_line[candidate.comment_line]
            for candidate in candidates.ignore_candidates
            if candidate.comment_line in findings_by_line
        }

    original_fingerprints = fingerprints_by_host(original)
    modified_fingerprints = fingerprints_by_host(modified)
    for host, fingerprint in original_fingerprints.items():
        assert modified_fingerprints[host] == fingerprint


@pytest.mark.skipif(sys.version_info < (3, 12), reason="PEP 695 requires Python 3.12+")
def test_type_alias_descendants_use_assignment_scope() -> None:
    text = """
def f():
    from typing import cast
    type Alias[T: cast(int, object())] = list[cast(str, object())]
"""
    result = analyze_source(text, select=ALL_RULES)
    assert finding_codes(result).count("TW002") == 2
    tree, scope_tree = _scope_tree(text)
    function_index = _function_scope_index(scope_tree)
    alias = next(node for node in ast.walk(tree) if type(node).__name__ == "TypeAlias")
    for node in ast.walk(alias):
        if isinstance(node, (ast.expr, ast.comprehension)):
            assert scope_tree.scope_for_node(node) == function_index


def test_curated_syntax_corpus_has_no_semantic_scope_fallback() -> None:
    corpus = """
from typing import cast

@decorator(cast(int, 0))
def f(arg: cast(type, object()) = cast(int, 1)) -> cast(type, object()):
    target[(shadow := lambda: cast(int, 2))] = cast(int, 3)
    target[cast(int, 4)] += cast(int, 5)
    del target[cast(int, 6)], cast(object, target).value
    for target[cast(int, 7)] in [cast(int, item) for item in values if (seen := item)]:
        yield cast(int, 8)
    yield from (cast(int, item) for item in values)
    try:
        raise Error(cast(int, 9))
    except Error as error:
        assert cast(bool, error), cast(str, error)
"""
    if sys.version_info >= (3, 10):
        corpus += """
    match arg:
        case Point(value=bound) if cast(bool, bound):
            return cast(int, bound)
        case {'key': value, **rest}:
            return cast(int, value)
"""
    if sys.version_info >= (3, 11):
        corpus += """
    try:
        raise Group(cast(int, 10))
    except* Error as grouped:
        observed = cast(int, grouped)
"""
    if sys.version_info >= (3, 12):
        corpus += "    type Alias[T: cast(int, object())] = list[cast(str, object())]\n"
    tree, scope_tree = _scope_tree(corpus)
    for node in ast.walk(tree):
        if isinstance(node, (ast.expr, ast.comprehension)):
            assert id(node) in scope_tree.node_scope, ast.dump(node)


def test_analyze_does_not_mutate_ast_with_parent_links(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed: list[ast.Module] = []
    real_parse = ast.parse

    def capture_parse(*args, **kwargs):  # type: ignore[no-untyped-def]
        tree = real_parse(*args, **kwargs)
        parsed.append(tree)
        return tree

    monkeypatch.setattr(ast, "parse", capture_parse)
    analyze(SourceFile(path=pathlib.Path("sample.py"), text="x = 1\n"))
    assert parsed
    assert all(not hasattr(node, "_tw_parent") for node in ast.walk(parsed[0]))


def test_deferred_deep_nonlocal_write_targets_later_outer_binding() -> None:
    text = """
def outer():
    class Namespace:
        def inner():
            nonlocal widened
            widened = [2]
    widened = [1]
"""
    _, scope_tree = _scope_tree(text)
    outer_index = _function_scope_index(scope_tree, "outer")
    forms = [site.binding_form for site in scope_tree.sites_for_name(outer_index, "widened")]
    assert BindingForm.NONLOCAL_WRITE.value in forms


def _dense_index_source(size: int) -> str:
    lines = ["from typing import cast"]
    for index in range(size):
        lines.extend(
            [
                f"def f_{index}():",
                (f"    return cast(int, cast(str, {index}))  # type: ignore[return-value]"),
            ]
        )
    return "\n".join(lines) + "\n"


def _measure_dense_indexes(size: int) -> tuple[dict[str, int], float]:
    from typewitness._instrumentation import disable, reset, snapshot

    source = _dense_index_source(size)
    samples: list[float] = []
    counts: dict[str, int] = {}
    for _ in range(3):
        reset()
        started = time.perf_counter()
        tree = ast.parse(source)
        source_index = build_source_index(source)
        scope_tree = build_scope_tree(tree)
        candidates = build_candidates(tree, source_index, scope_tree)
        assert len(candidates.cast_candidates) == size * 2
        assert len(candidates.ignore_candidates) == size
        samples.append(time.perf_counter() - started)
        counts = snapshot()
    disable()
    return counts, statistics.median(samples)


def test_dense_indexes_scale_near_linearly() -> None:
    measurements = [_measure_dense_indexes(size) for size in (250, 500, 1000, 2000)]
    operation_names = (
        "chain_ref_lookups",
        "name_site_lookups",
        "name_site_steps",
        "line_scope_lookups",
        "token_visits",
    )
    for counts, _ in measurements:
        for operation in operation_names:
            assert counts[operation] > 0
    for (previous_counts, previous_time), (counts, elapsed) in zip(
        measurements,
        measurements[1:],
    ):
        for operation in operation_names:
            ratio = counts[operation] / previous_counts[operation]
            assert ratio <= 2.35, (operation, ratio, previous_counts, counts)
        assert elapsed / previous_time <= 3.25, (previous_time, elapsed)


def _dense_repeated_import_source(size: int) -> str:
    lines: list[str] = []
    for index in range(size):
        lines.append("from typing import cast")
        lines.append(f"value_{index} = cast(int, {index})")
    return "\n".join(lines) + "\n"


def _measure_repeated_name_resolution(size: int) -> tuple[dict[str, int], float]:
    from typewitness._instrumentation import disable, reset, snapshot

    source = _dense_repeated_import_source(size)
    samples: list[float] = []
    counts: dict[str, int] = {}
    for _ in range(3):
        reset()
        started = time.perf_counter()
        tree = ast.parse(source)
        source_index = build_source_index(source)
        scope_tree = build_scope_tree(tree)
        candidates = build_candidates(tree, source_index, scope_tree)
        assert len(candidates.cast_candidates) == size
        samples.append(time.perf_counter() - started)
        counts = snapshot()
    disable()
    return counts, statistics.median(samples)


def test_repeated_name_resolution_operation_count_is_near_linear() -> None:
    measurements = [_measure_repeated_name_resolution(size) for size in (250, 500, 1000, 2000)]
    assert all(counts["name_site_steps"] > 0 for counts, _ in measurements)
    for (previous, previous_time), (current, elapsed) in zip(measurements, measurements[1:]):
        ratio = current["name_site_steps"] / previous["name_site_steps"]
        assert ratio <= 2.35, (ratio, previous, current)
        assert elapsed / previous_time <= 3.25, (previous_time, elapsed)


def _same_host_cast_source(size: int) -> str:
    lines = ["from typing import cast", "value = hold("]
    for index in range(size):
        lines.append(f"    cast(int, {index}),")
    lines.append(")")
    return "\n".join(lines) + "\n"


def _same_host_ignore_source(size: int) -> str:
    lines = ["holder("]
    for index in range(size):
        lines.append(f"    {index},  # type: ignore[arg-type]")
    lines.append(")")
    return "\n".join(lines) + "\n"


def _measure_same_host_casts(size: int) -> tuple[dict[str, int], float]:
    from typewitness._instrumentation import disable, reset, snapshot

    source = _same_host_cast_source(size)
    tree = ast.parse(source)
    source_index = build_source_index(source)
    scope_tree = build_scope_tree(tree)
    build_candidates(tree, source_index, scope_tree)
    samples: list[float] = []
    counts: dict[str, int] = {}
    for _ in range(5):
        reset()
        started = time.perf_counter()
        tree = ast.parse(source)
        source_index = build_source_index(source)
        scope_tree = build_scope_tree(tree)
        candidates = build_candidates(tree, source_index, scope_tree)
        assert len(candidates.cast_candidates) == size
        assert len({candidate.host_norm for candidate in candidates.cast_candidates}) == 1
        samples.append(time.perf_counter() - started)
        counts = snapshot()
    disable()
    return counts, statistics.median(samples)


def _measure_same_host_ignores(size: int) -> tuple[dict[str, int], float]:
    from typewitness._instrumentation import disable, reset, snapshot

    source = _same_host_ignore_source(size)
    tree = ast.parse(source)
    source_index = build_source_index(source)
    scope_tree = build_scope_tree(tree)
    build_candidates(tree, source_index, scope_tree)
    samples: list[float] = []
    counts: dict[str, int] = {}
    for _ in range(5):
        reset()
        started = time.perf_counter()
        tree = ast.parse(source)
        source_index = build_source_index(source)
        scope_tree = build_scope_tree(tree)
        candidates = build_candidates(tree, source_index, scope_tree)
        assert len(candidates.ignore_candidates) == size
        assert len({candidate.host_norm for candidate in candidates.ignore_candidates}) == 1
        samples.append(time.perf_counter() - started)
        counts = snapshot()
    disable()
    return counts, statistics.median(samples)


def test_same_host_cast_normalization_scales_near_linearly() -> None:
    measurements = [_measure_same_host_casts(size) for size in (125, 250, 500, 1000, 2000)]
    assert all(counts["span_token_visits"] > 0 for counts, _ in measurements)
    for (previous_counts, _), (counts, _) in zip(
        measurements,
        measurements[1:],
    ):
        ratio = counts["span_token_visits"] / previous_counts["span_token_visits"]
        assert ratio <= 2.5, ("span_token_visits", ratio, previous_counts, counts)
    assert measurements[-1][1] / measurements[0][1] <= 48


def test_same_host_ignore_normalization_scales_near_linearly() -> None:
    measurements = [_measure_same_host_ignores(size) for size in (125, 250, 500, 1000, 2000)]
    assert all(counts["span_token_visits"] > 0 for counts, _ in measurements)
    for (previous_counts, _), (counts, _) in zip(
        measurements,
        measurements[1:],
    ):
        ratio = counts["span_token_visits"] / previous_counts["span_token_visits"]
        assert ratio <= 2.5, ("span_token_visits", ratio, previous_counts, counts)
    assert measurements[-1][1] / measurements[0][1] <= 48


def test_tw010_respects_class_body_type_guard_shadowing() -> None:
    text = "\n".join(
        [
            "from typing import TypeGuard",
            "class C:",
            "    TypeGuard = int",
            "    def is_str(self, x: object) -> TypeGuard[str]:",
            "        return True",
        ]
    )
    result = analyze_source(text)
    assert "TW010" not in finding_codes(result)


def _dense_typeguard_module(size: int) -> str:
    lines = ["from typing import TypeGuard"]
    for index in range(size):
        lines.extend(
            [
                f"def guard_{index}(x: object) -> TypeGuard[str]:",
                "    return True",
            ]
        )
    return "\n".join(lines) + "\n"


def _measure_dense_typeguard_analysis(size: int) -> tuple[dict[str, int], float]:
    from typewitness._instrumentation import disable, reset, snapshot

    source = _dense_typeguard_module(size)
    samples: list[float] = []
    counts: dict[str, int] = {}
    for _ in range(3):
        reset()
        started = time.perf_counter()
        result = analyze_source(source)
        assert finding_codes(result).count("TW010") == size
        samples.append(time.perf_counter() - started)
        counts = snapshot()
    disable()
    return counts, statistics.median(samples)


def test_dense_typeguard_overloads_scale_near_linearly() -> None:
    measurements = [_measure_dense_typeguard_analysis(size) for size in (250, 500, 1000, 2000)]
    for (previous_counts, previous_time), (counts, elapsed) in zip(
        measurements,
        measurements[1:],
    ):
        for operation in ("name_site_lookups", "name_site_steps"):
            ratio = counts[operation] / previous_counts[operation]
            assert ratio <= 2.35, (operation, ratio, previous_counts, counts)
        assert elapsed / previous_time <= 3.25, (previous_time, elapsed)


def _dense_safety_comment_cast_module(comment_lines: int, cast_count: int) -> str:
    lines = ["from typing import cast"]
    for index in range(comment_lines):
        lines.append(f"# note {index}")
    for index in range(cast_count):
        lines.append(f"x_{index} = cast(int, {index})")
    return "\n".join(lines) + "\n"


def test_safety_for_statement_lookup_is_memoized_for_shared_hosts() -> None:
    source = "\n".join(
        [
            "# SAFETY: reviewed cast evidence here",
            "from typing import cast",
            "x = cast(int, 1)",
        ]
    )
    index = build_source_index(source)
    first = index.safety_for_statement(3, 3)
    second = index.safety_for_statement(3, 3)
    assert first is second
    assert (3, 3) in index._safety_for_statement_cache


def _dense_typevar_module(size: int) -> str:
    lines = ["from typing import TypeVar, cast"]
    for index in range(size):
        lines.append(f"T_{index} = TypeVar('T_{index}')")
        lines.append(f"x_{index} = cast(T_{index}, payload)")
    return "\n".join(lines) + "\n"


def _measure_typevar_index_build(size: int) -> tuple[dict[str, int], float]:
    from typewitness._instrumentation import disable, reset, snapshot
    from typewitness.typevars import build_typevar_index

    source = _dense_typevar_module(size)
    normalized = normalize_source_text(source)
    tree = ast.parse(normalized)
    scope_tree = build_scope_tree(tree)
    samples: list[float] = []
    counts: dict[str, int] = {}
    for _ in range(3):
        reset()
        started = time.perf_counter()
        build_typevar_index(scope_tree)
        samples.append(time.perf_counter() - started)
        counts = snapshot()
    disable()
    return counts, statistics.median(samples)


def test_typevar_index_build_scales_near_linearly() -> None:
    measurements = [_measure_typevar_index_build(size) for size in (250, 500, 1000, 2000)]
    for (previous_counts, _), (counts, _) in zip(
        measurements,
        measurements[1:],
    ):
        ratio = counts["name_site_lookups"] / previous_counts["name_site_lookups"]
        assert ratio <= 2.35, (ratio, previous_counts, counts)


def test_long_comment_run_with_many_casts_scales_near_linearly() -> None:
    def measure(comment_lines: int, cast_count: int) -> tuple[int, float]:
        source = _dense_safety_comment_cast_module(comment_lines, cast_count)
        started = time.perf_counter()
        result = analyze_source(source, select=ALL_RULES)
        elapsed = time.perf_counter() - started
        assert finding_codes(result).count("TW002") == cast_count
        return cast_count, elapsed

    small = measure(comment_lines=2000, cast_count=200)
    large = measure(comment_lines=4000, cast_count=400)
    assert large[0] / small[0] <= 2.5
    assert large[1] / small[1] <= 3.25


def test_source_index_caches_are_private_and_do_not_change_equality() -> None:
    left = build_source_index('value = "é"\n')
    right = build_source_index('value = "é"\n')
    assert left == right

    left.char_offset(1, 10)
    left.host_norm_for_span(1, 0, 1, 11)

    assert left == right
    assert left._byte_to_char_cache is not right._byte_to_char_cache
    assert left._byte_column_maps is not right._byte_column_maps
    assert left._norm_cache is not right._norm_cache


@pytest.mark.skipif(sys.version_info < (3, 12), reason="requires compound f-string tokens")
def test_fstring_dense_indexing_scales_near_linearly() -> None:
    def measure(size: int) -> float:
        source = "\n".join(f'value_{index} = f"item {index}"' for index in range(size)) + "\n"
        build_source_index(source)
        samples: list[float] = []
        for _ in range(5):
            started = time.perf_counter()
            build_source_index(source)
            samples.append(time.perf_counter() - started)
        return statistics.median(samples)

    elapsed_small = measure(250)
    elapsed_large = measure(2000)
    assert elapsed_large / elapsed_small <= 24
