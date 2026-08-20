"""Deterministic end-to-end runs through ``typewitness.cli.main``.

``main`` returns an exit code instead of raising ``SystemExit`` so the whole surface is
testable in-process, including argparse usage errors, which must surface as exit code 3
rather than argparse's own 2.

Every run happens inside a temporary project. Nothing here reads user config, the
environment, or the network.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from tests._integration_support import (
    CAST_NO_EVIDENCE,
    CAST_WITH_EVIDENCE,
    CHAINED_CAST,
    CLEAN_SOURCE,
    UNPARSEABLE_SOURCE,
    analyze_text,
    commit_all,
    git_available,
    init_repo,
    make_root,
    stage,
    write_bytes,
    write_file,
    write_project,
)
from typewitness.cli import main
from typewitness.report import TOOL_VERSION

requires_git = pytest.mark.skipif(not git_available(), reason="git executable not available")

ANSI = re.compile("\x1b\\[")

CONFIGURED_PYPROJECT = (
    '[project]\nname = "sample"\nversion = "0.0.0"\n\n'
    '[tool.typewitness]\nselect = ["TW002"]\noutput-format = "json"\n'
)


def _json_out(capsys: pytest.CaptureFixture[str]) -> Dict[str, Any]:
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert isinstance(payload, dict)
    return payload


# ------------------------------------------------------------------------- exit codes


def test_clean_project_exits_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"pkg/mod.py": CAST_WITH_EVIDENCE})
    monkeypatch.chdir(root)

    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert captured.err == ""


def test_findings_exit_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"pkg/mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)

    exit_code = main([])

    captured = capsys.readouterr()
    finding = analyze_text("pkg/mod.py", CAST_NO_EVIDENCE).findings[0]
    expected = (
        f"pkg/mod.py:{finding.range.start.line}:{finding.range.start.column + 1}: "
        f"{finding.code} {finding.message}"
    )
    assert exit_code == 1
    assert captured.out.splitlines() == [expected]


def test_source_analysis_error_exits_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"pkg/bad.py": UNPARSEABLE_SOURCE})
    monkeypatch.chdir(root)

    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "pkg/bad.py" in captured.err
    assert "parse" in captured.err


def test_undecodable_file_exits_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {})
    write_bytes(root, "pkg/bad.py", b'VALUE = "\xff\xfe\xfd"\n')
    monkeypatch.chdir(root)

    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "encode" in captured.err


def test_analysis_errors_outrank_findings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(
        make_root(tmp_path),
        {"pkg/bad.py": UNPARSEABLE_SOURCE, "pkg/mod.py": CAST_NO_EVIDENCE},
    )
    monkeypatch.chdir(root)

    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "pkg/mod.py" in captured.out
    assert "pkg/bad.py" in captured.err


def test_unknown_flag_exits_three_without_raising(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """argparse exits 2 by default; the CLI must translate that to the usage code."""
    root = write_project(make_root(tmp_path), {"mod.py": CLEAN_SOURCE})
    monkeypatch.chdir(root)

    exit_code = main(["--no-such-flag"])

    assert exit_code == 3
    assert capsys.readouterr().err


def test_unknown_rule_code_on_the_command_line_exits_three(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)

    exit_code = main(["--select", "TW999"])

    assert exit_code == 3
    assert "TW999" in capsys.readouterr().err


def test_invalid_pyproject_config_exits_three(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bad = '[project]\nname = "sample"\nversion = "0.0.0"\n\n[tool.typewitness]\nselct = []\n'
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE}, pyproject=bad)
    monkeypatch.chdir(root)

    exit_code = main([])

    assert exit_code == 3
    assert "selct" in capsys.readouterr().err


def test_missing_pyproject_exits_three(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = make_root(tmp_path, "no-project")
    write_file(root, "mod.py", CAST_NO_EVIDENCE)
    monkeypatch.chdir(root)

    exit_code = main([])

    assert exit_code == 3
    assert "pyproject.toml" in capsys.readouterr().err


def test_missing_input_path_exits_three(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)

    exit_code = main(["missing.py"])

    assert exit_code == 3
    assert "missing.py" in capsys.readouterr().err


def test_git_mode_outside_a_repository_exits_three(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)

    exit_code = main(["--worktree"])

    assert exit_code == 3
    assert capsys.readouterr().err


def test_usage_error_outranks_findings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)

    assert main([]) == 1
    capsys.readouterr()
    assert main(["--baseline", "missing-baseline.json"]) == 3
    assert capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["--staged", "--worktree"],
        ["--staged", "--diff-ref", "main"],
        ["--worktree", "--diff-ref", "main"],
        ["--staged", "--worktree", "--diff-ref", "main"],
    ],
)
def test_git_modes_are_mutually_exclusive(
    argv: List[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CLEAN_SOURCE})
    monkeypatch.chdir(root)

    exit_code = main(argv)

    assert exit_code == 3
    assert capsys.readouterr().err


def test_diff_ref_requires_a_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CLEAN_SOURCE})
    monkeypatch.chdir(root)

    exit_code = main(["--diff-ref"])

    assert exit_code == 3
    assert capsys.readouterr().err


# ------------------------------------------------------------- invocation invariance


def test_relative_and_absolute_invocation_agree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The headline guarantee: how you spelled the path cannot change the output."""
    root = write_project(make_root(tmp_path), {"pkg/mod.py": CHAINED_CAST})

    monkeypatch.chdir(root)
    assert main(["--format", "json", "pkg/mod.py"]) == 1
    relative = _json_out(capsys)

    assert main(["--format", "json", str((root / "pkg" / "mod.py").resolve())]) == 1
    absolute = _json_out(capsys)

    assert relative == absolute
    assert {entry["path"] for entry in relative["findings"]} == {"pkg/mod.py"}


