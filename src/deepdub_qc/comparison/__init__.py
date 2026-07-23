"""Vidchecker comparison harness (backlog #32).

Turns every Vidchecker run on the same file into recorded parity evidence:
parse the Vidchecker XML report, verify both tools analyzed identical bytes,
and diff Vidchecker's alerts against deepdub-qc measurements.
"""

from deepdub_qc.comparison.engine import (
    ComparisonResult,
    ComparisonRow,
    IdentityMismatchError,
    RowStatus,
    Tolerances,
    compare_reports,
)
from deepdub_qc.comparison.vidchecker import (
    VidcheckerAlert,
    VidcheckerParseError,
    VidcheckerTask,
    parse_vidchecker_report,
)

__all__ = [
    "ComparisonResult",
    "ComparisonRow",
    "IdentityMismatchError",
    "RowStatus",
    "Tolerances",
    "VidcheckerAlert",
    "VidcheckerParseError",
    "VidcheckerTask",
    "compare_reports",
    "parse_vidchecker_report",
]
