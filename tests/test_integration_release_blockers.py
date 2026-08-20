"""Release-review integration blockers: CLI-level regressions."""

from __future__ import annotations

import ast
import json
import subprocess
import textwrap
from pathlib import Path
from typing import Any, cast

import pytest

from tests._integration_support import (
    CAST_NO_EVIDENCE,
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
from typewitness.baseline import parse_baseline
from typewitness.cli import main

requires_git = pytest.mark.skipif(not git_available(), reason="git executable not available")


def _json(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    captured = capsys.readouterr()
    assert captured.out, "expected JSON document on stdout"
    return cast(dict[str, Any], json.loads(captured.out))


# ------------------------------------------------------------------ machine output


@pytest.mark.parametrize("output_format", ["json", "sarif"])
def test_machine_format_emits_document_on_clean_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    output_format: str,
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CLEAN_SOURCE})
    monkeypatch.chdir(root)

    assert main(["--format", output_format]) == 0
    payload = _json(capsys)
    if output_format == "json":
        assert payload["findings"] == []
        assert payload["errors"] == []
    else:
        assert payload["runs"][0]["results"] == []


@pytest.mark.parametrize("output_format", ["json", "sarif"])
def test_machine_format_emits_document_on_errors_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    output_format: str,
) -> None:
    root = write_project(make_root(tmp_path), {"bad.py": UNPARSEABLE_SOURCE})
    monkeypatch.chdir(root)

    assert main(["--format", output_format]) == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    if output_format == "json":
        assert payload["findings"] == []
        assert payload["errors"][0]["kind"] == "parse"
    else:
        assert payload["runs"][0]["invocations"][0]["toolExecutionNotifications"]
    assert captured.err == ""


def test_json_clean_run_parses_with_python_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CLEAN_SOURCE})
    monkeypatch.chdir(root)
    main(["--format", "json"])
    captured = capsys.readouterr()
    proc = subprocess.run(
        ("python3", "-c", "import json,sys; json.load(sys.stdin)"),
        input=captured.out,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_sarif_zero_results_on_clean_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CLEAN_SOURCE})
    monkeypatch.chdir(root)
    main(["--format", "sarif"])
    payload = _json(capsys)
    run = payload["runs"][0]
    assert run["results"] == []
    assert "originalUriBaseIds" in run
    assert run["invocations"][0]["executionSuccessful"] is True


# ---------------------------------------------------------- untracked filtering


@requires_git
def test_worktree_ignores_untracked_non_python_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_root(tmp_path)
    init_repo(root)
    write_project(root, {"mod.py": CLEAN_SOURCE})
    commit_all(root, "initial")
    write_bytes(root, "notes.txt", b"\xff\xfe\xfd" * 1000)
    write_bytes(root, "caf\u00e9.bin", b"\x00" * 5000)
    monkeypatch.chdir(root)

    assert main(["--worktree", "--format", "json"]) == 0


@requires_git
def test_worktree_untracked_invalid_python_is_structured_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = make_root(tmp_path)
    init_repo(root)
    write_project(root, {"mod.py": CLEAN_SOURCE})
    commit_all(root, "initial")
    write_file(root, "broken.py", UNPARSEABLE_SOURCE)
    monkeypatch.chdir(root)

    assert main(["--worktree", "--format", "json"]) == 2
    payload = _json(capsys)
    assert payload["errors"][0]["kind"] == "parse"
    assert payload["errors"][0]["path"] == "broken.py"


# ------------------------------------------------------------- limit errors


def test_oversize_file_is_limit_error_not_fatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"good.py": CAST_NO_EVIDENCE})
    write_bytes(root, "big.py", b"x = 1\n" * 500)
    monkeypatch.chdir(root)

    assert main(["--format", "json", "--max-file-bytes", "64"]) == 2
    payload = _json(capsys)
    assert payload["findings"]
    assert any(error["kind"] == "limit" for error in payload["errors"])


def test_explicit_oversize_file_is_limit_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {})
    write_bytes(root, "big.py", b"x = 1\n" * 500)
    monkeypatch.chdir(root)

    assert main(["--format", "json", "--max-file-bytes", "64", "big.py"]) == 2
    payload = _json(capsys)
    assert payload["errors"][0]["kind"] == "limit"


# ----------------------------------------------------------- baseline + git


