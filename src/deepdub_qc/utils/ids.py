"""Deterministic identifier generation (ADR-008).

Measurement and finding IDs are UUIDv5 values derived from their stable
content, so repeated runs of the same input/preset/environment produce
identical canonical IDs. Only `job_id` is random.

Why: the Definition of Done requires byte-identical canonical findings across
runs; random UUIDs would silently violate that and break golden-file tests.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

#: Namespace for all Deepdub QC deterministic IDs. Never change this value:
#: doing so alters every generated ID and invalidates all golden files.
QC_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://deepdub.ai/qc")

_SEPARATOR = "\x1f"  # ASCII unit separator: cannot appear in JSON output


def deterministic_id(*parts: Any) -> uuid.UUID:
    """Derive a stable UUIDv5 from an ordered sequence of content parts.

    Each part is canonicalized through JSON with sorted keys so dict ordering
    and unicode representation cannot influence the result.

    Inputs: any JSON-serializable parts (None allowed).
    Output: a UUID that is identical for identical inputs, on any machine.
    """
    canonical = _SEPARATOR.join(
        json.dumps(part, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
        for part in parts
    )
    return uuid.uuid5(QC_NAMESPACE, canonical)


def measurement_id(
    detector_id: str,
    detector_version: str,
    parameter_id: str,
    stream_index: int | None,
    start_seconds: float | None,
    end_seconds: float | None,
    value: Any,
) -> uuid.UUID:
    """Deterministic ID for a measurement, derived from its identifying content."""
    return deterministic_id(
        "measurement",
        detector_id,
        detector_version,
        parameter_id,
        stream_index,
        start_seconds,
        end_seconds,
        value,
    )


def finding_id(
    rule_id: str,
    rule_version: str,
    parameter_id: str,
    stream_index: int | None,
    start_seconds: float | None,
    status: str,
) -> uuid.UUID:
    """Deterministic ID for a finding, derived from its identifying content."""
    return deterministic_id(
        "finding",
        rule_id,
        rule_version,
        parameter_id,
        stream_index,
        start_seconds,
        status,
    )
