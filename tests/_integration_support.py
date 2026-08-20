"""Shared, dependency-free helpers for the v0.1 integration-layer test suite.

Everything here is stdlib plus the already-shipped ``typewitness`` core, so this module
imports cleanly even while the integration modules under test do not exist yet.

Hard rules encoded here:

* no network access,
* no reliance on the developer's user config, environment, or credentials,
* every filesystem artifact lives under a pytest-provided temporary directory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple

from typewitness import AnalysisResult, Config, SourceFile, analyze

REPO_ROOT = Path(__file__).resolve().parents[1]

MINIMAL_PYPROJECT = '[project]\nname = "sample"\nversion = "0.0.0"\n'

# Fixtures with known core behaviour. Line/column expectations are derived from these
# constants at assert time via ``analyze_text`` rather than hardcoded.
CAST_NO_EVIDENCE = "from typing import cast\n\nvalue = cast(int, 1)\n"
CAST_WITH_EVIDENCE = "from typing import cast\n\nvalue = cast(int, 1)  # SAFETY: reviewed owner\n"
CHAINED_CAST = "from typing import cast\n\nvalue = cast(int, cast(str, 1))\n"
UNPARSEABLE_SOURCE = "def broken(:\n    pass\n"
CLEAN_SOURCE = "VALUE = 1\n"

COMMITTER_ARGS: Tuple[str, ...] = (
    "-c",
    "user.name=TypeWitness Test",
    "-c",
    "user.email=test@example.invalid",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "core.quotepath=false",
)


def scrubbed_env(home: Path) -> Dict[str, str]:
    """A minimal subprocess environment: no user config, no credentials, no ambient state."""
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "TMPDIR": str(home),
        "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "NO_COLOR": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "",
    }


def git_available() -> bool:
    return shutil.which("git") is not None


def uv_available() -> bool:
    return shutil.which("uv") is not None


def make_root(tmp_path: Path, name: str = "project") -> Path:
    """Create a resolved project directory.

    ``tmp_path`` is not resolved on macOS (``/var`` is a symlink to ``/private/var``), so
    every test that compares against a discovered project root needs the resolved form.
    """
    root = (tmp_path / name).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def write_file(root: Path, relative: str, text: str, *, encoding: str = "utf-8") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)
    return path


def write_bytes(root: Path, relative: str, payload: bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def write_project(
    root: Path,
    files: Mapping[str, str],
    *,
    pyproject: Optional[str] = MINIMAL_PYPROJECT,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    if pyproject is not None:
        (root / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    for relative, text in files.items():
        write_file(root, relative, text)
    return root


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *args),
        cwd=str(repo),
        env=scrubbed_env(repo.parent),
        capture_output=True,
        text=True,
        check=False,
    )


def git_checked(repo: Path, *args: str) -> str:
    completed = run_git(repo, *args)
    if completed.returncode != 0:
        joined = " ".join(args)
        raise AssertionError(f"git {joined} failed ({completed.returncode}): {completed.stderr}")
    return completed.stdout


def init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    git_checked(repo, "-c", "init.defaultBranch=main", "init", "-q")


def commit_all(repo: Path, message: str) -> str:
    git_checked(repo, "add", "-A")
    git_checked(repo, *COMMITTER_ARGS, "commit", "-q", "-m", message)
    return git_checked(repo, "rev-parse", "HEAD").strip()


def stage(repo: Path, *relatives: str) -> None:
    git_checked(repo, "add", "--", *relatives)


def analyze_text(
    canonical_path: str,
    text: str,
    *,
    select: Optional[frozenset[str]] = None,
) -> AnalysisResult:
    """Analyze in-process using the canonical repo-relative path the CLI must also use."""
    config = Config(select=select, ignore=frozenset())
    return analyze(SourceFile(path=Path(canonical_path), text=text), config=config)


def fingerprints_of(result: AnalysisResult) -> Tuple[Tuple[str, str], ...]:
    return tuple(sorted((finding.code, finding.fingerprint) for finding in result.findings))


def build_wheel(out_dir: Path) -> Optional[Path]:
    """Build a wheel offline. Returns ``None`` when the build cannot run without network."""
    if not uv_available():
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ("uv", "build", "--offline", "--wheel", "--out-dir", str(out_dir)),
        cwd=str(REPO_ROOT),
        env=scrubbed_env(out_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    wheels = sorted(out_dir.glob("*.whl"))
    return wheels[0] if wheels else None


def make_venv(venv_dir: Path) -> Optional[Path]:
    """Create an isolated venv with pip from ensurepip. Returns the interpreter path."""
    completed = subprocess.run(
        (sys.executable, "-m", "venv", str(venv_dir)),
        env=scrubbed_env(venv_dir.parent),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    interpreter = venv_bin(venv_dir, "python")
    return interpreter if interpreter.exists() else None


def venv_bin(venv_dir: Path, name: str) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / (name + ".exe")
    return venv_dir / "bin" / name


def run_isolated(
    executable: Path,
    args: Sequence[str],
    *,
    cwd: Path,
    home: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (str(executable), *args),
        cwd=str(cwd),
        env=scrubbed_env(home),
        capture_output=True,
        text=True,
        check=False,
    )