def test_invocation_from_a_subdirectory_agrees(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"pkg/sub/mod.py": CHAINED_CAST})

    monkeypatch.chdir(root)
    assert main(["--format", "json"]) == 1
    from_root = _json_out(capsys)

    monkeypatch.chdir(root / "pkg" / "sub")
    assert main(["--format", "json", "."]) == 1
    from_subdir = _json_out(capsys)

    assert from_root == from_subdir


def test_cli_fingerprints_match_the_library(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"pkg/mod.py": CHAINED_CAST})
    monkeypatch.chdir(root)

    assert main(["--format", "json"]) == 1
    payload = _json_out(capsys)

    expected: List[Tuple[str, str]] = sorted(
        (finding.code, finding.fingerprint)
        for finding in analyze_text("pkg/mod.py", CHAINED_CAST).findings
    )
    actual = sorted((entry["code"], entry["fingerprint"]) for entry in payload["findings"])
    assert actual == expected


def test_output_is_byte_stable_across_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(
        make_root(tmp_path),
        {"b.py": CHAINED_CAST, "a.py": CAST_NO_EVIDENCE, "pkg/c.py": CHAINED_CAST},
    )
    monkeypatch.chdir(root)

    main(["--format", "json"])
    first = capsys.readouterr().out
    main(["--format", "json"])
    second = capsys.readouterr().out

    assert first == second


def test_findings_are_ordered_by_path_then_position(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(
        make_root(tmp_path),
        {"z.py": CAST_NO_EVIDENCE, "a.py": CAST_NO_EVIDENCE, "pkg/m.py": CAST_NO_EVIDENCE},
    )
    monkeypatch.chdir(root)

    main(["--format", "json"])
    payload = _json_out(capsys)

    keys = [
        (entry["path"], entry["line"], entry["column"], entry["code"])
        for entry in payload["findings"]
    ]
    assert keys == sorted(keys)


# ----------------------------------------------------------------------- output routing


def test_findings_go_to_stdout_and_errors_to_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(
        make_root(tmp_path),
        {"good.py": CAST_NO_EVIDENCE, "bad.py": UNPARSEABLE_SOURCE},
    )
    monkeypatch.chdir(root)

    main([])

    captured = capsys.readouterr()
    assert "good.py" in captured.out
    assert "good.py" not in captured.err
    assert "bad.py" in captured.err
    assert "bad.py" not in captured.out


def test_output_carries_no_ansi_escapes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CHAINED_CAST})
    monkeypatch.chdir(root)

    main([])

    captured = capsys.readouterr()
    assert not ANSI.search(captured.out)
    assert not ANSI.search(captured.err)


