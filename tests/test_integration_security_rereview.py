"""Security re-review regressions: NFC/NFD, git env, textconv, baseline root, bidi, bounds."""

from __future__ import annotations

import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any, Sequence

import pytest

from tests._integration_support import (
    CAST_NO_EVIDENCE,
    CLEAN_SOURCE,
    commit_all,
    git_available,
    git_checked,
    init_repo,
    make_root,
    stage,
    write_file,
    write_project,
)
from typewitness.baseline import load_baseline, write_baseline
from typewitness.cli import main
from typewitness.discovery import MAX_MAX_FILE_BYTES
from typewitness.errors import ConfigError, FilesystemError, GitError
from typewitness.exit_codes import EXIT_USAGE_ERROR
from typewitness.git import (
    DIFF_REF,
    STAGED,
    WORKTREE,
    GitSelection,
    changed_lines,
    diff_command,
    filter_findings_to_changed_lines,
    run_git,
)
from typewitness.project import discover_project
from typewitness.report import escape_text_output, render_text
from typewitness.settings import parse_settings_toml

requires_git = pytest.mark.skipif(not git_available(), reason="git executable not available")

NFC_CAFE = "caf\u00e9.py"
NFD_CAFE = unicodedata.normalize("NFD", NFC_CAFE)


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    root = make_root(tmp_path)
    init_repo(root)
    write_project(root, files)
    commit_all(root, "initial")
    return root


# ------------------------------------------------------------------ NFC/NFD git filtering


def test_filter_findings_falls_back_to_nfc_index() -> None:
    from tests._integration_support import analyze_text

    findings = analyze_text(NFD_CAFE, CAST_NO_EVIDENCE).findings
    line = findings[0].range.start.line
    kept = filter_findings_to_changed_lines(
        findings,
        {unicodedata.normalize("NFC", NFD_CAFE): frozenset({line})},
    )
    assert kept == findings


def test_filter_findings_unions_collapsed_nfc_paths() -> None:
    from tests._integration_support import analyze_text

    findings = analyze_text(NFD_CAFE, CAST_NO_EVIDENCE).findings
    line = findings[0].range.start.line
    kept = filter_findings_to_changed_lines(
        findings,
        {
            NFC_CAFE: frozenset({999}),
            NFD_CAFE: frozenset({line}) if NFD_CAFE != NFC_CAFE else frozenset({line}),
        },
    )
    assert kept == findings


@requires_git
@pytest.mark.parametrize("git_mode", [WORKTREE, STAGED, DIFF_REF])
def test_unicode_filename_git_modes_report_findings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    git_mode: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _repo(tmp_path, {NFC_CAFE: CAST_NO_EVIDENCE})
    nfd_path = root / NFD_CAFE
    if not nfd_path.exists() and sys.platform == "darwin":
        nfc_path = root / NFC_CAFE
        if nfc_path.exists():
            nfd_path = nfc_path
    write_file(root, NFD_CAFE, CAST_NO_EVIDENCE + "\nextra = cast(str, 2)\n")
    monkeypatch.chdir(root)
    args = ["--format", "json"]
    if git_mode == WORKTREE:
        args.append("--worktree")
    elif git_mode == STAGED:
        stage(root, NFD_CAFE)
        args.append("--staged")
    else:
        args.extend(["--diff-ref", "HEAD"])
    exit_code = main(args)
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out
    assert "findings" in captured.out


# ----------------------------------------------------------- git diff failures


@requires_git
def test_worktree_git_diff_failure_exits_three(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _repo(tmp_path, {"mod.py": CLEAN_SOURCE})
    monkeypatch.chdir(root)
    import typewitness.git as git_module

    original = git_module.run_git

    def failing_diff(root_path: Path, args: Sequence[str]) -> str:
        if args and args[0] == "diff":
            raise GitError("fatal: diff failed")
        return original(root_path, args)

    monkeypatch.setattr(git_module, "run_git", failing_diff)
    assert main(["--worktree"]) == EXIT_USAGE_ERROR
    assert capsys.readouterr().err


def test_run_git_timeout_on_diff_is_not_swallowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_root(tmp_path)
    init_repo(root)

    def timeout_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 1))

    monkeypatch.setattr(subprocess, "run", timeout_run)
    with pytest.raises(GitError):
        run_git(root, diff_command(GitSelection(mode=WORKTREE)))


