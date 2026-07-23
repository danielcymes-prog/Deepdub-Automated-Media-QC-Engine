"""Submission validation: the E1-E5 ladder (docs/server-gui-spec.md section 6).

Why: nothing is enqueued until the request is proven valid. Input paths are
untrusted (handoff section 20): they are resolved (following links/reparse
points) and containment-checked against the configured media_roots on the
RESOLVED path, so a link inside a root pointing outside it is rejected.

Inputs: raw form values + config + store + catalog.
Outputs: a ValidationResult with either a ready JobSubmission or typed field
errors (and the E5 duplicate, when found).
Side effects: filesystem stats only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from deepdub_qc.server.catalog import PresetInfo, find_preset
from deepdub_qc.server.config import DuplicatePolicy, ServerConfig
from deepdub_qc.server.store import JobRecord, JobStore, JobSubmission

_GB = 1024**3


@dataclass(frozen=True)
class FieldError:
    code: str  # E1..E5
    field: str  # input_path | preset | requested_by
    message: str


@dataclass(frozen=True)
class ValidationResult:
    submission: JobSubmission | None
    errors: list[FieldError] = field(default_factory=list)
    #: E5: existing in-flight job with the same identity (warn_confirm flow).
    duplicate: JobRecord | None = None

    @property
    def ok(self) -> bool:
        return self.submission is not None and not self.errors and self.duplicate is None


def _resolve_in_roots(
    raw_path: str, media_roots: list[Path]
) -> tuple[Path | None, FieldError | None]:
    try:
        resolved = Path(raw_path).resolve(strict=True)
    except OSError:
        return None, FieldError("E1", "input_path", f"File not found or not readable: {raw_path}")
    if not resolved.is_file():
        return None, FieldError("E1", "input_path", f"Not a file: {raw_path}")

    resolved_roots = []
    for root in media_roots:
        try:
            resolved_roots.append(root.resolve())
        except OSError:  # unreachable share: skip for containment purposes
            continue
    if not any(resolved.is_relative_to(root) for root in resolved_roots):
        allowed = ", ".join(str(r) for r in media_roots)
        return None, FieldError(
            "E2", "input_path", f"This location isn't an allowed media root. Allowed: {allowed}"
        )
    return resolved, None


def validate_submission(  # noqa: PLR0913 - one arg per form field, keyword-only
    *,
    raw_path: str,
    preset_id: str,
    preset_version: str,
    requested_by: str,
    config: ServerConfig,
    store: JobStore,
    catalog: list[PresetInfo],
    duplicate_override: bool = False,
    resubmit_of: str | None = None,
) -> ValidationResult:
    """Run the full pre-enqueue ladder; collect all field errors at once."""
    errors: list[FieldError] = []

    if not requested_by.strip():
        errors.append(FieldError("E1", "requested_by", "Requested by is required."))

    resolved, path_error = _resolve_in_roots(raw_path, config.paths.media_roots)
    if path_error is not None:
        errors.append(path_error)

    size = 0
    if resolved is not None:
        size = resolved.stat().st_size
        limit = config.jobs.max_file_size_gb * _GB
        if size > limit:
            errors.append(
                FieldError(
                    "E3",
                    "input_path",
                    f"File is {size / _GB:.1f} GB - the limit is "
                    f"{config.jobs.max_file_size_gb} GB. Contact the tool owner "
                    "if this is a legitimate deliverable.",
                )
            )

    preset = find_preset(catalog, preset_id, preset_version)
    if preset is None:
        errors.append(
            FieldError("E4", "preset", f"Preset {preset_id}@{preset_version} not found or invalid.")
        )

    if errors or resolved is None or preset is None:
        return ValidationResult(submission=None, errors=errors)

    submission = JobSubmission(
        input_path=str(resolved),
        input_size_bytes=size,
        preset_id=preset.preset_id,
        preset_version=preset.version,
        preset_path=str(preset.path),
        requested_by=requested_by.strip(),
        duplicate_override=duplicate_override,
        resubmit_of=resubmit_of,
    )

    policy = config.jobs.duplicate_inflight_policy
    if policy is not DuplicatePolicy.ALLOW and not duplicate_override:
        duplicate = store.find_inflight_duplicate(
            submission.input_path, size, preset.preset_id, preset.version
        )
        if duplicate is not None:
            if policy is DuplicatePolicy.REJECT:
                return ValidationResult(
                    submission=None,
                    errors=[
                        FieldError(
                            "E5",
                            "input_path",
                            f"This exact file and preset are already "
                            f"{duplicate.status.value} as job {duplicate.job_id[:8]}.",
                        )
                    ],
                )
            return ValidationResult(submission=submission, duplicate=duplicate)

    return ValidationResult(submission=submission)
