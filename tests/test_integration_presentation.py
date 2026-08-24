from __future__ import annotations

import os
import pty
import re
import select
import subprocess
import sys
from pathlib import Path

import pytest

from tests._integration_support import (
    CAST_NO_EVIDENCE,
    REPO_ROOT,
    analyze_text,
    make_root,
    scrubbed_env,
    write_project,
)
from typewitness.cli import main
from typewitness.presentation import PR_COMMENT_MARKER
from typewitness.report import Report, render_text

ANSI = re.compile("\x1b\\[")


def _read_master_output(master_fd: int) -> str:
    chunks: list[bytes] = []
    while True:
        ready, _, _ = select.select([master_fd], [], [], 0.2)
        if not ready:
            break
        chunk = os.read(master_fd, 4096)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8")


def test_cli_pretty_format(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)
    assert main(["--format", "pretty"]) == 1
    out = capsys.readouterr().out
    assert out.startswith("TypeWitness found 1 finding in 1 file\n")
    assert "TW002" in out
    assert not ANSI.search(out)


def test_cli_github_format(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)
    assert main(["--format", "github"]) == 1
    out = capsys.readouterr().out
    assert out.startswith(f"{PR_COMMENT_MARKER}\n")
    assert "| [TW002]" in out


def test_cli_defaults_to_pretty_on_tty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    assert main([]) == 1
    out = capsys.readouterr().out
    assert out.startswith("TypeWitness found 1 finding in 1 file\n")
    assert "TW002" in out


def test_cli_defaults_to_text_when_stdout_is_not_tty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert main([]) == 1
    finding = analyze_text("mod.py", CAST_NO_EVIDENCE).findings[0]
    expected = (
        f"mod.py:{finding.range.start.line}:{finding.range.start.column + 1}: "
        f"{finding.code} {finding.message}"
    )
    assert capsys.readouterr().out.splitlines() == [expected]


def test_cli_defaults_to_pretty_on_pty(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    master_fd, slave_fd = pty.openpty()
    env = scrubbed_env(root.parent)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    proc = subprocess.Popen(
        [sys.executable, "-m", "typewitness", "mod.py"],
        cwd=str(root),
        stdout=slave_fd,
        stderr=slave_fd,
        env=env,
    )
    os.close(slave_fd)
    output = _read_master_output(master_fd)
    os.close(master_fd)
    proc.wait()
    assert proc.returncode == 1
    normalized = output.replace("\r\n", "\n")
    assert "TypeWitness found 1 finding in 1 file" in normalized
    assert "TW002" in normalized
    assert "value = cast(int, 1)" in normalized


def test_cli_text_format_still_one_line_on_pty(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    finding = analyze_text("mod.py", CAST_NO_EVIDENCE).findings[0]
    expected = render_text(Report(findings=(finding,), errors=()))
    master_fd, slave_fd = pty.openpty()
    env = scrubbed_env(root.parent)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    proc = subprocess.Popen(
        [sys.executable, "-m", "typewitness", "--format", "text", "mod.py"],
        cwd=str(root),
        stdout=slave_fd,
        stderr=slave_fd,
        env=env,
    )
    os.close(slave_fd)
    output = _read_master_output(master_fd)
    os.close(master_fd)
    proc.wait()
    assert proc.returncode == 1
    assert output.replace("\r\n", "\n") == expected


def test_cli_github_links_from_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    monkeypatch.chdir(root)
    monkeypatch.setenv("TYPEWITNESS_GITHUB_REPOSITORY", "org/repo")
    monkeypatch.setenv("TYPEWITNESS_GITHUB_SHA", "abc123")
    assert main(["--format", "github"]) == 1
    assert "https://github.com/org/repo/blob/abc123/mod.py#L3" in capsys.readouterr().out
