from __future__ import annotations

from typewitness.exit_codes import EXIT_USAGE_ERROR


class TypeWitnessError(Exception):
    """Base error for integration-layer failures."""

    exit_code: int = EXIT_USAGE_ERROR

    def __init__(self, message: str) -> None:
        super().__init__(message)


class UsageError(TypeWitnessError):
    pass


class ConfigError(UsageError):
    pass


class BaselineError(ConfigError):
    pass


class ProjectDiscoveryError(UsageError):
    pass


class GitError(TypeWitnessError):
    pass


class FilesystemError(TypeWitnessError):
    pass
