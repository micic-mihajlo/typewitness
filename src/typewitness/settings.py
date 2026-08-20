from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import Any, FrozenSet, Optional, Tuple

from typewitness.discovery import DEFAULT_MAX_FILE_BYTES, MAX_MAX_FILE_BYTES
from typewitness.errors import ConfigError
from typewitness.models import DEFAULT_RULESET, VALID_RULE_CODES, Config
from typewitness.project import Project

if sys.version_info >= (3, 11):
    TOML_BACKEND = "tomllib"
else:
    TOML_BACKEND = "tomli"

SUPPORTED_OUTPUT_FORMATS = frozenset({"text", "json", "sarif", "pretty", "markdown"})
MAX_PYPROJECT_BYTES = 1_048_576
RULE_CODE_PATTERN = re.compile(r"^TW\d{3}$")
SUPPORTED_KEYS = frozenset(
    {"select", "ignore", "exclude", "output-format", "baseline", "max-file-bytes"}
)


def import_toml_module() -> Any:
    if TOML_BACKEND == "tomllib":
        import tomllib  # type: ignore[import-not-found]

        return tomllib
    try:
        import tomli
    except ImportError as exc:
        raise ConfigError(
            "tomli is required to parse pyproject.toml on Python < 3.11; "
            "install typewitness with its dependencies"
        ) from exc
    return tomli


@dataclass(frozen=True)
class SettingsOverlay:
    select: Optional[frozenset[str]] = None
    ignore: Optional[frozenset[str]] = None
    exclude: Optional[Tuple[str, ...]] = None
    output_format: Optional[str] = None
    baseline: Optional[str] = None
    max_file_bytes: Optional[int] = None


@dataclass(frozen=True)
class Settings:
    select: frozenset[str]
    ignore: frozenset[str]
    exclude: Tuple[str, ...]
    output_format: str
    baseline: Optional[str]
    max_file_bytes: int

    def to_config(self) -> Config:
        return Config(select=self.select, ignore=self.ignore)


def _validate_rule_codes(codes: FrozenSet[str], field_name: str) -> None:
    for code in codes:
        if code not in VALID_RULE_CODES or not RULE_CODE_PATTERN.fullmatch(code):
            raise ConfigError(f"unknown rule code in {field_name}: {code!r}")


def _parse_rule_code_list(value: Any, field_name: str) -> frozenset[str]:
    if not isinstance(value, list):
        raise ConfigError(f"{field_name} must be a list of rule codes")
    result: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ConfigError(f"{field_name} must be a list of rule codes")
        if item not in VALID_RULE_CODES or not RULE_CODE_PATTERN.fullmatch(item):
            raise ConfigError(f"unknown rule code in {field_name}: {item!r}")
        result.add(item)
    return frozenset(result)


def _parse_exclude(value: Any) -> Tuple[str, ...]:
    if not isinstance(value, list):
        raise ConfigError("exclude must be a list of path patterns")
    patterns: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ConfigError("exclude must be a list of path patterns")
        patterns.append(item)
    return tuple(patterns)


