"""Distribution contract: metadata, entry points, and a real installed console script.

The pyproject assertions need no production module, so they fail as assertions while the
integration layer is unimplemented. The wheel test builds offline and installs into a
throwaway virtualenv with ``--no-index --no-deps``; it skips rather than reaching the
network if a wheel cannot be produced from the local cache.

Because ``--no-deps`` omits the conditional ``tomli`` dependency, this file also pins the
lazy-import property: ``typewitness --version`` must work without a TOML parser, and a run
that genuinely needs one must fail with the usage exit code and name the missing package.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path
from typing import Dict, List

import pytest

from tests._integration_support import (
    CAST_NO_EVIDENCE,
    REPO_ROOT,
    build_wheel,
    make_root,
    make_venv,
    run_isolated,
    uv_available,
    venv_bin,
    write_project,
)

PYPROJECT_TEXT = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

REPOSITORY_URL = "https://github.com/micic-mihajlo/typewitness"


def _unquote(raw: str) -> str:
    """Strip one layer of TOML string quoting, leaving nested quotes intact."""
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _section(name: str) -> List[str]:
    """Return the raw lines of a pyproject table without needing a TOML parser."""
    lines: List[str] = []
    inside = False
    for raw in PYPROJECT_TEXT.splitlines():
        stripped = raw.strip()
        if stripped.startswith("["):
            inside = stripped == f"[{name}]"
            continue
        if inside and stripped:
            lines.append(stripped)
    return lines


def _entries(name: str) -> Dict[str, str]:
    entries: Dict[str, str] = {}
    for line in _section(name):
        key, separator, value = line.partition("=")
        if separator:
            entries[_unquote(key)] = _unquote(value)
    return entries


# ------------------------------------------------------------------------- metadata


def test_distribution_name_is_typewitness() -> None:
    assert _entries("project")["name"] == "typewitness"


def test_repository_urls_point_at_the_chosen_github_repository() -> None:
    urls = _entries("project.urls")

    assert urls, "[project.urls] is missing"
    assert urls.get("Homepage") == REPOSITORY_URL
    assert urls.get("Repository") == REPOSITORY_URL


def test_tomli_is_a_conditional_dependency_below_python_311() -> None:
    """The core stays dependency-free on 3.11+, where ``tomllib`` is in the stdlib."""
    dependencies = "\n".join(_section("project"))
    match = re.search(r"dependencies\s*=\s*\[(?P<body>[^\]]*)\]", dependencies, re.DOTALL)

    assert match is not None, "[project].dependencies is missing"
    requirements = [_unquote(item) for item in match.group("body").split(",")]
    requirements = [item for item in requirements if item]
    assert len(requirements) == 1, requirements
    requirement = requirements[0]
    assert requirement.startswith("tomli")
    assert ";" in requirement, "the tomli dependency must be conditional"
    marker = requirement.split(";", 1)[1].strip().replace("'", '"')
    # Either PEP 508 spelling is accepted; both mean "only below 3.11".
    assert marker in ('python_version < "3.11"', 'python_full_version < "3.11"'), marker


def test_console_script_is_declared() -> None:
    scripts = _entries("project.scripts")

    assert scripts.get("typewitness") == "typewitness.cli:main"


def test_flake8_entry_point_is_declared() -> None:
    entry_points = _entries('project.entry-points."flake8.extension"')

    assert entry_points.get("TW") == "typewitness.flake8_plugin:TypeWitnessPlugin"


def test_tool_version_matches_the_distribution_version() -> None:
    from typewitness.report import TOOL_VERSION

    assert _entries("project")["version"] == TOOL_VERSION


def test_requires_python_still_covers_39_through_314() -> None:
    requires = _entries("project")["requires-python"]

    assert requires == ">=3.9"


# ------------------------------------------------------------------------ wheel build


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not uv_available():
        pytest.skip("uv is not installed; cannot build a wheel offline")
    built = build_wheel(tmp_path_factory.mktemp("dist"))
    if built is None:
        pytest.skip("offline wheel build unavailable (build backend not cached)")
    return built


def test_wheel_filename_uses_the_distribution_name(wheel: Path) -> None:
    assert wheel.name.startswith("typewitness-")
    assert wheel.name.endswith(".whl")


def test_wheel_ships_the_package_and_type_marker(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())

    assert "typewitness/__init__.py" in names
    assert "typewitness/py.typed" in names
    assert "typewitness/cli.py" in names
    assert "typewitness/report.py" in names


def test_wheel_declares_the_console_script(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        entry_points = [name for name in archive.namelist() if name.endswith("entry_points.txt")]
        assert entry_points, "wheel has no entry_points.txt"
        text = archive.read(entry_points[0]).decode("utf-8")

    assert "[console_scripts]" in text
    assert "typewitness = typewitness.cli:main" in text
    assert "[flake8.extension]" in text


# --------------------------------------------------------- installed console script


@pytest.fixture(scope="module")
def installed_venv(wheel: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    home = tmp_path_factory.mktemp("home")
    venv_dir = home / "venv"
    interpreter = make_venv(venv_dir)
    if interpreter is None:
        pytest.skip("could not create an isolated virtualenv")
    pip = venv_bin(venv_dir, "pip")
    if not pip.exists():
        pytest.skip("isolated virtualenv has no pip")
    completed = run_isolated(
        pip,
        (
            "install",
            "--no-index",
            "--no-deps",
            "--disable-pip-version-check",
            "--no-cache-dir",
            str(wheel),
        ),
        cwd=home,
        home=home,
    )
    if completed.returncode != 0:
        pytest.skip(f"offline wheel install failed: {completed.stderr}")
    return venv_dir


def test_console_script_is_installed(installed_venv: Path) -> None:
    executable = venv_bin(installed_venv, "typewitness")

    assert executable.exists()


def test_installed_console_script_reports_its_version(
    installed_venv: Path,
    tmp_path: Path,
) -> None:
    """``--version`` must not need the conditional TOML parser."""
    from typewitness.report import TOOL_VERSION

    executable = venv_bin(installed_venv, "typewitness")
    home = make_root(tmp_path, "home")

    completed = run_isolated(executable, ("--version",), cwd=home, home=home)

    assert completed.returncode == 0, completed.stderr
    assert TOOL_VERSION in completed.stdout


def test_installed_console_script_prints_help(installed_venv: Path, tmp_path: Path) -> None:
    executable = venv_bin(installed_venv, "typewitness")
    home = make_root(tmp_path, "home")

    completed = run_isolated(executable, ("--help",), cwd=home, home=home)

    assert completed.returncode == 0, completed.stderr
    assert "--diff-ref" in completed.stdout


def test_installed_console_script_does_not_import_the_repository_checkout(
    installed_venv: Path,
    tmp_path: Path,
) -> None:
    interpreter = venv_bin(installed_venv, "python")
    home = make_root(tmp_path, "home")
    script = "import typewitness, sys; sys.stdout.write(typewitness.__file__)"

    completed = run_isolated(interpreter, ("-c", script), cwd=home, home=home)

    assert completed.returncode == 0, completed.stderr
    assert str(REPO_ROOT / "src") not in completed.stdout


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="without tomli installed a run cannot parse pyproject below 3.11",
)
def test_installed_console_script_analyzes_a_temporary_project(
    installed_venv: Path,
    tmp_path: Path,
) -> None:
    executable = venv_bin(installed_venv, "typewitness")
    home = make_root(tmp_path, "home")
    root = write_project(make_root(tmp_path, "sample"), {"pkg/mod.py": CAST_NO_EVIDENCE})

    findings_run = run_isolated(executable, ("--format", "json"), cwd=root, home=home)

    assert findings_run.returncode == 1, findings_run.stderr
    assert '"pkg/mod.py"' in findings_run.stdout


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="without tomli installed a run cannot parse pyproject below 3.11",
)
def test_installed_console_script_exits_zero_on_a_clean_project(
    installed_venv: Path,
    tmp_path: Path,
) -> None:
    executable = venv_bin(installed_venv, "typewitness")
    home = make_root(tmp_path, "home")
    root = write_project(make_root(tmp_path, "clean"), {"pkg/mod.py": "VALUE = 1\n"})

    completed = run_isolated(executable, (), cwd=root, home=home)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""


@pytest.mark.skipif(
    sys.version_info >= (3, 11),
    reason="tomllib is in the stdlib from 3.11 onwards",
)
def test_missing_tomli_below_311_fails_loudly_and_names_the_package(
    installed_venv: Path,
    tmp_path: Path,
) -> None:
    """The conditional dependency is real: without it, say so instead of guessing config."""
    executable = venv_bin(installed_venv, "typewitness")
    home = make_root(tmp_path, "home")
    root = write_project(make_root(tmp_path, "sample"), {"pkg/mod.py": CAST_NO_EVIDENCE})

    completed = run_isolated(executable, ("--format", "json"), cwd=root, home=home)

    assert completed.returncode == 3, completed.stdout
    assert "tomli" in completed.stderr
