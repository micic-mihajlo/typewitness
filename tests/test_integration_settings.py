"""``[tool.typewitness]`` parsing and the defaults < pyproject < CLI precedence chain.

Parsing is strict on purpose: an unknown key, a wrong type, or an unknown rule code is a
configuration error (exit 3), never a silently ignored line. Silent tolerance is how a
linter ends up running a different ruleset than its config claims.
"""

from __future__ import annotations

import dataclasses
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests._integration_support import REPO_ROOT, make_root, scrubbed_env, write_project
from typewitness.errors import ConfigError, TypeWitnessError
from typewitness.exit_codes import EXIT_USAGE_ERROR
from typewitness.models import DEFAULT_RULESET
from typewitness.project import discover_project
from typewitness.settings import (
    TOML_BACKEND,
    Settings,
    SettingsOverlay,
    import_toml_module,
    load_pyproject_overlay,
    parse_settings_toml,
    resolve_settings,
)

FULL_TABLE = textwrap.dedent(
    """
    [project]
    name = "sample"
    version = "0.0.0"

    [tool.typewitness]
    select = ["TW002", "TW004"]
    ignore = ["TW004"]
    exclude = ["generated", "vendor/*"]
    output-format = "json"
    baseline = "typewitness-baseline.json"
    """
).lstrip()


def _pyproject(table: str) -> str:
    return '[project]\nname = "sample"\nversion = "0.0.0"\n\n' + textwrap.dedent(table).lstrip()


def test_defaults_when_nothing_is_configured() -> None:
    settings = resolve_settings()

    assert settings.select == DEFAULT_RULESET
    assert settings.ignore == frozenset()
    assert settings.exclude == ()
    assert settings.output_format == "text"
    assert settings.baseline is None
    assert settings.max_file_bytes == 1_048_576


def test_settings_is_frozen_and_hashable() -> None:
    settings = resolve_settings()

    assert hash(settings) == hash(resolve_settings())
    assert settings == resolve_settings()


def test_settings_maps_onto_the_core_config() -> None:
    settings = resolve_settings(SettingsOverlay(select=frozenset({"TW002", "TW003"})))

    config = settings.to_config()

    assert config.resolved_select() == frozenset({"TW002", "TW003"})


def test_ignore_is_subtracted_from_select_like_the_core() -> None:
    settings = resolve_settings(
        SettingsOverlay(select=frozenset({"TW001", "TW002"}), ignore=frozenset({"TW002"}))
    )

    assert settings.to_config().resolved_select() == frozenset({"TW001"})


def test_full_table_parses_every_supported_key() -> None:
    overlay = parse_settings_toml(FULL_TABLE)

    assert overlay.select == frozenset({"TW002", "TW004"})
    assert overlay.ignore == frozenset({"TW004"})
    assert overlay.exclude == ("generated", "vendor/*")
    assert overlay.output_format == "json"
    assert overlay.baseline == "typewitness-baseline.json"


def test_absent_table_yields_a_fully_unset_overlay() -> None:
    overlay = parse_settings_toml('[project]\nname = "sample"\nversion = "0.0.0"\n')

    assert overlay == SettingsOverlay()
    assert overlay.select is None
    assert overlay.ignore is None
    assert overlay.exclude is None
    assert overlay.output_format is None
    assert overlay.baseline is None


def test_empty_select_list_is_meaningful_and_not_the_default() -> None:
    overlay = parse_settings_toml(_pyproject("[tool.typewitness]\nselect = []\n"))

    settings = resolve_settings(overlay)

    assert overlay.select == frozenset()
    assert settings.select == frozenset()
    assert settings.to_config().resolved_select() == frozenset()


def test_unknown_key_is_a_config_error() -> None:
    with pytest.raises(ConfigError) as excinfo:
        parse_settings_toml(_pyproject('[tool.typewitness]\nselct = ["TW002"]\n'))

    assert isinstance(excinfo.value, TypeWitnessError)
    assert excinfo.value.exit_code == EXIT_USAGE_ERROR
    assert "selct" in str(excinfo.value)


