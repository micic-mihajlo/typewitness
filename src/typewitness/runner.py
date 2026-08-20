from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

from typewitness.baseline import apply_baseline, load_baseline, write_baseline
from typewitness.discovery import (
    _is_python_file as is_python_file,
)
from typewitness.discovery import (
    _resolve_input as resolve_discover_input,
)
from typewitness.discovery import (
    discover_paths,
    is_path_excluded,
    read_source,
)
from typewitness.engine import analyze
from typewitness.errors import FilesystemError
from typewitness.git import (
    ChangedLinesResult,
    GitSelection,
    changed_lines,
    filter_findings_to_changed_lines,
)
from typewitness.models import AnalysisError, Finding
from typewitness.project import Project, discover_project
from typewitness.settings import Settings, SettingsOverlay, load_pyproject_overlay, resolve_settings

__all__ = (
    "RunResult",
    "analyze",
    "build_settings_from_project",
    "run_analysis",
)


@dataclass(frozen=True)
class RunResult:
    findings: Tuple[Finding, ...]
    errors: Tuple[AnalysisError, ...]


def _changed_python_lines(changed: ChangedLinesResult) -> dict[str, frozenset[int]]:
    return {
        path: lines for path, lines in changed.lines.items() if lines and is_python_file(Path(path))
    }


def _validate_git_scope_input(project: Project, raw: Path | str) -> tuple[Path, bool]:
    absolute, is_symlink_input = resolve_discover_input(project, raw)
    if is_symlink_input:
        raise FilesystemError(f"symlink inputs are not supported: {raw}")
    if not absolute.is_file() and not absolute.is_dir():
        raise FilesystemError(f"input path does not exist: {raw}")
    return absolute, absolute.is_dir()


def _canonical_in_scope(canonical: str, scope: str, *, scope_is_dir: bool) -> bool:
    if scope_is_dir:
        if scope in {"", "."}:
            return True
        return canonical == scope or canonical.startswith(f"{scope}/")
    return canonical == scope


def _analyzable_git_path(project: Project, canonical: str) -> Optional[Path]:
    resolved = project.resolve(canonical)
    if resolved.is_symlink() or not resolved.is_file():
        return None
    return resolved


def _git_analysis_paths(
    project: Project,
    paths: Sequence[str],
    excludes: Sequence[str],
    changed: ChangedLinesResult,
) -> Tuple[Path, ...]:
    changed_python = _changed_python_lines(changed)
    if paths:
        selected: list[Path] = []
        seen: set[str] = set()
        for raw in paths:
            absolute, scope_is_dir = _validate_git_scope_input(project, raw)
            scope_canonical = project.canonical(absolute)
            for canonical in sorted(changed_python):
                if is_path_excluded(canonical, excludes):
                    continue
                if not _canonical_in_scope(
                    canonical,
                    scope_canonical,
                    scope_is_dir=scope_is_dir,
                ):
                    continue
                if canonical in seen:
                    continue
                resolved = _analyzable_git_path(project, canonical)
                if resolved is None:
                    continue
                seen.add(canonical)
                selected.append(resolved)
        return tuple(selected)

    resolved_paths: list[Path] = []
    for canonical in sorted(changed_python):
        if is_path_excluded(canonical, excludes):
            continue
        resolved = _analyzable_git_path(project, canonical)
        if resolved is None:
            continue
        resolved_paths.append(resolved)
    return tuple(resolved_paths)


def run_analysis(
    *,
    paths: Sequence[str],
    settings: Settings,
    project: Optional[Project] = None,
    git_selection: Optional[GitSelection] = None,
    baseline_path: Optional[Path] = None,
    write_baseline_path: Optional[Path] = None,
) -> RunResult:
    resolved_project = project or discover_project(Path.cwd())
    config = settings.to_config()
    findings: list[Finding] = []
    errors: list[AnalysisError] = []

    if git_selection is not None:
        changed = changed_lines(
            resolved_project,
            git_selection,
            max_file_bytes=settings.max_file_bytes,
        )
        errors.extend(changed.errors)
        file_paths = _git_analysis_paths(
            resolved_project,
            paths,
            settings.exclude,
            changed,
        )
    else:
        changed = None
        file_paths = discover_paths(
            resolved_project,
            tuple(Path(p) for p in paths),
            settings.exclude,
        )

    for absolute in file_paths:
        read_result = read_source(
            resolved_project,
            absolute,
            max_file_bytes=settings.max_file_bytes,
        )
        if read_result.error is not None:
            errors.append(read_result.error)
            continue
        assert read_result.source is not None
        result = analyze(read_result.source, config)
        findings.extend(result.findings)
        errors.extend(result.errors)

    findings_tuple = tuple(findings)
    errors_tuple = tuple(errors)

    if changed is not None:
        findings_tuple = filter_findings_to_changed_lines(findings_tuple, changed.lines)

    if write_baseline_path is not None:
        if errors_tuple:
            return RunResult(findings=findings_tuple, errors=errors_tuple)
        write_baseline(resolved_project.root, write_baseline_path, findings_tuple)
        return RunResult(findings=(), errors=())

    if baseline_path is not None:
        baseline = load_baseline(baseline_path)
        findings_tuple = apply_baseline(findings_tuple, baseline)

    return RunResult(findings=findings_tuple, errors=errors_tuple)


def build_settings_from_project(
    start: Path,
    cli_overlay: SettingsOverlay,
) -> Tuple[Project, Settings]:
    project = discover_project(start)
    pyproject_overlay = load_pyproject_overlay(project)
    settings = resolve_settings(pyproject_overlay, cli_overlay)
    return project, settings
