"""Shared annotated types used by the domain models."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator, Field

SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def _validate_semver(value: str) -> str:
    if not SEMVER_PATTERN.match(value):
        msg = f"not a valid semantic version (expected MAJOR.MINOR.PATCH): {value!r}"
        raise ValueError(msg)
    return value


SemVer = Annotated[str, AfterValidator(_validate_semver)]
"""A strict MAJOR.MINOR.PATCH semantic version string."""

NonEmptyStr = Annotated[str, Field(min_length=1)]
"""A string that must not be empty."""
