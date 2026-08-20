"""Project-root discovery and canonical path contracts.

The whole integration layer hangs off two guarantees:

1. the project root is the nearest ancestor directory containing ``pyproject.toml``, and
2. every path that reaches the analyzer, a reporter, or a baseline is the repo-relative
   POSIX form of that path.

Together those make fingerprints independent of how the tool was invoked.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest

from tests._integration_support import (
    CAST_NO_EVIDENCE,
    MINIMAL_PYPROJECT,
    make_root,
    write_file,
    write_project,
)
from typewitness.errors import TypeWitnessError
from typewitness.exit_codes import EXIT_USAGE_ERROR
from typewitness.project import Project, ProjectDiscoveryError, discover_project


def test_project_root_is_nearest_pyproject_ancestor(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {"pkg/sub/mod.py": CAST_NO_EVIDENCE})

    project = discover_project(root / "pkg" / "sub")

    assert project.root == root


def test_project_root_prefers_the_nearest_pyproject(tmp_path: Path) -> None:
    outer = write_project(make_root(tmp_path), {})
    inner = write_project(outer / "nested", {"mod.py": CAST_NO_EVIDENCE})

    assert discover_project(inner / "mod.py").root == inner
    assert discover_project(outer).root == outer


def test_project_discovery_accepts_a_file_start(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {"pkg/mod.py": CAST_NO_EVIDENCE})

    assert discover_project(root / "pkg" / "mod.py").root == root


def test_project_root_is_absolute_and_resolved(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {"pkg/mod.py": CAST_NO_EVIDENCE})
    link = tmp_path / "link"
    link.symlink_to(root, target_is_directory=True)

    project = discover_project(link / "pkg")

    assert project.root.is_absolute()
    assert project.root == root


def test_missing_pyproject_is_a_usage_error(tmp_path: Path) -> None:
    lonely = make_root(tmp_path, "no-project")

    with pytest.raises(ProjectDiscoveryError) as excinfo:
        discover_project(lonely)

    assert isinstance(excinfo.value, TypeWitnessError)
    assert excinfo.value.exit_code == EXIT_USAGE_ERROR
    assert "pyproject.toml" in str(excinfo.value)


def test_pyproject_path_points_at_the_anchor_file(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {})

    project = discover_project(root)

    assert project.pyproject_path == root / "pyproject.toml"
    assert project.pyproject_path.read_text(encoding="utf-8") == MINIMAL_PYPROJECT


def test_canonical_path_is_repo_relative_posix(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {"pkg/sub/mod.py": CAST_NO_EVIDENCE})
    project = discover_project(root)

    assert project.canonical(root / "pkg" / "sub" / "mod.py") == "pkg/sub/mod.py"
    assert project.canonical(root / "mod.py") == "mod.py"


def test_canonical_path_from_relative_and_absolute_input_is_identical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = write_project(make_root(tmp_path), {"pkg/mod.py": CAST_NO_EVIDENCE})
    project = discover_project(root)
    absolute = project.canonical(root / "pkg" / "mod.py")

    monkeypatch.chdir(root)
    from_root = project.canonical(Path("pkg/mod.py"))
    monkeypatch.chdir(root / "pkg")
    from_subdir = project.canonical(Path("mod.py"))
    dotted = project.canonical(Path("./mod.py"))
    parent_walk = project.canonical(Path("../pkg/mod.py"))

    assert absolute == "pkg/mod.py"
    assert from_root == absolute
    assert from_subdir == absolute
    assert dotted == absolute
    assert parent_walk == absolute


def test_canonical_path_collapses_dot_segments(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {"pkg/mod.py": CAST_NO_EVIDENCE})
    project = discover_project(root)

    noisy = root / "pkg" / ".." / "pkg" / "." / "mod.py"

    assert project.canonical(noisy) == "pkg/mod.py"


def test_canonical_path_handles_spaces_and_non_ascii(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {})
    write_file(root, "src dir/caf\u00e9/m\u00f6d.py", CAST_NO_EVIDENCE)
    project = discover_project(root)

    canonical = project.canonical(root / "src dir" / "caf\u00e9" / "m\u00f6d.py")

    assert canonical == "src dir/caf\u00e9/m\u00f6d.py"


def test_canonical_path_outside_the_root_is_a_usage_error(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {})
    outsider = write_file(make_root(tmp_path, "elsewhere"), "mod.py", CAST_NO_EVIDENCE)
    project = discover_project(root)

    with pytest.raises(TypeWitnessError) as excinfo:
        project.canonical(outsider)

    assert excinfo.value.exit_code == EXIT_USAGE_ERROR


def test_canonical_path_never_leaks_backslashes(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {"pkg/sub/mod.py": CAST_NO_EVIDENCE})
    project = discover_project(root)

    canonical = project.canonical(root / "pkg" / "sub" / "mod.py")

    assert "\\" not in canonical
    assert not canonical.startswith("/")
    assert not canonical.startswith("./")


def test_resolve_round_trips_a_canonical_path(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {"pkg/mod.py": CAST_NO_EVIDENCE})
    project = discover_project(root)

    absolute = project.resolve("pkg/mod.py")

    assert absolute == root / "pkg" / "mod.py"
    assert project.canonical(absolute) == "pkg/mod.py"


def test_project_is_frozen_and_comparable(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {"pkg/mod.py": CAST_NO_EVIDENCE})

    first = discover_project(root)
    second = discover_project(root / "pkg" / "mod.py")

    assert isinstance(first, Project)
    assert first == second
    assert hash(first) == hash(second)
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.root = root  # type: ignore[misc]


def test_discovery_stops_at_the_filesystem_root(tmp_path: Path) -> None:
    """Discovery must terminate rather than walking past ``/`` forever."""
    deep = make_root(tmp_path, "no-project") / "a" / "b" / "c"
    deep.mkdir(parents=True)

    with pytest.raises(ProjectDiscoveryError):
        discover_project(deep)


def test_canonical_paths_produce_invocation_independent_fingerprints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The canonical form is what makes relative and absolute runs agree."""
    from tests._integration_support import analyze_text

    root = write_project(make_root(tmp_path), {"pkg/mod.py": CAST_NO_EVIDENCE})
    project = discover_project(root)

    monkeypatch.chdir(root)
    relative_canonical = project.canonical(Path("pkg/mod.py"))
    monkeypatch.chdir(os.fspath(tmp_path))
    absolute_canonical = project.canonical(root / "pkg" / "mod.py")

    relative_result = analyze_text(relative_canonical, CAST_NO_EVIDENCE)
    absolute_result = analyze_text(absolute_canonical, CAST_NO_EVIDENCE)

    assert relative_result.findings
    assert [f.fingerprint for f in relative_result.findings] == [
        f.fingerprint for f in absolute_result.findings
    ]
