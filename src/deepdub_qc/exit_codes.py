"""Stable, documented CLI exit codes (handoff section 18).

These are a public contract consumed by pipeline automation. Never renumber.
"""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Machine-readable process exit codes for the deepdub-qc CLI."""

    QC_PASS = 0
    QC_WARNING = 1
    QC_FAIL = 2
    QC_EXECUTION_ERROR = 3
    INVALID_CONFIGURATION = 4
    INVALID_INPUT = 5
    INTERNAL_ERROR = 6