def test_sarif_output_is_a_single_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"pkg/mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)

    assert main(["--format", "sarif"]) == 1

    payload = _json_out(capsys)
    assert payload["version"] == "2.1.0"
    result = payload["runs"][0]["results"][0]
    location = result["locations"][0]["physicalLocation"]
    assert location["artifactLocation"]["uri"] == "pkg/mod.py"
    finding = analyze_text("pkg/mod.py", CAST_NO_EVIDENCE).findings[0]
    assert location["region"]["startColumn"] == finding.range.start.column + 1


def test_version_flag_prints_the_tool_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)

    exit_code = main(["--version"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert TOOL_VERSION in captured.out


def test_help_flag_exits_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)

    exit_code = main(["--help"])

    captured = capsys.readouterr()
    assert exit_code == 0
    for flag in ("--staged", "--worktree", "--diff-ref", "--baseline", "--format"):
        assert flag in captured.out


# ------------------------------------------------------------------ config precedence


def test_cli_select_overrides_pyproject_select(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(
        make_root(tmp_path),
        {"mod.py": CHAINED_CAST},
        pyproject=CONFIGURED_PYPROJECT,
    )
    monkeypatch.chdir(root)

    assert main([]) == 1
    from_pyproject = _json_out(capsys)
    assert main(["--select", "TW001"]) == 1
    from_cli = _json_out(capsys)

    assert {entry["code"] for entry in from_pyproject["findings"]} == {"TW002"}
    assert {entry["code"] for entry in from_cli["findings"]} == {"TW001"}


def test_pyproject_output_format_is_honoured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(
        make_root(tmp_path),
        {"mod.py": CAST_NO_EVIDENCE},
        pyproject=CONFIGURED_PYPROJECT,
    )
    monkeypatch.chdir(root)

    assert main([]) == 1

    assert _json_out(capsys)["schema"] == "typewitness-json-1"


def test_cli_ignore_overrides_pyproject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(
        make_root(tmp_path),
        {"mod.py": CHAINED_CAST},
        pyproject=CONFIGURED_PYPROJECT,
    )
    monkeypatch.chdir(root)

    assert main(["--ignore", "TW002"]) == 0
    payload = _json_out(capsys)
    assert payload["findings"] == []


def test_exclude_from_the_command_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(
        make_root(tmp_path),
        {"generated/mod.py": CAST_NO_EVIDENCE, "keep.py": CAST_NO_EVIDENCE},
    )
    monkeypatch.chdir(root)

    assert main(["--format", "json", "--exclude", "generated"]) == 1

    payload = _json_out(capsys)
    assert {entry["path"] for entry in payload["findings"]} == {"keep.py"}


# ------------------------------------------------------------------------ one pass only


def test_each_file_is_analyzed_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import typewitness.runner as runner_module

    root = write_project(
        make_root(tmp_path),
        {"a.py": CAST_NO_EVIDENCE, "pkg/b.py": CHAINED_CAST, "pkg/c.py": CLEAN_SOURCE},
    )
    monkeypatch.chdir(root)
    analyzed: List[str] = []
    original = runner_module.analyze

    def counting_analyze(source: Any, config: Any = None) -> Any:
        analyzed.append(source.path.as_posix())
        return original(source, config)

    monkeypatch.setattr(runner_module, "analyze", counting_analyze)

    main(["--format", "json"])
    capsys.readouterr()

    assert sorted(analyzed) == ["a.py", "pkg/b.py", "pkg/c.py"]
    assert len(analyzed) == len(set(analyzed))


# ------------------------------------------------------------------------- baselines


def test_write_baseline_then_clean_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"pkg/mod.py": CHAINED_CAST})
    monkeypatch.chdir(root)

    assert main(["--baseline", "tw-baseline.json", "--write-baseline"]) == 0
    capsys.readouterr()
    assert (root / "tw-baseline.json").is_file()

    assert main(["--baseline", "tw-baseline.json"]) == 0
    assert capsys.readouterr().out == ""


def test_baseline_reports_only_new_findings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"pkg/mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)
    assert main(["--baseline", "tw-baseline.json", "--write-baseline"]) == 0
    capsys.readouterr()

    write_file(root, "pkg/other.py", CAST_NO_EVIDENCE)

    assert main(["--format", "json", "--baseline", "tw-baseline.json"]) == 1
    payload = _json_out(capsys)

    assert {entry["path"] for entry in payload["findings"]} == {"pkg/other.py"}