# --------------------------------------------------------------------- textconv


def test_diff_command_includes_no_textconv() -> None:
    for mode in (WORKTREE, STAGED, DIFF_REF):
        ref = "HEAD" if mode == DIFF_REF else None
        selection = GitSelection(mode=mode, ref=ref) if ref else GitSelection(mode=mode)
        assert "--no-textconv" in diff_command(selection)


@requires_git
def test_repo_local_textconv_driver_is_not_executed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repo(tmp_path, {"mod.py": CLEAN_SOURCE})
    marker = tmp_path / "textconv-ran"
    write_file(root, ".gitattributes", "*.py diff=evil\n")
    git_checked(root, "config", "diff.evil.textconv", f"touch {marker}")
    write_file(root, "mod.py", CAST_NO_EVIDENCE)
    project = discover_project(root)
    import typewitness.git as git_module

    observed: list[tuple[str, ...]] = []
    original = git_module.run_git

    def recording_run(root_path: Path, args: Sequence[str]) -> str:
        if args and args[0] == "diff":
            observed.append(tuple(args))
            assert "--no-textconv" in args
        return original(root_path, args)

    monkeypatch.setattr(git_module, "run_git", recording_run)
    changed_lines(project, GitSelection(mode=WORKTREE))
    assert observed
    assert not marker.exists()


# ----------------------------------------------------------- git env scrubbing


