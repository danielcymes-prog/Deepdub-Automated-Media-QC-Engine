"""Core enumerations shared across the system (handoff section 8).

Members may be added in minor schema versions; never removed or renamed
without a major schema version bump.
"""

from __future__ import annotations

from enum import StrEnum


class QCStatus(StrEnum):
    """Outcome of evaluating one rule, or of a whole job.

    Semantics (see docs/DATA_MODEL_REVIEW.md item 7):
        NOT_APPLICABLE: rule disabled, or its stream selector matches nothing
            by design.
        SKIPPED: a required measurement was expected but unavailable
            (e.g. upstream detector did not run). A SKIPPED enabled blocking
            rule escalates the job to ERROR - the tool must not pass a file
            it failed to inspect.
    """

    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class Category(StrEnum):
    FILE = "file"
    CONTAINER = "container"
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"
    METADATA = "metadata"
    DEEPDUB = "deepdub"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Operator(StrEnum):
    """Generic comparison operators available to preset rules (handoff section 13)."""

    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    IN = "in"
    NOT_IN = "not_in"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    BETWEEN = "between"
    APPROXIMATELY_EQUALS = "approximately_equals"
    CONTAINS = "contains"
    CONTAINS_ALL = "contains_all"
    REGEX = "regex"
    EXISTS = "exists"
    NOT_EXISTS = "not_exists"
    COUNT_EQUALS = "count_equals"
    COUNT_AT_LEAST = "count_at_least"
    COUNT_AT_MOST = "count_at_most"


class StreamType(StrEnum):
    """Stream scope for rule selectors (ADR-009)."""

    AUDIO = "audio"
    VIDEO = "video"
    SUBTITLE = "subtitle"
    CONTAINER = "container"


class Quantifier(StrEnum):
    """How a rule quantifies over the streams matched by its selector (ADR-009)."""

    ALL = "all"
    ANY = "any"
    EXACTLY_ONE = "exactly_one"


class PresetStatus(StrEnum):
    """Lifecycle status of a preset version (handoff section 12.2)."""

    DRAFT = "draft"
    APPROVED = "approved"
    DEPRECATED = "deprecated"


class EvidenceType(StrEnum):
    THUMBNAIL = "thumbnail"
    WAVEFORM = "waveform"
    CLIP = "clip"
    RAW = "raw"
