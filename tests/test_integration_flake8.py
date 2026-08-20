"""Flake8 plugin adapter contract.

Flake8 has already read and parsed the file by the time a plugin runs. The adapter must
reuse what it was handed: one analysis per file, no second read, no second parse, and
0-based columns because that is what Flake8's reporting layer expects.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any, List, Tuple

import pytest

from tests._integration_support import (
    CAST_NO_EVIDENCE,
    CAST_WITH_EVIDENCE,
    CHAINED_CAST,
    CLEAN_SOURCE,
    UNPARSEABLE_SOURCE,
    analyze_text,
    make_root,
    write_project,
)
from typewitness.flake8_plugin import TypeWitnessPlugin
from typewitness.report import TOOL_NAME, TOOL_VERSION

Violation = Tuple[int, int, str, type]


def _lines(text: str) -> List[str]:
    return text.splitlines(keepends=True)


def _run(text: str, filename: str = "pkg/mod.py") -> List[Violation]:
    plugin = TypeWitnessPlugin(ast.parse(text), filename, _lines(text))
    return list(plugin.run())


def test_plugin_identity() -> None:
    assert TypeWitnessPlugin.name == TOOL_NAME
    assert TypeWitnessPlugin.version == TOOL_VERSION


def test_plugin_init_signature_matches_the_flake8_protocol() -> None:
    """Flake8 injects arguments by parameter name, so the names are the contract."""
    parameters = tuple(inspect.signature(TypeWitnessPlugin.__init__).parameters)

    assert parameters == ("self", "tree", "filename", "lines")


def test_violations_carry_the_code_message_and_plugin_class() -> None:
    expected = analyze_text("pkg/mod.py", CAST_NO_EVIDENCE).findings
    assert expected

    violations = _run(CAST_NO_EVIDENCE)

    assert len(violations) == len(expected)
    for violation, finding in zip(violations, expected):
        line, column, text, plugin_class = violation
        assert line == finding.range.start.line
        assert column == finding.range.start.column
        assert text == f"{finding.code} {finding.message}"
        assert plugin_class is TypeWitnessPlugin


def test_columns_are_zero_based_for_flake8() -> None:
    finding = analyze_text("pkg/mod.py", CAST_NO_EVIDENCE).findings[0]

    line, column, _, _ = _run(CAST_NO_EVIDENCE)[0]

    assert line == finding.range.start.line
    assert column == finding.range.start.column
    assert column == 8


def test_violations_are_sorted_by_position_then_code() -> None:
    violations = _run(CHAINED_CAST)

    keys = [(line, column, text.split(" ", 1)[0]) for line, column, text, _ in violations]

    assert len(keys) >= 2
    assert keys == sorted(keys)


def test_clean_file_yields_nothing() -> None:
    assert _run(CLEAN_SOURCE) == []


def test_suppressed_finding_yields_nothing() -> None:
    assert _run(CAST_WITH_EVIDENCE) == []


def test_default_ruleset_is_used_so_tw004_stays_opt_in() -> None:
    text = (
        "from typing import Any, cast\n"
        "\n"
        "\n"
        "def load():\n"
        "    widened: Any = [1, 2]\n"
        "    return cast(list, widened)  # SAFETY: reviewed narrowing\n"
    )

    codes = {text_value.split(" ", 1)[0] for _, _, text_value, _ in _run(text)}

    assert "TW004" not in codes


def test_analysis_runs_exactly_once_per_file(monkeypatch: pytest.MonkeyPatch) -> None:
    import typewitness.flake8_plugin as plugin_module

    calls: List[Path] = []
    original = plugin_module.analyze

    def counting_analyze(source: Any, config: Any = None) -> Any:
        calls.append(source.path)
        return original(source, config)

    monkeypatch.setattr(plugin_module, "analyze", counting_analyze)

    plugin = TypeWitnessPlugin(ast.parse(CHAINED_CAST), "pkg/mod.py", _lines(CHAINED_CAST))
    violations = list(plugin.run())

    assert violations
    assert len(calls) == 1


def test_run_is_not_re_entrant_across_instances(monkeypatch: pytest.MonkeyPatch) -> None:
    import typewitness.flake8_plugin as plugin_module

    calls: List[Path] = []
    original = plugin_module.analyze

    def counting_analyze(source: Any, config: Any = None) -> Any:
        calls.append(source.path)
        return original(source, config)

    monkeypatch.setattr(plugin_module, "analyze", counting_analyze)

    for _ in range(3):
        list(TypeWitnessPlugin(ast.parse(CAST_NO_EVIDENCE), "a.py", _lines(CAST_NO_EVIDENCE)).run())

    assert len(calls) == 3


def test_plugin_does_not_read_the_file_from_disk() -> None:
    """``lines`` is authoritative; the path need not exist."""
    violations = _run(CAST_NO_EVIDENCE, filename="does/not/exist.py")

    assert violations


def test_plugin_uses_the_supplied_lines_not_the_file_contents(tmp_path: Path) -> None:
    target = tmp_path / "mod.py"
    target.write_text(CLEAN_SOURCE, encoding="utf-8")

    violations = _run(CAST_NO_EVIDENCE, filename=str(target))

    assert violations


def test_lines_are_joined_without_added_or_lost_newlines() -> None:
    """A wrong join shifts every reported line number by the number of joins."""
    text = "from typing import cast\n\n\n\nvalue = cast(int, 1)\n"
    finding = analyze_text("pkg/mod.py", text).findings[0]

    line, _, _, _ = _run(text)[0]

    assert line == finding.range.start.line == 5


def test_lines_without_a_trailing_newline_are_handled() -> None:
    text = "from typing import cast\n\nvalue = cast(int, 1)"

    violations = _run(text)

    assert violations


def test_unparseable_source_yields_nothing_and_does_not_raise() -> None:
    """Flake8 reports syntax errors itself (E999); the plugin must stay silent."""
    plugin = TypeWitnessPlugin(None, "pkg/bad.py", _lines(UNPARSEABLE_SOURCE))

    assert list(plugin.run()) == []


def test_undecodable_text_yields_nothing_and_does_not_raise() -> None:
    text = "VALUE = 1\x00\n"

    plugin = TypeWitnessPlugin(None, "pkg/bad.py", _lines(text))

    assert list(plugin.run()) == []


def test_stdin_filename_does_not_raise() -> None:
    violations = _run(CAST_NO_EVIDENCE, filename="-")

    assert isinstance(violations, list)


def test_empty_lines_input_yields_nothing() -> None:
    plugin = TypeWitnessPlugin(ast.parse(""), "pkg/mod.py", [])

    assert list(plugin.run()) == []


def test_every_violation_is_a_four_tuple() -> None:
    for violation in _run(CHAINED_CAST):
        assert isinstance(violation, tuple)
        assert len(violation) == 4


def test_message_text_is_prefixed_with_the_rule_code() -> None:
    for _, _, text, _ in _run(CHAINED_CAST):
        code = text.split(" ", 1)[0]
        assert code.startswith("TW")
        assert len(code) == 5
        assert text[len(code)] == " "


def test_flake8_honors_exclude_patterns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import textwrap

    import typewitness.flake8_plugin as plugin_module

    root = write_project(
        make_root(tmp_path),
        {"keep.py": CAST_NO_EVIDENCE, "generated/mod.py": CAST_NO_EVIDENCE},
        pyproject=textwrap.dedent(
            """
            [project]
            name = "sample"
            version = "0.0.0"

            [tool.typewitness]
            exclude = ["generated"]
            """
        ).lstrip(),
    )
    target = root / "generated" / "mod.py"
    monkeypatch.chdir(root)
    plugin_module._clear_config_cache()
    plugin = TypeWitnessPlugin(
        ast.parse(CAST_NO_EVIDENCE),
        str(target),
        _lines(CAST_NO_EVIDENCE),
    )

    assert list(plugin.run()) == []


def test_flake8_rejects_symlink_filename_with_tw000(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = write_project(make_root(tmp_path), {"real.py": CAST_NO_EVIDENCE})
    alias = root / "alias.py"
    alias.symlink_to(root / "real.py")
    monkeypatch.chdir(root)

    plugin = TypeWitnessPlugin(
        ast.parse(CAST_NO_EVIDENCE),
        str(alias),
        _lines(CAST_NO_EVIDENCE),
    )
    violations = list(plugin.run())

    assert len(violations) == 1
    assert violations[0][2].startswith("TW000 ")
    assert "symlink" in violations[0][2]


def test_flake8_filesystem_error_is_tw000_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import typewitness.flake8_plugin as plugin_module

    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    target = root / "mod.py"
    monkeypatch.chdir(root)

    def exploding_overlay(project: Any) -> Any:
        raise ValueError("broken config lookup")

    monkeypatch.setattr(plugin_module, "load_pyproject_overlay", exploding_overlay)
    plugin_module._clear_config_cache()
    plugin = TypeWitnessPlugin(
        ast.parse(CAST_NO_EVIDENCE),
        str(target),
        _lines(CAST_NO_EVIDENCE),
    )
    violations = list(plugin.run())

    assert len(violations) == 1
    assert violations[0][2] == "TW000 broken config lookup"


def test_flake8_out_of_root_absolute_path_yields_tw000(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    write_project(make_root(tmp_path, "outside"), {"other.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)

    plugin = TypeWitnessPlugin(
        ast.parse(CAST_NO_EVIDENCE),
        str(Path("..") / "outside" / "other.py"),
        _lines(CAST_NO_EVIDENCE),
    )
    violations = list(plugin.run())

    assert len(violations) == 1
    assert violations[0][2].startswith("TW000 ")
    assert "project root" in violations[0][2]


def test_flake8_relative_path_without_project_uses_default_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lonely = make_root(tmp_path, "no-project")
    source = lonely / "mod.py"
    source.write_text(CAST_NO_EVIDENCE, encoding="utf-8")
    monkeypatch.chdir(lonely)

    plugin = TypeWitnessPlugin(
        ast.parse(CAST_NO_EVIDENCE),
        "mod.py",
        _lines(CAST_NO_EVIDENCE),
    )
    violations = list(plugin.run())

    assert violations
    assert violations[0][2].startswith("TW002 ")