def _parse_max_file_bytes(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError("max-file-bytes must be a positive integer")
    if value < 1:
        raise ConfigError("max-file-bytes must be a positive integer")
    if value > MAX_MAX_FILE_BYTES:
        raise ConfigError(f"max-file-bytes exceeds maximum ({MAX_MAX_FILE_BYTES})")
    return int(value)


def _parse_table(table: Any) -> SettingsOverlay:
    if not isinstance(table, dict):
        raise ConfigError("[tool.typewitness] must be a table")

    for key in table:
        if key not in SUPPORTED_KEYS:
            raise ConfigError(f"unknown configuration key: {key!r}")

    overlay = SettingsOverlay()
    if "select" in table:
        overlay = dataclass_replace(
            overlay,
            select=_parse_rule_code_list(table["select"], "select"),
        )
    if "ignore" in table:
        overlay = dataclass_replace(
            overlay,
            ignore=_parse_rule_code_list(table["ignore"], "ignore"),
        )
    if "exclude" in table:
        overlay = dataclass_replace(overlay, exclude=_parse_exclude(table["exclude"]))
    if "output-format" in table:
        output_format = table["output-format"]
        if not isinstance(output_format, str):
            raise ConfigError("output-format must be a string")
        if output_format not in SUPPORTED_OUTPUT_FORMATS:
            raise ConfigError(f"unknown output format: {output_format!r}")
        overlay = dataclass_replace(overlay, output_format=output_format)
    if "baseline" in table:
        baseline = table["baseline"]
        if not isinstance(baseline, str):
            raise ConfigError("baseline must be a string")
        overlay = dataclass_replace(overlay, baseline=baseline)
    if "max-file-bytes" in table:
        overlay = dataclass_replace(
            overlay,
            max_file_bytes=_parse_max_file_bytes(table["max-file-bytes"]),
        )
    return overlay


def dataclass_replace(instance: SettingsOverlay, **kwargs: Any) -> SettingsOverlay:
    return SettingsOverlay(
        select=kwargs.get("select", instance.select),
        ignore=kwargs.get("ignore", instance.ignore),
        exclude=kwargs.get("exclude", instance.exclude),
        output_format=kwargs.get("output_format", instance.output_format),
        baseline=kwargs.get("baseline", instance.baseline),
        max_file_bytes=kwargs.get("max_file_bytes", instance.max_file_bytes),
    )


def parse_settings_toml(text: str) -> SettingsOverlay:
    toml = import_toml_module()
    try:
        document = toml.loads(text)
    except RecursionError as exc:
        raise ConfigError("malformed pyproject.toml: excessive nesting") from exc
    except Exception as exc:
        raise ConfigError(f"malformed pyproject.toml: {exc}") from exc

    if not isinstance(document, dict):
        raise ConfigError("pyproject.toml must contain a table")

    tool = document.get("tool")
    if tool is None:
        return SettingsOverlay()
    if not isinstance(tool, dict):
        raise ConfigError("[tool] must be a table")

    for key in tool:
        if key == "typewitness":
            continue
        if key.startswith("typewitness."):
            raise ConfigError(f"unknown configuration table: tool.{key}")

    table = tool.get("typewitness")
    if table is None:
        return SettingsOverlay()
    return _parse_table(table)


def load_pyproject_overlay(project: Project) -> SettingsOverlay:
    path = project.pyproject_path
    if path.is_symlink():
        raise ConfigError(f"pyproject.toml must not be a symlink: {path}")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ConfigError(f"cannot read pyproject.toml: {path}") from exc
    if size > MAX_PYPROJECT_BYTES:
        raise ConfigError(
            f"pyproject.toml exceeds maximum size ({MAX_PYPROJECT_BYTES} bytes): {path}"
        )
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"cannot read pyproject.toml: {path}") from exc
    if len(payload) > MAX_PYPROJECT_BYTES:
        raise ConfigError(
            f"pyproject.toml exceeds maximum size ({MAX_PYPROJECT_BYTES} bytes): {path}"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(f"pyproject.toml is not valid UTF-8: {path}") from exc
    return parse_settings_toml(text)


def resolve_settings(*overlays: SettingsOverlay) -> Settings:
    select: Optional[frozenset[str]] = None
    ignore: Optional[frozenset[str]] = None
    exclude: Tuple[str, ...] = ()
    output_format = "text"
    baseline: Optional[str] = None
    max_file_bytes = DEFAULT_MAX_FILE_BYTES

    for overlay in overlays:
        if overlay.select is not None:
            _validate_rule_codes(overlay.select, "select")
            select = overlay.select
        if overlay.ignore is not None:
            _validate_rule_codes(overlay.ignore, "ignore")
            ignore = overlay.ignore
        if overlay.exclude is not None:
            exclude = overlay.exclude
        if overlay.output_format is not None:
            output_format = overlay.output_format
        if overlay.baseline is not None:
            baseline = overlay.baseline
        if overlay.max_file_bytes is not None:
            if overlay.max_file_bytes > MAX_MAX_FILE_BYTES:
                raise ConfigError(f"max-file-bytes exceeds maximum ({MAX_MAX_FILE_BYTES})")
            max_file_bytes = overlay.max_file_bytes

    return Settings(
        select=DEFAULT_RULESET if select is None else select,
        ignore=frozenset() if ignore is None else ignore,
        exclude=exclude,
        output_format=output_format,
        baseline=baseline,
        max_file_bytes=max_file_bytes,
    )