def test_unknown_nested_table_is_a_config_error() -> None:
    with pytest.raises(ConfigError) as excinfo:
        parse_settings_toml(_pyproject("[tool.typewitness.per-file]\n'a.py' = ['TW002']\n"))

    assert "per-file" in str(excinfo.value)


@pytest.mark.parametrize(
    "table",
    [
        '[tool.typewitness]\nselect = "TW002"\n',
        "[tool.typewitness]\nselect = 2\n",
        "[tool.typewitness]\nselect = [2]\n",
        '[tool.typewitness]\nignore = "TW002"\n',
        '[tool.typewitness]\nexclude = "vendor"\n',
        "[tool.typewitness]\nexclude = [1, 2]\n",
        "[tool.typewitness]\noutput-format = 1\n",
        "[tool.typewitness]\nbaseline = true\n",
        '[tool.typewitness]\nselect = { a = "TW002" }\n',
    ],
)
def test_wrong_value_type_is_a_config_error(table: str) -> None:
    with pytest.raises(ConfigError) as excinfo:
        parse_settings_toml(_pyproject(table))

    assert excinfo.value.exit_code == EXIT_USAGE_ERROR


@pytest.mark.parametrize("field", ["select", "ignore"])
def test_unknown_rule_code_is_a_config_error(field: str) -> None:
    with pytest.raises(ConfigError) as excinfo:
        parse_settings_toml(_pyproject(f'[tool.typewitness]\n{field} = ["TW999"]\n'))

    assert "TW999" in str(excinfo.value)


@pytest.mark.parametrize("code", ["tw002", "TW02", "TW0021", "", "TW"])
def test_malformed_rule_code_is_a_config_error(code: str) -> None:
    with pytest.raises(ConfigError):
        parse_settings_toml(_pyproject(f'[tool.typewitness]\nselect = ["{code}"]\n'))


def test_unknown_output_format_is_a_config_error() -> None:
    with pytest.raises(ConfigError) as excinfo:
        parse_settings_toml(_pyproject('[tool.typewitness]\noutput-format = "xml"\n'))

    assert "xml" in str(excinfo.value)


@pytest.mark.parametrize("output_format", ["text", "json", "sarif", "pretty", "github"])
def test_supported_output_formats(output_format: str) -> None:
    table = f'[tool.typewitness]\noutput-format = "{output_format}"\n'

    assert parse_settings_toml(_pyproject(table)).output_format == output_format


def test_malformed_toml_is_a_config_error() -> None:
    with pytest.raises(ConfigError):
        parse_settings_toml("[tool.typewitness\nselect = [\n")


def test_underscore_key_spelling_is_rejected() -> None:
    """Only the hyphenated ``output-format`` spelling is accepted, so config is unambiguous."""
    with pytest.raises(ConfigError) as excinfo:
        parse_settings_toml(_pyproject('[tool.typewitness]\noutput_format = "json"\n'))

    assert "output_format" in str(excinfo.value)


def test_load_pyproject_overlay_reads_the_project_anchor(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {}, pyproject=FULL_TABLE)
    project = discover_project(root)

    overlay = load_pyproject_overlay(project)

    assert overlay.select == frozenset({"TW002", "TW004"})
    assert overlay.output_format == "json"


def test_load_pyproject_overlay_on_a_file_without_the_table(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {})
    project = discover_project(root)

    assert load_pyproject_overlay(project) == SettingsOverlay()


