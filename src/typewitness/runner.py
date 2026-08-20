from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

from typewitness.baseline import apply_baseline, load_baseline, write_baseline
from typewitness.discovery import discover_paths, read_source
from typewitness.engine import analyze
from typewitness.git import GitSelection, changed_lines, filter_findings_to_changed_lines
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
    file_paths = discover_paths(
        resolved_project,
        tuple(Path(p) for p in paths),
        settings.exclude,
    )

    findings: list[Finding] = []
    errors: list[AnalysisError] = []

    config = settings.to_config()
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

    if git_selection is not None:
        changed = changed_lines(
            resolved_project,
            git_selection,
            max_file_bytes=settings.max_file_bytes,
        )
        errors_tuple = errors_tuple + changed.errors
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
