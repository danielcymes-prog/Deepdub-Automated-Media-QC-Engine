"""Background worker: claims queued jobs and runs the SAME pipeline as the CLI.

Why: one in-process worker (ADR-014) serializes FFmpeg work; a job submitted
from the GUI must produce identical canonical output to `deepdub-qc analyze`
(spec section 1), so this module calls run_analysis and adds only
orchestration around it - never QC behavior.

Cancellation and timeout (F3/E9): a per-job monitor thread watches the
store's cancel flag and the job deadline. On trigger it kills the tool
currently running on the worker thread (utils.subprocess registry) and the
pipeline's next progress callback raises to unwind. Cancellation is
therefore effective mid-ffmpeg, not just at stage boundaries.

Inputs: JobStore + ServerConfig. Outputs: store state transitions + job
directories produced by the pipeline. Side effects: threads, subprocesses.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from deepdub_qc.exceptions import DeepdubQCError, PresetError
from deepdub_qc.server.config import ServerConfig
from deepdub_qc.server.store import REASON_TIMEOUT, JobRecord, JobStore
from deepdub_qc.utils.subprocess import terminate_active_tool

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 0.5
MONITOR_INTERVAL_SECONDS = 0.5


class JobCancelledError(Exception):
    """Raised inside the pipeline callback to unwind a cancelled job."""


class JobTimeoutError(Exception):
    """Raised inside the pipeline callback when the job deadline passed."""


class PipelineRunner(Protocol):
    """The pipeline entrypoint shape (injectable for tests)."""

    def __call__(
        self,
        input_path: Path,
        preset_path: Path,
        output_dir: Path,
        on_progress: Callable[[str], None],
    ) -> tuple[str, dict[str, object]]:
        """Returns (overall_qc_status, summary_dict)."""
        ...


def _run_real_pipeline(
    input_path: Path,
    preset_path: Path,
    output_dir: Path,
    on_progress: Callable[[str], None],
) -> tuple[str, dict[str, object]]:
    from deepdub_qc.orchestration.pipeline import AnalysisOptions, run_analysis  # noqa: PLC0415

    result = run_analysis(
        input_path,
        preset_path,
        output_dir,
        # PDF rendering wiring (Playwright, E10 degraded mode) lands with the
        # app layer; the canonical JSON+HTML artifacts are always produced.
        AnalysisOptions(render_pdf=False, on_progress=on_progress),
    )
    return (
        result.summary.overall_status.value,
        result.summary.model_dump(mode="json"),
    )


class Worker:
    """Single background worker thread with per-job cancel/timeout monitor."""

    def __init__(
        self,
        store: JobStore,
        config: ServerConfig,
        runner: PipelineRunner | None = None,
        poll_interval: float = POLL_INTERVAL_SECONDS,
    ) -> None:
        self._store = store
        self._config = config
        self._runner: PipelineRunner = runner if runner is not None else _run_real_pipeline
        self._poll_interval = poll_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        self._store.recover_orphans()  # F5: never silently re-run
        self._thread = threading.Thread(target=self._loop, name="qc-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self._store.claim_next()
            if job is None:
                self._stop.wait(self._poll_interval)
                continue
            self._execute(job)

    # ------------------------------------------------------------- execution

    def _execute(self, job: JobRecord) -> None:
        deadline = time.monotonic() + self._config.jobs.max_job_duration_minutes * 60
        worker_ident = threading.get_ident()
        job_done = threading.Event()
        timed_out = threading.Event()

        def monitor() -> None:
            while not job_done.wait(MONITOR_INTERVAL_SECONDS):
                if time.monotonic() > deadline:
                    timed_out.set()
                    terminate_active_tool(worker_ident)
                    return
                if self._store.cancel_requested(job.job_id):
                    terminate_active_tool(worker_ident)
                    return

        def on_progress(message: str) -> None:
            self._store.record_progress(
                job.job_id,
                {"label": message, "at": datetime.now(UTC).isoformat(timespec="seconds")},
            )
            if timed_out.is_set():
                raise JobTimeoutError(message)
            if self._store.cancel_requested(job.job_id):
                raise JobCancelledError(message)

        monitor_thread = threading.Thread(
            target=monitor, name=f"qc-monitor-{job.job_id[:8]}", daemon=True
        )
        monitor_thread.start()
        try:
            qc_status, summary = self._runner(
                Path(job.input_path), Path(job.preset_path), Path(job.output_dir), on_progress
            )
        except JobCancelledError:
            self._store.mark_cancelled(job.job_id)
            logger.info("job cancelled", extra={"job_id": job.job_id})
        except JobTimeoutError:
            self._store.mark_failed(job.job_id, REASON_TIMEOUT, self._timeout_message())
        except DeepdubQCError as exc:
            # A kill from the monitor surfaces as a tool/pipeline error here;
            # classify by cause before treating it as a genuine failure.
            self._classify_pipeline_error(job, exc, timed_out.is_set())
        except Exception as exc:  # never let the worker thread die silently
            self._store.mark_failed(job.job_id, "internal_error", str(exc))
            logger.exception("job crashed", extra={"job_id": job.job_id})
        else:
            self._store.mark_completed(job.job_id, qc_status, summary)
            logger.info("job completed", extra={"job_id": job.job_id, "qc_status": qc_status})
        finally:
            job_done.set()
            monitor_thread.join(timeout=5.0)

    def _classify_pipeline_error(
        self, job: JobRecord, exc: DeepdubQCError, timed_out: bool
    ) -> None:
        if timed_out:
            self._store.mark_failed(job.job_id, REASON_TIMEOUT, self._timeout_message())
            return
        if self._store.cancel_requested(job.job_id):
            self._store.mark_cancelled(job.job_id)
            logger.info("job cancelled mid-tool", extra={"job_id": job.job_id})
            return
        from deepdub_qc.orchestration.pipeline import InputFileError  # noqa: PLC0415

        if isinstance(exc, PresetError):
            reason = "invalid_preset"
        elif isinstance(exc, InputFileError):
            reason = "invalid_input"
        else:
            reason = "pipeline_error"
        self._store.mark_failed(job.job_id, reason, str(exc))
        logger.error(
            "job failed", extra={"job_id": job.job_id, "reason": reason, "error": str(exc)}
        )

    def _timeout_message(self) -> str:
        return (
            f"Job exceeded {self._config.jobs.max_job_duration_minutes} minutes "
            "and was stopped. Partial raw output remains in the job folder."
        )