def test_load_pyproject_overlay_reports_undecodable_pyproject(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    (root / "pyproject.toml").write_bytes(b"\xff\xfe[tool.typewitness]\n")
    project = discover_project(root)

    with pytest.raises(ConfigError):
        load_pyproject_overlay(project)


def test_precedence_defaults_then_pyproject_then_cli() -> None:
    pyproject = SettingsOverlay(
        select=frozenset({"TW002"}),
        exclude=("from-pyproject",),
        output_format="json",
        baseline="pyproject-baseline.json",
    )
    cli = SettingsOverlay(select=frozenset({"TW003"}), output_format="sarif")

    settings = resolve_settings(pyproject, cli)

    assert settings.select == frozenset({"TW003"})
    assert settings.output_format == "sarif"
    assert settings.exclude == ("from-pyproject",)
    assert settings.baseline == "pyproject-baseline.json"


def test_unset_cli_fields_do_not_clobber_pyproject_values() -> None:
    pyproject = SettingsOverlay(ignore=frozenset({"TW003"}), exclude=("vendor",))

    settings = resolve_settings(pyproject, SettingsOverlay())

    assert settings.ignore == frozenset({"TW003"})
    assert settings.exclude == ("vendor",)


def test_pyproject_overrides_defaults_but_not_the_cli() -> None:
    defaults = resolve_settings()
    with_pyproject = resolve_settings(SettingsOverlay(select=frozenset({"TW001"})))
    with_cli = resolve_settings(
        SettingsOverlay(select=frozenset({"TW001"})),
        SettingsOverlay(select=frozenset({"TW002"})),
    )

    assert defaults.select == DEFAULT_RULESET
    assert with_pyproject.select == frozenset({"TW001"})
    assert with_cli.select == frozenset({"TW002"})


def test_cli_exclude_replaces_rather_than_extends_pyproject_exclude() -> None:
    settings = resolve_settings(
        SettingsOverlay(exclude=("a",)),
        SettingsOverlay(exclude=("b",)),
    )

    assert settings.exclude == ("b",)


def test_later_overlays_win_field_by_field() -> None:
    first = SettingsOverlay(select=frozenset({"TW001"}), baseline="a.json")
    second = SettingsOverlay(baseline="b.json")
    third = SettingsOverlay(ignore=frozenset({"TW001"}))

    settings = resolve_settings(first, second, third)

    assert settings.select == frozenset({"TW001"})
    assert settings.baseline == "b.json"
    assert settings.ignore == frozenset({"TW001"})


def test_resolve_settings_validates_overlay_rule_codes() -> None:
    with pytest.raises(ConfigError):
        resolve_settings(SettingsOverlay(select=frozenset({"TW999"})))


def test_toml_backend_matches_the_running_interpreter() -> None:
    expected = "tomllib" if sys.version_info >= (3, 11) else "tomli"

    assert TOML_BACKEND == expected


def test_import_toml_module_provides_loads() -> None:
    module = import_toml_module()

    assert hasattr(module, "loads")
    assert module.loads("a = 1\n") == {"a": 1}


def test_missing_tomli_is_an_actionable_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Python < 3.11 the parser comes from ``tomli``; its absence must be explained."""
    import typewitness.settings as settings_module

    monkeypatch.setattr(settings_module, "TOML_BACKEND", "tomli")
    monkeypatch.setitem(sys.modules, "tomli", None)

    with pytest.raises(ConfigError) as excinfo:
        import_toml_module()

    message = str(excinfo.value)
    assert "tomli" in message
    assert excinfo.value.exit_code == EXIT_USAGE_ERROR


def test_missing_tomli_error_surfaces_through_table_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import typewitness.settings as settings_module

    monkeypatch.setattr(settings_module, "TOML_BACKEND", "tomli")
    monkeypatch.setitem(sys.modules, "tomli", None)

    with pytest.raises(ConfigError):
        parse_settings_toml(FULL_TABLE)


def test_toml_backend_is_imported_lazily() -> None:
    """Importing the package must not require the TOML parser.

    This keeps ``typewitness --version`` and the library API working in an environment
    where the conditional ``tomli`` dependency was not installed.
    """
    script = (
        "import sys\n"
        "import typewitness\n"
        "import typewitness.cli\n"
        "import typewitness.settings\n"
        "print('tomli' in sys.modules, 'tomllib' in sys.modules)\n"
    )
    env = scrubbed_env(REPO_ROOT)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    completed = subprocess.run(
        (sys.executable, "-c", script),
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "False False"


def test_settings_exposes_only_the_documented_fields() -> None:
    names = tuple(field.name for field in dataclasses.fields(Settings))

    assert names == ("select", "ignore", "exclude", "output_format", "baseline", "max_file_bytes")


def test_overlay_exposes_the_same_fields_as_settings() -> None:
    settings_names = tuple(field.name for field in dataclasses.fields(Settings))
    overlay_names = tuple(field.name for field in dataclasses.fields(SettingsOverlay))

    assert overlay_names == settings_names
