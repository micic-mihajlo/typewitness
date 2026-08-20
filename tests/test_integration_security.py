"""Adversarial regressions for integration-layer security hardening."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, List, Sequence

import pytest

from tests._integration_support import (
    CAST_NO_EVIDENCE,
    CLEAN_SOURCE,
    commit_all,
    git_available,
    git_checked,
    init_repo,
    make_root,
    write_bytes,
    write_file,
    write_project,
)
from typewitness.baseline import write_baseline
from typewitness.cli import main
from typewitness.discovery import read_source
from typewitness.errors import FilesystemError, GitError, UsageError
from typewitness.exit_codes import EXIT_USAGE_ERROR
from typewitness.git import DIFF_REF, WORKTREE, GitSelection, changed_lines, diff_command, run_git
from typewitness.project import ProjectDiscoveryError, discover_project
from typewitness.report import render_errors_text, render_text
from typewitness.settings import SettingsOverlay, parse_settings_toml, resolve_settings

requires_git = pytest.mark.skipif(not git_available(), reason="git executable not available")

DEFAULT_MAX_FILE_BYTES = 1_048_576
MAX_LINE_COUNT = 100_000


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    root = make_root(tmp_path)
    init_repo(root)
    write_project(root, files)
    commit_all(root, "initial")
    return root


# ---------------------------------------------------------------------- git hardening


def test_git_selection_rejects_ref_starting_with_dash() -> None:
    with pytest.raises(UsageError):
        GitSelection(mode=DIFF_REF, ref="--output=/tmp/evil")


def test_git_selection_rejects_nul_in_ref() -> None:
    with pytest.raises(UsageError):
        GitSelection(mode=DIFF_REF, ref="main\x00evil")


def test_diff_command_uses_end_of_options_for_diff_ref() -> None:
    command = diff_command(GitSelection(mode=DIFF_REF, ref="main"))
    assert "--end-of-options" in command
    assert command.index("--end-of-options") < command.index("main")
    assert command[-1] == "--"


def test_diff_command_uses_end_of_options_for_worktree() -> None:
    command = diff_command(GitSelection(mode=WORKTREE))
    assert "--end-of-options" in command
    assert "HEAD" in command


def test_run_git_scrubs_injection_env_and_uses_argv_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_root(tmp_path)
    observed: dict[str, Any] = {}

    def recording_run(args: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        observed["args"] = args
        observed["shell"] = kwargs.get("shell")
        observed["stdin"] = kwargs.get("stdin")
        observed["timeout"] = kwargs.get("timeout")
        observed["env_keys"] = sorted(kwargs.get("env", {}))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", recording_run)
    monkeypatch.setenv("GIT_EXTERNAL_DIFF", "evil")
    monkeypatch.setenv("GIT_DIFF_OPTS", "--output=/tmp/pwned")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "diff.external")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "sh -c id")

    assert run_git(root, ("rev-parse", "--show-toplevel")) == "ok\n"
    assert observed.get("shell") in (False, None)
    assert observed["stdin"] == subprocess.DEVNULL
    assert observed["timeout"] is not None
    assert "GIT_EXTERNAL_DIFF" not in observed["env_keys"]
    assert "GIT_DIFF_OPTS" not in observed["env_keys"]
    assert all(not key.startswith("GIT_CONFIG") for key in observed["env_keys"])


def test_run_git_timeout_becomes_git_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_root(tmp_path)

    def timeout_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 1))

    monkeypatch.setattr(subprocess, "run", timeout_run)

    with pytest.raises(GitError) as excinfo:
        run_git(root, ("status",))

    assert excinfo.value.exit_code == EXIT_USAGE_ERROR


def test_diff_ref_option_injection_is_rejected_at_selection() -> None:
    with pytest.raises(UsageError):
        GitSelection(mode=DIFF_REF, ref="--output=/tmp/evil")


@requires_git
def test_diff_ref_output_option_does_not_execute_external_diff(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"mod.py": CLEAN_SOURCE})
    project = discover_project(root)
    marker = tmp_path / "ext-diff-ran"

    with pytest.raises(UsageError):
        changed_lines(project, GitSelection(mode=DIFF_REF, ref=f"--output={marker}"))

    assert not marker.exists()


@requires_git
def test_diff_ref_ext_diff_env_is_not_executed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repo(tmp_path, {"mod.py": CLEAN_SOURCE})
    project = discover_project(root)
    marker = tmp_path / "ext-diff-env"
    driver = tmp_path / "evil-diff.sh"
    driver.write_text(
        f"#!/bin/sh\ntouch {marker}\nexit 1\n",
        encoding="utf-8",
    )
    driver.chmod(0o755)
    monkeypatch.setenv("GIT_EXTERNAL_DIFF", str(driver))

    changed_lines(project, GitSelection(mode=DIFF_REF, ref="HEAD~0"))

    assert not marker.exists()


# ------------------------------------------------------------------- untracked fail-closed


@requires_git
@pytest.mark.parametrize(
    "relative",
    [
        "caf\u00e9.py",
        "two words.py",
        "tab\there.py",
        'quote".py',
        "back\\slash.py",
        "-leading-dash.py",
    ],
)
def test_untracked_special_paths_use_nul_ls_files(
    tmp_path: Path,
    relative: str,
) -> None:
    root = _repo(tmp_path, {"mod.py": CLEAN_SOURCE})
    project = discover_project(root)
    write_file(root, relative, "a = 1\nb = 2\n")

    changed = changed_lines(project, GitSelection(mode=WORKTREE)).lines

    assert project.canonical(root / relative) in changed


@requires_git
def test_untracked_fail_closed_matches_full_scan_on_oversize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repo(tmp_path, {"mod.py": CLEAN_SOURCE})
    write_bytes(root, "huge.py", b"x = 1\n" * 300)
    settings = resolve_settings(SettingsOverlay(max_file_bytes=1024))
    monkeypatch.chdir(root)

    from typewitness.runner import run_analysis

    full = run_analysis(paths=[], settings=settings)
    worktree = run_analysis(
        paths=[],
        settings=settings,
        git_selection=GitSelection(mode=WORKTREE),
    )

    assert any(error.kind == "limit" for error in full.errors)
    assert any(error.kind == "limit" for error in worktree.errors)
    full_limit_paths = {
        error.path.as_posix() for error in full.errors if error.kind == "limit" and error.path
    }
    worktree_limit_paths = {
        error.path.as_posix() for error in worktree.errors if error.kind == "limit" and error.path
    }
    assert full_limit_paths == {"huge.py"}
    assert worktree_limit_paths == {"huge.py"}


# --------------------------------------------------------------------- bounded input


def test_read_source_rejects_file_one_byte_over_limit(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {})
    payload = b"x = 1\n" * 200
    write_bytes(root, "mod.py", payload)
    project = discover_project(root)
    limit = len(payload) - 1

    result = read_source(project, root / "mod.py", max_file_bytes=limit)

    assert result.error is not None
    assert result.error.kind == "limit"
    assert "mod.py" in result.error.message
    assert str(limit) in result.error.message


def test_read_source_accepts_file_one_byte_below_limit(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {})
    payload = b"x = 1\n"
    write_bytes(root, "mod.py", payload)
    project = discover_project(root)

    result = read_source(project, root / "mod.py", max_file_bytes=len(payload) + 1)

    assert result.source is not None


def test_read_source_rejects_file_at_exact_limit_if_growing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = write_project(make_root(tmp_path), {})
    target = write_bytes(root, "mod.py", b"x = 1\ny = 2\n")
    project = discover_project(root)
    limit = 6
    original_stat = Path.stat

    def capped_stat(self: Path, *args: Any, **kwargs: Any) -> os.stat_result:
        result = original_stat(self, *args, **kwargs)
        if self == target:
            return os.stat_result(
                (
                    result.st_mode,
                    result.st_ino,
                    result.st_dev,
                    result.st_nlink,
                    result.st_uid,
                    result.st_gid,
                    limit,
                    result.st_atime,
                    result.st_mtime,
                    result.st_ctime,
                )
            )
        return result

    monkeypatch.setattr(Path, "stat", capped_stat)

    result = read_source(project, target, max_file_bytes=limit)

    assert result.error is not None
    assert result.error.kind == "limit"


def test_max_file_bytes_cli_overrides_pyproject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyproject = textwrap.dedent(
        """
        [project]
        name = "sample"
        version = "0.0.0"

        [tool.typewitness]
        max-file-bytes = 2048
        """
    ).lstrip()
    root = write_project(make_root(tmp_path), {"mod.py": CLEAN_SOURCE}, pyproject=pyproject)
    write_bytes(root, "big.py", b"x = 1\n" * 300)
    monkeypatch.chdir(root)

    assert main(["--max-file-bytes", "4096"]) in (0, 1, 2)
    assert main(["--max-file-bytes", "64"]) == 2


def test_max_file_bytes_from_pyproject(tmp_path: Path) -> None:
    overlay = parse_settings_toml(
        '[project]\nname = "s"\nversion = "0"\n\n[tool.typewitness]\nmax-file-bytes = 8192\n'
    )
    settings = resolve_settings(overlay)
    assert settings.max_file_bytes == 8192


def test_read_source_rejects_excessive_line_count(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {})
    write_bytes(root, "wide.py", (b"x = 1\n" * (MAX_LINE_COUNT + 1)))
    project = discover_project(root)

    result = read_source(project, root / "wide.py")

    assert result.error is not None
    assert result.error.kind == "limit"
    assert "wide.py" in result.error.message


# ------------------------------------------------------------------ baseline safety


def test_write_baseline_uses_unpredictable_temp_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tempfile

    import typewitness.baseline as baseline_module

    root = make_root(tmp_path)
    target = root / "typewitness-baseline.json"
    observed: List[str] = []
    original_mkstemp = tempfile.mkstemp

    def recording_mkstemp(*args: Any, **kwargs: Any) -> tuple[int, str]:
        fd, name = original_mkstemp(*args, **kwargs)
        observed.append(name)
        return fd, name

    monkeypatch.setattr(baseline_module.tempfile, "mkstemp", recording_mkstemp)  # type: ignore[attr-defined]

    from tests._integration_support import analyze_text

    write_baseline(root, target, analyze_text("mod.py", CAST_NO_EVIDENCE).findings)

    assert len(observed) == 1
    assert observed[0].startswith(str(root))
    assert ".typewitness-baseline.json." in observed[0]
    assert observed[0] != str(root / ".typewitness-baseline.json.tmp")


def test_write_baseline_preserves_existing_mode(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    target = root / "typewitness-baseline.json"
    from tests._integration_support import analyze_text

    write_baseline(root, target, analyze_text("mod.py", CAST_NO_EVIDENCE).findings)
    target.chmod(0o640)
    before = stat.S_IMODE(target.stat().st_mode)
    write_baseline(root, target, analyze_text("mod.py", CAST_NO_EVIDENCE).findings)
    after = stat.S_IMODE(target.stat().st_mode)
    assert after == before == 0o640


def test_write_baseline_does_not_follow_predictable_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_root(tmp_path)
    target = root / "typewitness-baseline.json"
    predictable = root / ".typewitness-baseline.json.tmp"
    predictable.symlink_to(tmp_path / "outside" / "stolen.json")
    (tmp_path / "outside").mkdir()
    from tests._integration_support import analyze_text

    write_baseline(root, target, analyze_text("mod.py", CAST_NO_EVIDENCE).findings)

    assert target.is_file()
    assert not (tmp_path / "outside" / "stolen.json").exists()


def test_write_baseline_cleans_temp_on_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_root(tmp_path)
    target = root / "typewitness-baseline.json"
    from tests._integration_support import analyze_text

    def failing_replace(src: Any, dst: Any, **kwargs: Any) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", failing_replace)

    with pytest.raises(FilesystemError):
        write_baseline(root, target, analyze_text("mod.py", CAST_NO_EVIDENCE).findings)

    leftovers = [entry.name for entry in root.iterdir()]
    assert leftovers == [] or leftovers == ["typewitness-baseline.json"]


# ----------------------------------------------------------- project discovery


@requires_git
def test_project_discovery_stops_at_git_root_without_pyproject(tmp_path: Path) -> None:
    repo = make_root(tmp_path, "repo")
    init_repo(repo)
    write_file(repo, ".keep", "tracked\n")
    inner = repo / "inner"
    inner.mkdir()
    commit_all(repo, "initial")

    with pytest.raises(ProjectDiscoveryError):
        discover_project(inner)


@requires_git
def test_unrelated_ancestor_pyproject_outside_git_is_ignored(tmp_path: Path) -> None:
    write_project(make_root(tmp_path, "outside"), {"lib.py": CLEAN_SOURCE})
    repo = make_root(tmp_path, "repo")
    init_repo(repo)
    root = write_project(repo / "pkg", {"mod.py": CLEAN_SOURCE})
    commit_all(repo, "initial")

    project = discover_project(root)

    assert project.root == root


@requires_git
def test_nested_repo_uses_inner_git_boundary(tmp_path: Path) -> None:
    outer = make_root(tmp_path, "outer")
    init_repo(outer)
    write_project(outer, {"outer.py": CLEAN_SOURCE})
    commit_all(outer, "outer")
    inner = outer / "inner"
    init_repo(inner)
    write_project(inner, {"inner.py": CLEAN_SOURCE})
    commit_all(inner, "inner")

    project = discover_project(inner)

    assert project.root == inner


@requires_git
def test_worktree_git_file_counts_as_vcs_root(tmp_path: Path) -> None:
    if sys.platform == "win32":
        pytest.skip("git worktree not exercised on Windows here")
    main_repo = make_root(tmp_path, "main")
    init_repo(main_repo)
    write_project(main_repo, {"mod.py": CLEAN_SOURCE})
    commit_all(main_repo, "initial")
    linked = make_root(tmp_path, "linked")
    git_checked(main_repo, "worktree", "add", "--detach", str(linked), "HEAD")
    assert (linked / ".git").is_file()

    project = discover_project(linked)

    assert project.root == linked


def test_non_git_discovery_depth_is_capped(tmp_path: Path) -> None:
    from typewitness.project import _MAX_NON_GIT_SEARCH_DEPTH

    base = write_project(make_root(tmp_path, "root"), {"mod.py": CLEAN_SOURCE})
    current = base
    for index in range(_MAX_NON_GIT_SEARCH_DEPTH):
        current = current / f"seg{index}"
        current.mkdir()

    assert discover_project(current).root == base

    too_deep = current / f"seg{_MAX_NON_GIT_SEARCH_DEPTH}"
    too_deep.mkdir()
    with pytest.raises(ProjectDiscoveryError):
        discover_project(too_deep)


@requires_git
def test_baseline_write_stays_inside_discovered_project(tmp_path: Path) -> None:
    repo = make_root(tmp_path, "repo")
    init_repo(repo)
    root = write_project(repo / "pkg", {"mod.py": CAST_NO_EVIDENCE})
    commit_all(repo, "initial")
    project = discover_project(root)
    target = project.root / "baseline.json"
    from tests._integration_support import analyze_text

    write_baseline(project.root, target, analyze_text("mod.py", CAST_NO_EVIDENCE).findings)

    assert target.is_file()
    assert target.parent == project.root

    outside = tmp_path / "outside-baseline.json"
    with pytest.raises(FilesystemError):
        write_baseline(project.root, outside, analyze_text("mod.py", CAST_NO_EVIDENCE).findings)

    link = project.root / "linked"
    link.symlink_to(tmp_path / "real", target_is_directory=True)
    (tmp_path / "real").mkdir()
    with pytest.raises(FilesystemError):
        write_baseline(
            project.root,
            link / "baseline.json",
            analyze_text("mod.py", CAST_NO_EVIDENCE).findings,
        )


# ------------------------------------------------------------------- safe text output


def test_text_output_escapes_control_characters_in_paths() -> None:
    from typewitness.models import Finding, SourceLocation, SourceRange
    from typewitness.report import Report

    finding = Finding(
        code="TW002",
        path=Path("a\nb.py"),
        range=SourceRange(
            start=SourceLocation(line=1, column=0),
            end=SourceLocation(line=1, column=5),
        ),
        message="bad\rmessage",
        fingerprint="0123456789abcdef",
    )
    rendered = render_text(Report(findings=(finding,), errors=()))
    assert rendered.count("\n") == 1
    assert "\\x0a" in rendered
    assert "\\x0d" in rendered


def test_error_text_escapes_ansi_and_tabs() -> None:
    from typewitness.models import AnalysisError
    from typewitness.report import Report

    error = AnalysisError(kind="parse", path=Path("a\tb.py"), message="bad\x1b[31mmsg")
    rendered = render_errors_text(Report(findings=(), errors=(error,)))
    assert rendered.count("\n") == 1
    assert "\\x09" in rendered
    assert "\\x1b" in rendered


def test_json_output_preserves_unicode_path_unchanged() -> None:
    import json

    from tests._integration_support import analyze_text
    from typewitness.report import Report, render_json

    finding = analyze_text("src dir/caf\u00e9/mod.py", CAST_NO_EVIDENCE).findings[0]

    payload = json.loads(render_json(Report(findings=(finding,), errors=())))
    assert payload["findings"][0]["path"] == "src dir/caf\u00e9/mod.py"


# ------------------------------------------------------------------------ flake8


def test_flake8_plugin_canonicalizes_absolute_filename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ast

    import typewitness.flake8_plugin as plugin_module

    root = write_project(make_root(tmp_path), {"pkg/mod.py": CAST_NO_EVIDENCE})
    target = root / "pkg" / "mod.py"
    calls: List[str] = []
    original = plugin_module.analyze

    def capturing_analyze(source: Any, config: Any = None) -> Any:
        calls.append(source.path.as_posix())
        return original(source, config)

    monkeypatch.setattr(plugin_module, "analyze", capturing_analyze)
    plugin = plugin_module.TypeWitnessPlugin(
        ast.parse(CAST_NO_EVIDENCE),
        str(target),
        CAST_NO_EVIDENCE.splitlines(keepends=True),
    )
    list(plugin.run())

    assert calls == ["pkg/mod.py"]