@requires_git
def test_write_baseline_applies_git_filter_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_root(tmp_path)
    init_repo(root)
    write_project(root, {"mod.py": CHAINED_CAST})
    commit_all(root, "initial")
    monkeypatch.chdir(root)
    write_file(root, "mod.py", CHAINED_CAST + "extra = cast(str, 2)\n")

    assert main(["--worktree", "--baseline", "tw.json", "--write-baseline"]) == 0
    baseline = parse_baseline((root / "tw.json").read_text(encoding="utf-8"))
    assert len(baseline.entries) == 1


@requires_git
def test_write_baseline_refuses_when_errors_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_root(tmp_path)
    init_repo(root)
    write_project(root, {"mod.py": CAST_NO_EVIDENCE, "bad.py": UNPARSEABLE_SOURCE})
    commit_all(root, "initial")
    monkeypatch.chdir(root)
    before = '{"schema":"typewitness-baseline-1"}\n'
    (root / "tw.json").write_text(before, encoding="utf-8")

    assert main(["--baseline", "tw.json", "--write-baseline"]) == 2
    assert (root / "tw.json").read_text(encoding="utf-8") == before


@pytest.mark.parametrize("output_format", ["json", "sarif"])
def test_write_baseline_clean_run_emits_machine_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    output_format: str,
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)

    assert main(["--format", output_format, "--baseline", "tw.json", "--write-baseline"]) == 0
    captured = capsys.readouterr()
    assert captured.out
    assert captured.err == ""
    assert (root / "tw.json").is_file()
    payload = json.loads(captured.out)
    if output_format == "json":
        assert payload["findings"] == []
        assert payload["errors"] == []
    else:
        assert payload["runs"][0]["results"] == []


@pytest.mark.parametrize("output_format", ["json", "sarif"])
@requires_git
def test_write_baseline_error_run_emits_machine_document_and_preserves_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    output_format: str,
) -> None:
    root = make_root(tmp_path)
    init_repo(root)
    write_project(root, {"mod.py": CAST_NO_EVIDENCE, "bad.py": UNPARSEABLE_SOURCE})
    commit_all(root, "initial")
    monkeypatch.chdir(root)
    before = '{"schema":"typewitness-baseline-1"}\n'
    (root / "tw.json").write_text(before, encoding="utf-8")

    assert main(["--format", output_format, "--baseline", "tw.json", "--write-baseline"]) == 2
    captured = capsys.readouterr()
    assert captured.out
    assert captured.err == ""
    assert (root / "tw.json").read_text(encoding="utf-8") == before
    payload = json.loads(captured.out)
    if output_format == "json":
        assert payload["findings"]
        assert payload["errors"]
        assert payload["errors"][0]["kind"] == "parse"
    else:
        assert payload["runs"][0]["results"]
        assert payload["runs"][0]["invocations"][0]["toolExecutionNotifications"]


@pytest.mark.parametrize("output_format", ["json", "sarif"])
@requires_git
def test_write_baseline_mixed_run_emits_findings_and_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    output_format: str,
) -> None:
    root = make_root(tmp_path)
    init_repo(root)
    write_project(root, {"mod.py": CAST_NO_EVIDENCE, "bad.py": UNPARSEABLE_SOURCE})
    commit_all(root, "initial")
    monkeypatch.chdir(root)
    before = '{"schema":"typewitness-baseline-1"}\n'
    (root / "tw.json").write_text(before, encoding="utf-8")

    assert main(["--format", output_format, "--baseline", "tw.json", "--write-baseline"]) == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert (root / "tw.json").read_text(encoding="utf-8") == before
    if output_format == "json":
        assert payload["findings"]
        assert payload["errors"]
    else:
        assert payload["runs"][0]["results"]
        assert payload["runs"][0]["invocations"][0]["toolExecutionNotifications"]


# --------------------------------------------------------------- exclude


@pytest.mark.parametrize(
    "pattern",
    ["generated", "generated/", "./generated", "/generated"],
)
def test_exclude_normalization_blocks_directory_walk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    pattern: str,
) -> None:
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
    monkeypatch.chdir(root)
    assert main(["--format", "json"]) == 1
    payload = _json(capsys)
    assert {entry["path"] for entry in payload["findings"]} == {"keep.py"}


def test_explicit_excluded_file_exits_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"generated/mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)
    assert main(["--exclude", "generated", "generated/mod.py"]) == 0
    assert capsys.readouterr().out == ""


# --------------------------------------------------------------- symlinks


def test_explicit_symlink_input_is_usage_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"real.py": CAST_NO_EVIDENCE})
    (root / "alias.py").symlink_to(root / "real.py")
    monkeypatch.chdir(root)
    assert main(["alias.py"]) == 3
    assert "alias.py" in capsys.readouterr().err