@pytest.mark.parametrize(
    "env_var",
    [
        "GIT_WORK_TREE",
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_NAMESPACE",
        "GIT_CEILING_DIRECTORIES",
    ],
)
def test_run_git_scrubs_repository_location_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    env_var: str,
) -> None:
    root = make_root(tmp_path)
    observed: dict[str, Any] = {}

    def recording_run(args: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        observed["env_keys"] = sorted(kwargs.get("env", {}))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", recording_run)
    monkeypatch.setenv(env_var, str(tmp_path / "evil"))
    run_git(root, ("rev-parse", "--show-toplevel"))
    assert env_var not in observed["env_keys"]


# --------------------------------------------------------- baseline containment


def test_write_baseline_rejects_outside_project_root(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    outside = tmp_path / "outside.json"
    from tests._integration_support import analyze_text

    with pytest.raises(FilesystemError):
        write_baseline(root, outside, analyze_text("mod.py", CAST_NO_EVIDENCE).findings)


def test_write_baseline_rejects_parent_symlink(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    link = root / "linked"
    link.symlink_to(tmp_path / "real", target_is_directory=True)
    (tmp_path / "real").mkdir()
    target = link / "baseline.json"
    from tests._integration_support import analyze_text

    with pytest.raises(FilesystemError):
        write_baseline(root, target, analyze_text("mod.py", CAST_NO_EVIDENCE).findings)


def test_write_baseline_rejects_target_symlink(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    target = root / "baseline.json"
    target.symlink_to(root / "other.json")
    from tests._integration_support import analyze_text

    with pytest.raises(FilesystemError):
        write_baseline(root, target, analyze_text("mod.py", CAST_NO_EVIDENCE).findings)


# ------------------------------------------------------------- text escaping


def test_text_output_escapes_bidi_and_line_separators() -> None:
    from typewitness.models import Finding, SourceLocation, SourceRange
    from typewitness.report import Report

    trojan = "safe\u202e evil.py"
    finding = Finding(
        code="TW002",
        path=Path(trojan),
        range=SourceRange(
            start=SourceLocation(line=1, column=0),
            end=SourceLocation(line=1, column=5),
        ),
        message="line\u2028sep\u2029para",
        fingerprint="0123456789abcdef",
    )
    rendered = render_text(Report(findings=(finding,), errors=()))
    assert rendered.count("\n") == 1
    assert "\u202e" not in rendered
    assert "\u2028" not in rendered
    assert "\u2029" not in rendered
    assert "\\u202e" in rendered


def test_escape_text_output_preserves_ordinary_unicode() -> None:
    assert escape_text_output("caf\u00e9") == "caf\u00e9"


# ----------------------------------------------------------- bounded settings


def test_max_file_bytes_hard_cap_in_pyproject() -> None:
    with pytest.raises(ConfigError):
        parse_settings_toml(
            "[project]\nname='s'\nversion='0'\n\n"
            f"[tool.typewitness]\nmax-file-bytes = {MAX_MAX_FILE_BYTES + 1}\n"
        )


def test_max_file_bytes_cli_hard_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CLEAN_SOURCE})
    monkeypatch.chdir(root)
    assert main(["--max-file-bytes", str(MAX_MAX_FILE_BYTES + 1)]) == EXIT_USAGE_ERROR


def test_oversize_pyproject_is_config_error(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    payload = b"[project]\nname='s'\nversion='0'\n" + b"#" * (1_048_576 + 1)
    (root / "pyproject.toml").write_bytes(payload)
    project = discover_project(root)
    from typewitness.settings import load_pyproject_overlay

    with pytest.raises(ConfigError) as excinfo:
        load_pyproject_overlay(project)
    assert "pyproject.toml" in str(excinfo.value)


def test_oversize_baseline_is_baseline_error(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    target = root / "baseline.json"
    target.write_bytes(b'{"schema":' + b" " * (8_388_608 + 1))
    with pytest.raises(Exception) as excinfo:
        load_baseline(target)
    assert "baseline" in str(excinfo.value).lower()


def test_recursion_error_in_pyproject_is_framed(monkeypatch: pytest.MonkeyPatch) -> None:
    import typewitness.settings as settings_module

    class _RecursingToml:
        def loads(self, text: str) -> object:
            raise RecursionError("too deep")

    monkeypatch.setattr(settings_module, "import_toml_module", lambda: _RecursingToml())
    with pytest.raises(ConfigError) as excinfo:
        parse_settings_toml("[project]\nname='s'\nversion='0'\n")
    assert "pyproject.toml" in str(excinfo.value)


# ----------------------------------------------------------- flake8 config


def test_flake8_malformed_config_emits_tw000(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ast

    import typewitness.flake8_plugin as plugin_module

    pyproject = (
        '[project]\nname = "sample"\nversion = "0.0.0"\n\n'
        '[tool.typewitness]\nselect = "not-a-list"\n'
    )
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE}, pyproject=pyproject)
    target = root / "mod.py"
    monkeypatch.chdir(root)
    plugin = plugin_module.TypeWitnessPlugin(
        ast.parse(CAST_NO_EVIDENCE),
        str(target),
        CAST_NO_EVIDENCE.splitlines(keepends=True),
    )
    violations = list(plugin.run())
    assert len(violations) == 1
    line, column, message, plugin_class = violations[0]
    assert (line, column) == (1, 0)
    assert message.startswith("TW000 ")
    assert plugin_class is plugin_module.TypeWitnessPlugin


def test_flake8_caches_config_per_pyproject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ast

    import typewitness.flake8_plugin as plugin_module
    import typewitness.settings as settings_module

    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    target = root / "mod.py"
    monkeypatch.chdir(root)
    reads = {"count": 0}
    original = settings_module.load_pyproject_overlay

    def counting_load(project: Any) -> Any:
        reads["count"] += 1
        return original(project)

    monkeypatch.setattr(settings_module, "load_pyproject_overlay", counting_load)
    monkeypatch.setattr(plugin_module, "load_pyproject_overlay", counting_load)
    plugin_module._clear_config_cache()
    for _ in range(3):
        list(
            plugin_module.TypeWitnessPlugin(
                ast.parse(CAST_NO_EVIDENCE),
                str(target),
                CAST_NO_EVIDENCE.splitlines(keepends=True),
            ).run()
        )
    assert reads["count"] == 1
