"""SQLite job store: queue and orchestration state, never QC results.

Why: the queue is a cross-request, cross-restart concern the filesystem
cannot serve safely (ADR-014). This store is an index over job output
directories - report.json remains the sole source of truth (ADR-002); the
verdict/summary columns are display snapshots copied verbatim from it.

Design notes:
- stdlib sqlite3 (no new dependency): one table, tiny load (<=2 operators).
- WAL mode; short-lived connections; BEGIN IMMEDIATE around read-modify-
  write transitions (enqueue capacity check, claim) so a second thread
  cannot double-claim.
- Duplicate identity for E5 is (resolved input path, size, preset id,
  preset version) - NOT the content hash: hashing a 40 GB master at submit
  time would block the form for minutes. The pipeline still records the
  real sha256 in report.json.

Inputs/outputs: JobRecord dataclasses. Side effects: the SQLite file.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deepdub_qc.exceptions import DeepdubQCError
from deepdub_qc.models.enums import JobStatus

#: Reasons recorded on FAILED jobs (machine-readable; messages are for humans).
REASON_INTERRUPTED = "interrupted_by_restart"
REASON_TIMEOUT = "timeout"


class QueueFullError(DeepdubQCError):
    """max_queue_length reached (GUI error E6)."""


class UnknownJobError(DeepdubQCError):
    """No job with that id."""


@dataclass(frozen=True)
class JobRecord:
    """One job's orchestration state (a row; never QC content)."""

    job_id: str
    status: JobStatus
    input_path: str
    input_size_bytes: int
    preset_id: str
    preset_version: str
    preset_path: str
    requested_by: str
    output_dir: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    qc_status: str | None = None  # verbatim from report.json when COMPLETED
    summary: dict[str, Any] | None = None  # verbatim summary block snapshot
    error_reason: str | None = None
    error_message: str | None = None
    progress: list[dict[str, Any]] = field(default_factory=list)
    cancel_requested: bool = False
    duplicate_override: bool = False
    resubmit_of: str | None = None
    cancelled_by: str | None = None

    @property
    def duplicate_key(self) -> str:
        return duplicate_key(
            self.input_path, self.input_size_bytes, self.preset_id, self.preset_version
        )


def duplicate_key(input_path: str, size: int, preset_id: str, preset_version: str) -> str:
    return f"{input_path}|{size}|{preset_id}|{preset_version}"


@dataclass(frozen=True)
class JobSubmission:
    """A validated submission, ready to enqueue (built by the web layer)."""

    input_path: str
    input_size_bytes: int
    preset_id: str
    preset_version: str
    preset_path: str
    requested_by: str
    duplicate_override: bool = False
    resubmit_of: str | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    rowid_order      INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id           TEXT UNIQUE NOT NULL,
    status           TEXT NOT NULL,
    input_path       TEXT NOT NULL,
    input_size_bytes INTEGER NOT NULL,
    preset_id        TEXT NOT NULL,
    preset_version   TEXT NOT NULL,
    preset_path      TEXT NOT NULL,
    requested_by     TEXT NOT NULL,
    output_dir       TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    started_at       TEXT,
    finished_at      TEXT,
    qc_status        TEXT,
    summary_json     TEXT,
    error_reason     TEXT,
    error_message    TEXT,
    progress_json    TEXT NOT NULL DEFAULT '[]',
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    duplicate_override INTEGER NOT NULL DEFAULT 0,
    resubmit_of      TEXT,
    cancelled_by     TEXT,
    duplicate_key    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_dupkey ON jobs (duplicate_key);
