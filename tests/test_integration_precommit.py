"""Pre-commit hook manifest contract and filenames-as-input behaviour.

``.pre-commit-hooks.yaml`` is a public interface: consumers pin it by repo and rev, so its
id, entry, and language cannot change without breaking their config. The manifest is
deliberately restricted to flat scalar and inline-list values, which is why the tiny parser
below is sufficient — and why a manifest that needs more than that should be reconsidered.

The manifest tests need no production module, so they fail as assertions rather than
collection errors while the integration layer is unimplemented.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Union

import pytest

from tests._integration_support import (
    CAST_NO_EVIDENCE,
    CLEAN_SOURCE,
    REPO_ROOT,
    make_root,
    write_project,
)

MANIFEST_PATH = REPO_ROOT / ".pre-commit-hooks.yaml"

Scalar = Union[str, bool, List[str]]


def _parse_scalar(raw: str) -> Scalar:
    value = raw.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("'\"") for item in inner.split(",")]
    if value in ("true", "false"):
        return value == "true"
    return value.strip("'\"")


def _parse_manifest(text: str) -> List[Dict[str, Scalar]]:
    """Parse the flat ``- key: value`` subset of YAML that this manifest is limited to."""
    hooks: List[Dict[str, Scalar]] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line.startswith("- "):
            hooks.append({})
            line = "  " + line[2:]
        if not line.startswith("  "):
            raise AssertionError(f"unsupported manifest line: {raw_line!r}")
        if not hooks:
            raise AssertionError(f"manifest entry outside a hook: {raw_line!r}")
        key, separator, value = line.strip().partition(":")
        if not separator:
            raise AssertionError(f"unsupported manifest line: {raw_line!r}")
        hooks[-1][key.strip()] = _parse_scalar(value)
    return hooks


def _hooks() -> List[Dict[str, Scalar]]:
    assert MANIFEST_PATH.is_file(), f"{MANIFEST_PATH.name} is missing from the repository root"
    return _parse_manifest(MANIFEST_PATH.read_text(encoding="utf-8"))


def _typewitness_hook() -> Dict[str, Scalar]:
    matching = [hook for hook in _hooks() if hook.get("id") == "typewitness"]
    assert len(matching) == 1, "exactly one hook with id 'typewitness' is expected"
    return matching[0]


def test_manifest_exists_at_the_repository_root() -> None:
    assert MANIFEST_PATH.is_file()


def test_manifest_is_a_list_of_hooks() -> None:
    hooks = _hooks()

    assert hooks
    assert all(isinstance(hook, dict) for hook in hooks)
    assert all("id" in hook for hook in hooks)


def test_hook_ids_are_unique() -> None:
    ids = [hook["id"] for hook in _hooks()]

    assert len(ids) == len(set(ids))


def test_hook_declares_the_console_entry_point() -> None:
    hook = _typewitness_hook()

    assert hook["entry"] == "typewitness"
    assert hook["language"] == "python"


def test_hook_has_a_human_readable_name_and_description() -> None:
    hook = _typewitness_hook()

    assert isinstance(hook["name"], str) and hook["name"].strip()
    assert isinstance(hook["description"], str) and hook["description"].strip()


def test_hook_targets_python_sources() -> None:
    hook = _typewitness_hook()

    assert hook.get("types_or") == ["python", "pyi"]


def test_hook_receives_filenames() -> None:
    hook = _typewitness_hook()

    assert hook["pass_filenames"] is True


def test_hook_does_not_require_serial_execution() -> None:
    """Analysis is per-file and side-effect free, so pre-commit may fan out."""
    hook = _typewitness_hook()

    assert hook["require_serial"] is False


def test_hook_inserts_end_of_options_before_filenames() -> None:
    hook = _typewitness_hook()

    assert hook.get("args") == ["--"]


def test_hook_declares_no_default_git_mode_arguments() -> None:
    """Git scoping stays explicit; a hook default would silently hide findings."""
    hook = _typewitness_hook()
    args = hook.get("args", [])

    assert isinstance(args, list)
    for forbidden in ("--staged", "--worktree", "--diff-ref"):
        assert forbidden not in args


def test_hook_declares_a_minimum_pre_commit_version() -> None:
    hook = _typewitness_hook()

    assert isinstance(hook["minimum_pre_commit_version"], str)
    assert hook["minimum_pre_commit_version"].count(".") >= 1


def test_manifest_keys_are_all_recognized() -> None:
    allowed = {
        "id",
        "name",
        "description",
        "entry",
        "language",
        "types",
        "types_or",
        "files",
        "exclude",
        "args",
        "pass_filenames",
        "require_serial",
        "minimum_pre_commit_version",
        "stages",
    }

    for hook in _hooks():
        assert set(hook) <= allowed, set(hook) - allowed


# ------------------------------------------------------- filenames-as-input behaviour


def _run_cli(argv: List[str]) -> int:
    from typewitness.cli import main

    return main(argv)


def test_named_filenames_limit_the_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(
        make_root(tmp_path),
        {"targeted.py": CAST_NO_EVIDENCE, "untouched.py": CAST_NO_EVIDENCE},
    )
    monkeypatch.chdir(root)

    exit_code = _run_cli(["--format", "json", "targeted.py"])

    payload = json.loads(capsys.readouterr().out)
    paths = {entry["path"] for entry in payload["findings"]}
    assert exit_code == 1
    assert paths == {"targeted.py"}


def test_multiple_filenames_are_all_analyzed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(
        make_root(tmp_path),
        {"a.py": CAST_NO_EVIDENCE, "pkg/b.py": CAST_NO_EVIDENCE, "c.py": CLEAN_SOURCE},
    )
    monkeypatch.chdir(root)

    exit_code = _run_cli(["--format", "json", "a.py", "pkg/b.py", "c.py"])

    payload = json.loads(capsys.readouterr().out)
    paths = sorted({entry["path"] for entry in payload["findings"]})
    assert exit_code == 1
    assert paths == ["a.py", "pkg/b.py"]


def test_filenames_are_accepted_as_absolute_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """pre-commit passes repo-relative paths, but editors pass absolute ones."""
    root = write_project(make_root(tmp_path), {"pkg/mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)

    exit_code = _run_cli(["--format", "json", str((root / "pkg" / "mod.py").resolve())])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert {entry["path"] for entry in payload["findings"]} == {"pkg/mod.py"}


def test_clean_named_files_exit_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(
        make_root(tmp_path),
        {"clean.py": CLEAN_SOURCE, "dirty.py": CAST_NO_EVIDENCE},
    )
    monkeypatch.chdir(root)

    exit_code = _run_cli(["clean.py"])

    assert exit_code == 0
    assert capsys.readouterr().out == ""


def test_no_filenames_falls_back_to_the_project_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"pkg/mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)

    exit_code = _run_cli(["--format", "json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert {entry["path"] for entry in payload["findings"]} == {"pkg/mod.py"}


def test_named_filenames_are_skipped_when_excluded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"generated/mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)

    walked = _run_cli(["--exclude", "generated"])
    capsys.readouterr()
    explicit = _run_cli(["--exclude", "generated", "generated/mod.py"])
    capsys.readouterr()

    assert walked == 0
    assert explicit == 0


def test_repeated_filenames_are_analyzed_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)

    once = _run_cli(["--format", "json", "mod.py"])
    single_payload: Dict[str, Any] = json.loads(capsys.readouterr().out)
    twice = _run_cli(["--format", "json", "mod.py", "mod.py", "./mod.py"])
    repeated_payload: Dict[str, Any] = json.loads(capsys.readouterr().out)

    assert once == twice == 1
    assert repeated_payload["findings"] == single_payload["findings"]