def test_missing_baseline_file_exits_three(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)

    exit_code = main(["--baseline", "tw-baseline.json"])

    assert exit_code == 3
    assert capsys.readouterr().err


def test_corrupt_baseline_file_exits_three(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    write_file(root, "tw-baseline.json", '{"schema": "typewitness-baseline-0"}\n')
    monkeypatch.chdir(root)

    exit_code = main(["--baseline", "tw-baseline.json"])

    assert exit_code == 3
    assert "typewitness-baseline-0" in capsys.readouterr().err


def test_baseline_path_from_pyproject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject = (
        '[project]\nname = "sample"\nversion = "0.0.0"\n\n'
        '[tool.typewitness]\nbaseline = "tw-baseline.json"\n'
    )
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE}, pyproject=pyproject)
    monkeypatch.chdir(root)

    assert main(["--write-baseline"]) == 0
    capsys.readouterr()

    assert (root / "tw-baseline.json").is_file()
    assert main([]) == 0
    assert capsys.readouterr().out == ""


def test_write_baseline_without_a_target_exits_three(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)

    exit_code = main(["--write-baseline"])

    assert exit_code == 3
    assert capsys.readouterr().err


# ---------------------------------------------------------------------- git filtering


@requires_git
def test_worktree_mode_reports_only_touched_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = make_root(tmp_path)
    init_repo(root)
    write_project(root, {"pkg/mod.py": CAST_NO_EVIDENCE})
    commit_all(root, "initial")
    monkeypatch.chdir(root)

    assert main(["--worktree"]) == 0
    assert capsys.readouterr().out == ""

    write_file(root, "pkg/mod.py", CAST_NO_EVIDENCE + "second = cast(str, 2)\n")

    assert main(["--format", "json", "--worktree"]) == 1
    payload = _json_out(capsys)
    assert [entry["line"] for entry in payload["findings"]] == [4]


@requires_git
def test_staged_mode_ignores_unstaged_edits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = make_root(tmp_path)
    init_repo(root)
    write_project(root, {"pkg/mod.py": CLEAN_SOURCE})
    commit_all(root, "initial")
    monkeypatch.chdir(root)
    write_file(root, "pkg/mod.py", CAST_NO_EVIDENCE)

    assert main(["--staged"]) == 0
    capsys.readouterr()
    stage(root, "pkg/mod.py")
    assert main(["--staged"]) == 1
    assert "pkg/mod.py" in capsys.readouterr().out


@requires_git
def test_diff_ref_mode_reports_changes_since_the_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = make_root(tmp_path)
    init_repo(root)
    write_project(root, {"pkg/mod.py": CLEAN_SOURCE})
    base = commit_all(root, "initial")
    write_file(root, "pkg/mod.py", CAST_NO_EVIDENCE)
    commit_all(root, "second")
    monkeypatch.chdir(root)

    assert main(["--diff-ref", base]) == 1
    assert "pkg/mod.py" in capsys.readouterr().out


@requires_git
def test_git_error_outranks_findings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = make_root(tmp_path)
    init_repo(root)
    write_project(root, {"pkg/mod.py": CAST_NO_EVIDENCE})
    commit_all(root, "initial")
    monkeypatch.chdir(root)

    assert main([]) == 1
    capsys.readouterr()

    assert main(["--diff-ref", "no-such-ref"]) == 3
    assert capsys.readouterr().err


@requires_git
def test_baseline_and_git_mode_compose(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = make_root(tmp_path)
    init_repo(root)
    write_project(root, {"pkg/mod.py": CAST_NO_EVIDENCE})
    commit_all(root, "initial")
    monkeypatch.chdir(root)
    assert main(["--baseline", "tw-baseline.json", "--write-baseline"]) == 0
    capsys.readouterr()

    write_file(root, "pkg/mod.py", CAST_NO_EVIDENCE + "second = cast(str, 2)\n")

    assert main(["--format", "json", "--worktree", "--baseline", "tw-baseline.json"]) == 1
    payload = _json_out(capsys)
    assert [entry["line"] for entry in payload["findings"]] == [4]
