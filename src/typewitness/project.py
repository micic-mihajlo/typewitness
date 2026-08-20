from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from typewitness.errors import ProjectDiscoveryError, TypeWitnessError, UsageError

__all__ = ("Project", "ProjectDiscoveryError", "discover_project", "resolve_cli_project")

_MAX_NON_GIT_SEARCH_DEPTH = 25


@dataclass(frozen=True)
class Project:
    root: Path
    pyproject_path: Path

    def canonical(self, path: Path | str) -> str:
        absolute = self._resolve_under_root(path)
        relative = absolute.relative_to(self.root)
        return relative.as_posix()

    def resolve(self, canonical: str) -> Path:
        candidate = Path(canonical)
        if candidate.is_absolute():
            raise TypeWitnessError(f"path is outside the project root: {canonical}")
        resolved = (self.root / candidate).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise TypeWitnessError(f"path is outside the project root: {canonical}") from exc
        return resolved

    def _resolve_under_root(self, path: Path | str) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        else:
            candidate = candidate.resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise TypeWitnessError(f"path is outside the project root: {path}") from exc
        return candidate


def _is_git_root(path: Path) -> bool:
    git_path = path / ".git"
    return git_path.is_file() or git_path.is_dir()


def _find_git_root(start: Path) -> Optional[Path]:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    while True:
        if _is_git_root(current):
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def discover_project(start: Path | str) -> Project:
    start_path = Path(start).resolve()
    search_start = start_path.parent if start_path.is_file() else start_path

    git_root = _find_git_root(search_start)
    if git_root is not None:
        current = search_start
        while True:
            pyproject = current / "pyproject.toml"
            if pyproject.is_file():
                return Project(root=current.resolve(), pyproject_path=pyproject.resolve())
            if current == git_root:
                break
            parent = current.parent
            if parent == current:
                break
            current = parent.resolve()
        raise ProjectDiscoveryError(
            f"no pyproject.toml found at or below the git root for {os.fspath(start)}"
        )

    current = search_start
    previous: Path | None = None
    depth = 0
    while current != previous and depth <= _MAX_NON_GIT_SEARCH_DEPTH:
        pyproject = current / "pyproject.toml"
        if pyproject.is_file():
            return Project(root=current.resolve(), pyproject_path=pyproject.resolve())
        previous = current
        parent = current.parent
        if parent == current:
            break
        current = parent.resolve()
        depth += 1

    raise ProjectDiscoveryError(f"no pyproject.toml found in any ancestor of {os.fspath(start)}")


def resolve_cli_project(
    *,
    cwd: Path,
    config_path: Optional[Path | str],
    input_paths: Sequence[str],
) -> Project:
    if config_path is not None:
        candidate = Path(config_path)
        if candidate.is_file():
            if candidate.name != "pyproject.toml":
                raise UsageError("--config must point to pyproject.toml")
            resolved = candidate.resolve()
            return Project(root=resolved.parent, pyproject_path=resolved)
        return discover_project(candidate)

    try:
        return discover_project(cwd)
    except ProjectDiscoveryError:
        pass

    if not input_paths:
        return discover_project(cwd)

    roots: set[Path] = set()
    last_project: Optional[Project] = None
    for raw in input_paths:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = (cwd / candidate).resolve()
        else:
            candidate = candidate.resolve()
        project = discover_project(candidate)
        roots.add(project.root)
        last_project = project

    if len(roots) > 1:
        raise UsageError("input paths span multiple project roots")

    assert last_project is not None
    return last_project
