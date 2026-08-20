from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple

from typewitness.discovery import is_path_excluded
from typewitness.engine import analyze
from typewitness.errors import ConfigError, FilesystemError, ProjectDiscoveryError, TypeWitnessError
from typewitness.models import Config, SourceFile
from typewitness.project import Project, discover_project
from typewitness.report import TOOL_NAME, TOOL_VERSION
from typewitness.settings import load_pyproject_overlay, resolve_settings

Violation = Tuple[int, int, str, type]

CONFIG_DIAGNOSTIC_CODE = "TW000"

__all__ = ("TypeWitnessPlugin", "Violation", "analyze", "CONFIG_DIAGNOSTIC_CODE")

_ConfigCacheEntry = Tuple[Optional[Config], Optional[str], Tuple[str, ...]]
_config_cache: dict[tuple[int, int], _ConfigCacheEntry] = {}


def _clear_config_cache() -> None:
    _config_cache.clear()


def _config_for_project(
    project: Project,
) -> Tuple[Optional[Config], Optional[str], Tuple[str, ...]]:
    stat_result = project.pyproject_path.stat()
    cache_key = (stat_result.st_dev, stat_result.st_ino)
    cached = _config_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        overlay = load_pyproject_overlay(project)
        settings = resolve_settings(overlay)
        entry: _ConfigCacheEntry = (settings.to_config(), None, settings.exclude)
    except ConfigError as exc:
        entry = (None, str(exc), ())
    _config_cache[cache_key] = entry
    return entry


class TypeWitnessPlugin:
    name = TOOL_NAME
    version = TOOL_VERSION

    def __init__(self, tree: Optional[ast.AST], filename: str, lines: Sequence[str]) -> None:
        self._tree = tree
        self._filename = filename
        self._lines = lines
        self._ran = False

    def _project_for_filename(self) -> Optional[Project]:
        if self._filename == "-":
            return None
        candidate = Path(self._filename)
        if candidate.is_symlink():
            return None
        if not candidate.is_absolute():
            try:
                return discover_project(Path.cwd())
            except ProjectDiscoveryError:
                return None
        try:
            return discover_project(candidate)
        except ProjectDiscoveryError:
            return None

    def _resolve_source_path(self) -> Path:
        if self._filename == "-":
            return Path("stdin")

        candidate = Path(self._filename)
        project = self._project_for_filename()
        if project is None:
            return candidate if not candidate.is_absolute() else Path(candidate.name)

        absolute = candidate if candidate.is_absolute() else (Path.cwd() / candidate).resolve()
        return Path(project.canonical(absolute))

    def _emit_config_error(self, message: str) -> Iterator[Violation]:
        yield (1, 0, f"{CONFIG_DIAGNOSTIC_CODE} {message}", TypeWitnessPlugin)

    def run(self) -> Iterator[Violation]:
        if self._ran:
            return
        self._ran = True

        text = "".join(self._lines)
        if not text and not self._lines:
            return

        if self._tree is None:
            return

        if self._filename != "-":
            candidate = Path(self._filename)
            if candidate.is_symlink():
                yield from self._emit_config_error(
                    f"symlink inputs are not supported: {self._filename}"
                )
                return

        project = self._project_for_filename()
        config: Config
        exclude: Tuple[str, ...] = ()
        if project is None:
            config = Config()
        else:
            try:
                loaded_config, config_error, exclude = _config_for_project(project)
            except (FilesystemError, ValueError) as exc:
                yield from self._emit_config_error(str(exc))
                return
            if config_error is not None:
                yield from self._emit_config_error(config_error)
                return
            assert loaded_config is not None
            config = loaded_config

        try:
            source_path = self._resolve_source_path()
        except (FilesystemError, ValueError, TypeWitnessError) as exc:
            yield from self._emit_config_error(str(exc))
            return
        if exclude and is_path_excluded(source_path.as_posix(), exclude):
            return

        try:
            source = SourceFile(path=source_path, text=text)
            result = analyze(source, config)
        except (FilesystemError, ValueError, TypeWitnessError) as exc:
            yield from self._emit_config_error(str(exc))
            return

        violations: List[Violation] = []
        for finding in result.findings:
            violations.append(
                (
                    finding.range.start.line,
                    finding.range.start.column,
                    f"{finding.code} {finding.message}",
                    TypeWitnessPlugin,
                )
            )

        violations.sort(key=lambda item: (item[0], item[1], item[2].split(" ", 1)[0]))
        yield from violations
