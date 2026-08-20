"""Exit-code contract.

0 clean, 1 findings, 2 source analysis errors, 3 usage/config/git/filesystem errors, and
the higher code always wins. CI depends on this being a total, deterministic function of
the run outcome rather than whatever the last branch happened to return.
"""

from __future__ import annotations

import itertools

import pytest
from typewitness.errors import (
    BaselineError,
    ConfigError,
    FilesystemError,
    GitError,
    ProjectDiscoveryError,
    TypeWitnessError,
    UsageError,
)
from typewitness.exit_codes import (
    EXIT_ANALYSIS_ERROR,
    EXIT_FINDINGS,
    EXIT_OK,
    EXIT_USAGE_ERROR,
    resolve_exit_code,
)

ERROR_TYPES = (
    TypeWitnessError,
    UsageError,
    ConfigError,
    BaselineError,
    GitError,
    FilesystemError,
    ProjectDiscoveryError,
)


def test_exit_code_values() -> None:
    assert EXIT_OK == 0
    assert EXIT_FINDINGS == 1
    assert EXIT_ANALYSIS_ERROR == 2
    assert EXIT_USAGE_ERROR == 3


def test_clean_run_exits_zero() -> None:
    assert resolve_exit_code(has_findings=False, has_analysis_errors=False) == EXIT_OK


def test_findings_exit_one() -> None:
    assert resolve_exit_code(has_findings=True, has_analysis_errors=False) == EXIT_FINDINGS


def test_analysis_errors_exit_two() -> None:
    assert resolve_exit_code(has_findings=False, has_analysis_errors=True) == EXIT_ANALYSIS_ERROR


def test_analysis_errors_outrank_findings() -> None:
    assert resolve_exit_code(has_findings=True, has_analysis_errors=True) == EXIT_ANALYSIS_ERROR


def test_usage_errors_outrank_everything() -> None:
    for findings, analysis in itertools.product((False, True), repeat=2):
        code = resolve_exit_code(
            has_findings=findings,
            has_analysis_errors=analysis,
            has_usage_error=True,
        )
        assert code == EXIT_USAGE_ERROR


@pytest.mark.parametrize(
    ("findings", "analysis", "usage", "expected"),
    [
        (False, False, False, EXIT_OK),
        (True, False, False, EXIT_FINDINGS),
        (False, True, False, EXIT_ANALYSIS_ERROR),
        (True, True, False, EXIT_ANALYSIS_ERROR),
        (False, False, True, EXIT_USAGE_ERROR),
        (True, False, True, EXIT_USAGE_ERROR),
        (False, True, True, EXIT_USAGE_ERROR),
        (True, True, True, EXIT_USAGE_ERROR),
    ],
)
def test_exit_code_precedence_is_total(
    findings: bool,
    analysis: bool,
    usage: bool,
    expected: int,
) -> None:
    assert (
        resolve_exit_code(
            has_findings=findings,
            has_analysis_errors=analysis,
            has_usage_error=usage,
        )
        == expected
    )


def test_resolve_exit_code_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        resolve_exit_code(True, False)  # type: ignore[misc]


def test_usage_error_default_is_false() -> None:
    assert resolve_exit_code(has_findings=False, has_analysis_errors=False) == EXIT_OK


@pytest.mark.parametrize("error_type", ERROR_TYPES)
def test_every_error_type_maps_to_the_usage_exit_code(error_type: type) -> None:
    error = error_type("message")

    assert isinstance(error, TypeWitnessError)
    assert error.exit_code == EXIT_USAGE_ERROR
    assert str(error) == "message"


def test_error_hierarchy() -> None:
    assert issubclass(UsageError, TypeWitnessError)
    assert issubclass(ConfigError, UsageError)
    assert issubclass(BaselineError, ConfigError)
    assert issubclass(ProjectDiscoveryError, UsageError)
    assert issubclass(GitError, TypeWitnessError)
    assert issubclass(FilesystemError, TypeWitnessError)


def test_errors_are_ordinary_exceptions() -> None:
    for error_type in ERROR_TYPES:
        assert issubclass(error_type, Exception)
        assert not issubclass(error_type, SystemExit)