# ---------------------------------------------------------- project discovery


def test_project_root_follows_cwd_not_first_path_argument(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    outer = write_project(make_root(tmp_path, "outer"), {"outer.py": CAST_NO_EVIDENCE})
    inner = write_project(outer / "inner", {"inner.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(inner)
    assert main(["--format", "json", str(outer / "outer.py")]) == 3
    assert capsys.readouterr().err


def test_config_flag_selects_project_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    outer = write_project(make_root(tmp_path, "outer"), {"outer.py": CAST_NO_EVIDENCE})
    inner = write_project(outer / "inner", {"inner.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(tmp_path)
    assert main(["--config", str(inner / "pyproject.toml"), "--format", "json"]) == 1
    payload = _json(capsys)
    assert {entry["path"] for entry in payload["findings"]} == {"inner.py"}


def test_config_dir_starts_discovery_from_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    outer = write_project(make_root(tmp_path, "outer"), {"outer.py": CAST_NO_EVIDENCE})
    inner = write_project(outer / "inner", {"inner.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(outer)
    assert main(["--config", str(inner), "--format", "json"]) == 1
    payload = _json(capsys)
    assert {entry["path"] for entry in payload["findings"]} == {"inner.py"}


def test_absolute_path_from_unrelated_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = write_project(make_root(tmp_path, "project"), {"mod.py": CAST_NO_EVIDENCE})
    unrelated = make_root(tmp_path, "elsewhere")
    unrelated.mkdir(exist_ok=True)
    monkeypatch.chdir(unrelated)
    assert main(["--format", "json", str(project_root / "mod.py")]) == 1
    payload = _json(capsys)
    assert {entry["path"] for entry in payload["findings"]} == {"mod.py"}


def test_multiple_input_project_roots_exit_three(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = write_project(make_root(tmp_path, "first"), {"a.py": CAST_NO_EVIDENCE})
    second = write_project(make_root(tmp_path, "second"), {"b.py": CAST_NO_EVIDENCE})
    unrelated = make_root(tmp_path, "elsewhere")
    unrelated.mkdir(exist_ok=True)
    monkeypatch.chdir(unrelated)
    assert main(["--format", "json", str(first / "a.py"), str(second / "b.py")]) == 3
    assert "multiple project roots" in capsys.readouterr().err


# ----------------------------------------------------------- unborn git


@requires_git
def test_worktree_on_unborn_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = make_root(tmp_path)
    init_repo(root)
    write_project(root, {"mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)
    assert main(["--worktree", "--format", "json"]) == 1
    payload = _json(capsys)
    assert payload["findings"]


@requires_git
def test_staged_on_unborn_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = make_root(tmp_path)
    init_repo(root)
    write_project(root, {"mod.py": CAST_NO_EVIDENCE})
    stage(root, "mod.py")
    monkeypatch.chdir(root)
    assert main(["--staged", "--format", "json"]) == 1
    payload = _json(capsys)
    assert payload["findings"]


# --------------------------------------------------------- flake8 parity


def test_flake8_matches_cli_fingerprint_for_same_basename_sibling(
    tmp_path: Path,
) -> None:
    import typewitness.flake8_plugin as plugin_module

    root = write_project(
        make_root(tmp_path),
        {"pkg/a/mod.py": CAST_NO_EVIDENCE, "pkg/b/mod.py": CLEAN_SOURCE},
        pyproject=textwrap.dedent(
            """
            [project]
            name = "sample"
            version = "0.0.0"

            [tool.typewitness]
            select = ["TW002"]
            """
        ).lstrip(),
    )
    target = root / "pkg" / "a" / "mod.py"
    plugin = plugin_module.TypeWitnessPlugin(
        ast.parse(CAST_NO_EVIDENCE),
        str(target),
        CAST_NO_EVIDENCE.splitlines(keepends=True),
    )
    cli_fp = analyze_text("pkg/a/mod.py", CAST_NO_EVIDENCE).findings[0].fingerprint
    assert list(plugin.run())
    assert plugin._resolve_source_path().as_posix() == "pkg/a/mod.py"
    assert cli_fp


# -------------------------------------------------------- comma-separated


def test_comma_separated_select(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CHAINED_CAST})
    monkeypatch.chdir(root)
    assert main(["--format", "json", "--select", "TW001,TW002"]) == 1
    payload = _json(capsys)
    codes = {entry["code"] for entry in payload["findings"]}
    assert codes <= {"TW001", "TW002"}