"""


class JobStore:
    """Thread-safe job queue over one SQLite file (WAL)."""

    def __init__(self, database: Path) -> None:
        self._database = database
        database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._database, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ------------------------------------------------------------ submission

    def enqueue(
        self, submission: JobSubmission, *, jobs_root: Path, max_queue_length: int
    ) -> JobRecord:
        """Create a PENDING job; raises QueueFullError at capacity (E6)."""
        job_id = str(uuid.uuid4())
        record = JobRecord(
            job_id=job_id,
            status=JobStatus.PENDING,
            input_path=submission.input_path,
            input_size_bytes=submission.input_size_bytes,
            preset_id=submission.preset_id,
            preset_version=submission.preset_version,
            preset_path=submission.preset_path,
            requested_by=submission.requested_by,
            output_dir=str(jobs_root / job_id),
            created_at=_now(),
            duplicate_override=submission.duplicate_override,
            resubmit_of=submission.resubmit_of,
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            pending = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status = ?", (JobStatus.PENDING.value,)
            ).fetchone()[0]
            if pending >= max_queue_length:
                conn.execute("ROLLBACK")
                raise QueueFullError(f"Queue is full ({pending} pending, limit {max_queue_length})")
            conn.execute(
                """INSERT INTO jobs (job_id, status, input_path, input_size_bytes,
                   preset_id, preset_version, preset_path, requested_by, output_dir,
                   created_at, duplicate_override, resubmit_of, duplicate_key)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.job_id,
                    record.status.value,
                    record.input_path,
                    record.input_size_bytes,
                    record.preset_id,
                    record.preset_version,
                    record.preset_path,
                    record.requested_by,
                    record.output_dir,
                    record.created_at,
                    int(record.duplicate_override),
                    record.resubmit_of,
                    record.duplicate_key,
                ),
            )
        return record

    def find_inflight_duplicate(
        self, input_path: str, size: int, preset_id: str, preset_version: str
    ) -> JobRecord | None:
        """Oldest PENDING/RUNNING job with the same duplicate identity (E5)."""
        key = duplicate_key(input_path, size, preset_id, preset_version)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE duplicate_key = ? AND status IN (?, ?) "
                "ORDER BY rowid_order LIMIT 1",
                (key, JobStatus.PENDING.value, JobStatus.RUNNING.value),
            ).fetchone()
        return _record(row) if row else None

    # ------------------------------------------------------------ worker side

    def claim_next(self) -> JobRecord | None:
        """Atomically move the oldest PENDING job to RUNNING and return it."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY rowid_order LIMIT 1",
                (JobStatus.PENDING.value,),
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return None
            started = _now()
            conn.execute(
                "UPDATE jobs SET status = ?, started_at = ? WHERE job_id = ?",
                (JobStatus.RUNNING.value, started, row["job_id"]),
            )
        return replace(_record(row), status=JobStatus.RUNNING, started_at=started)

    def record_progress(self, job_id: str, event: dict[str, Any]) -> None:
        """Append one stage event (spec section 5) to the job's progress list."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT progress_json FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                raise UnknownJobError(job_id)
            events = json.loads(row["progress_json"])
            events.append(event)
            conn.execute(
                "UPDATE jobs SET progress_json = ? WHERE job_id = ?",
                (json.dumps(events), job_id),
            )

    def mark_completed(self, job_id: str, qc_status: str, summary: dict[str, Any]) -> None:
        self._finish(job_id, JobStatus.COMPLETED, qc_status=qc_status, summary=summary)

    def mark_failed(self, job_id: str, reason: str, message: str) -> None:
        self._finish(job_id, JobStatus.FAILED, error_reason=reason, error_message=message)

    def mark_cancelled(self, job_id: str, cancelled_by: str | None = None) -> None:
        self._finish(job_id, JobStatus.CANCELLED, cancelled_by=cancelled_by)

    def _finish(  # noqa: PLR0913 - private column setter, keyword-only
        self,
        job_id: str,
        status: JobStatus,
        *,
        qc_status: str | None = None,
        summary: dict[str, Any] | None = None,
        error_reason: str | None = None,
        error_message: str | None = None,
        cancelled_by: str | None = None,
    ) -> None:
        with self._connect() as conn:
            updated = conn.execute(
                """UPDATE jobs SET status = ?, finished_at = ?, qc_status = ?,
                   summary_json = ?, error_reason = ?, error_message = ?,
                   cancelled_by = COALESCE(?, cancelled_by)
                   WHERE job_id = ?""",
                (
                    status.value,
                    _now(),
                    qc_status,
                    json.dumps(summary) if summary is not None else None,
                    error_reason,
                    error_message,
                    cancelled_by,
                    job_id,
                ),
            ).rowcount
        if updated == 0:
            raise UnknownJobError(job_id)

    def recover_orphans(self) -> list[str]:
        """F5: on startup, RUNNING jobs from a previous process become FAILED.

        A job must never be silently re-run; reruns are an explicit human act.
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT job_id FROM jobs WHERE status = ?", (JobStatus.RUNNING.value,)
            ).fetchall()
            ids = [row["job_id"] for row in rows]
            for job_id in ids:
                conn.execute(
                    """UPDATE jobs SET status = ?, finished_at = ?, error_reason = ?,
                       error_message = ? WHERE job_id = ?""",
                    (
                        JobStatus.FAILED.value,
                        _now(),
                        REASON_INTERRUPTED,
                        "The QC service restarted while this job was running, "
                        "so it was stopped for safety. Resubmit to run it again.",
                        job_id,
                    ),
                )
        return ids

    # ------------------------------------------------------------ cancel (F3)

    def request_cancel(self, job_id: str, cancelled_by: str | None = None) -> str:
        """Cancel a job. Returns one of 'cancelled', 'requested', 'already_finished'.

        PENDING jobs leave the queue instantly; RUNNING jobs get a cooperative
        flag (the worker terminates the subprocess tree and marks CANCELLED);
        finished jobs are untouched (E13 idempotency).
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                raise UnknownJobError(job_id)
            status = JobStatus(row["status"])
            if status is JobStatus.PENDING:
                conn.execute(
                    "UPDATE jobs SET status = ?, finished_at = ?, cancelled_by = ? "
                    "WHERE job_id = ?",
                    (JobStatus.CANCELLED.value, _now(), cancelled_by, job_id),
                )
                return "cancelled"
            if status is JobStatus.RUNNING:
                conn.execute(
                    "UPDATE jobs SET cancel_requested = 1, "
                    "cancelled_by = COALESCE(?, cancelled_by) WHERE job_id = ?",
                    (cancelled_by, job_id),
                )
                return "requested"
            return "already_finished"

    def cancel_requested(self, job_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT cancel_requested FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise UnknownJobError(job_id)
        return bool(row["cancel_requested"])

    # ------------------------------------------------------------ queries

    def get(self, job_id: str) -> JobRecord:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise UnknownJobError(job_id)
        return _record(row)

    def list_jobs(self, offset: int = 0, limit: int = 50) -> list[JobRecord]:
        """All users' jobs, newest first (spec section 3.2)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY rowid_order DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [_record(row) for row in rows]

    def count_jobs(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])

    def queue_position(self, job_id: str) -> tuple[int, int] | None:
        """(position, total) among PENDING jobs, 1-based; None if not pending."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT job_id FROM jobs WHERE status = ? ORDER BY rowid_order",
                (JobStatus.PENDING.value,),
            ).fetchall()
        pending = [row["job_id"] for row in rows]
        if job_id not in pending:
            return None
        return pending.index(job_id) + 1, len(pending)

    def queue_depth(self) -> int:
        with self._connect() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM jobs WHERE status IN (?, ?)",
                    (JobStatus.PENDING.value, JobStatus.RUNNING.value),
                ).fetchone()[0]
            )


def _record(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        job_id=row["job_id"],
        status=JobStatus(row["status"]),
        input_path=row["input_path"],
        input_size_bytes=row["input_size_bytes"],
        preset_id=row["preset_id"],
        preset_version=row["preset_version"],
        preset_path=row["preset_path"],
        requested_by=row["requested_by"],
        output_dir=row["output_dir"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        qc_status=row["qc_status"],
        summary=json.loads(row["summary_json"]) if row["summary_json"] else None,
        error_reason=row["error_reason"],
        error_message=row["error_message"],
        progress=json.loads(row["progress_json"]),
        cancel_requested=bool(row["cancel_requested"]),
        duplicate_override=bool(row["duplicate_override"]),
        resubmit_of=row["resubmit_of"],
        cancelled_by=row["cancelled_by"],
    )
