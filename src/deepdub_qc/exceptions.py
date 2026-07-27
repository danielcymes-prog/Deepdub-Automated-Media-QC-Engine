"""Typed exception hierarchy.

Every error raised by deepdub_qc derives from DeepdubQCError so callers
(CLI, future API) can map failures to exit codes / HTTP statuses in one place.
"""

from __future__ import annotations


class DeepdubQCError(Exception):
    """Base class for all deepdub_qc errors."""


class PresetError(DeepdubQCError):
    """Base class for preset-related errors (exit code: invalid configuration)."""


class PresetNotFoundError(PresetError):
    """The preset file does not exist or is not a readable file."""


class PresetParseError(PresetError):
    """The preset file is not valid YAML."""


class PresetValidationError(PresetError):
    """The preset parsed but violates the preset schema or its invariants.

    Attributes:
        errors: Human-readable list of individual validation problems.
    """

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors: list[str] = errors or []


def preset_error_detail(exc: PresetError) -> str:
    """One-line rendering including any per-rule validation messages.

    `str(exc)` on a PresetValidationError is only the summary; the actionable
    part (which rule, which parameter, did-you-mean suggestions) is in
    `errors`. Log sites that swallow the exception must use this, or the
    detail is discarded exactly where it is most needed.
    """
    errors = getattr(exc, "errors", None)
    if errors:
        return f"{exc}: {'; '.join(errors)}"
    return str(exc)
