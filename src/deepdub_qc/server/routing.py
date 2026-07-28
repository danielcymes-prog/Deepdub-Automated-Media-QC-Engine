"""Verdict routing and completion webhooks for watch-folder jobs (ADR-028).

Why: a dropbox is only unattended once results LEAVE the folder - Vidchecker
moves inputs to pass/reject folders and downstream automation watches those.
This module is the worker's post-terminal step: after a watch job finishes,
move or copy the input per the folder's `on_pass` / `on_warning` / `on_reject`
actions and POST the outcome to the folder's `webhook_url`.

Hard rule: nothing here may change a verdict or a job status. report.json is
already written (ADR-002) and the store row is already terminal when this
runs; every failure degrades to an ERROR log plus a progress note on the job.

Routing semantics (docs/watch-folders-spec.md section 10):
- Only COMPLETED jobs route, and only for PASS / WARNING / FAIL verdicts.
  ERROR is not a media verdict and unset keys mean "leave in place" - there
  is no fallback between verdicts.
- Webhooks fire for COMPLETED and FAILED jobs. CANCELLED is a deliberate
  human act and notifies nobody.
- Webhook URLs may embed tokens: they are never logged and never shown in
  progress notes - only the target host is.

Inputs: a terminal JobRecord + ServerConfig. Outputs: moved/copied files,
webhook POSTs, progress notes on the job. Side effects: filesystem, network.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from deepdub_qc.models.enums import JobStatus, QCStatus
from deepdub_qc.server.config import RoutingAction, ServerConfig, WatchFolderEntry
from deepdub_qc.server.store import JobRecord, JobStore

logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT_SECONDS = 10.0
#: Connection errors and 5xx retry with these waits between attempts;
#: 4xx is a misconfigured endpoint and never retried.
WEBHOOK_RETRY_WAITS_SECONDS = (1.0, 5.0)

#: Which config key routes each verdict. ERROR is deliberately absent:
#: it means the pipeline could not measure, not that the media failed.
_VERDICT_TO_ACTION_KEY = {
    QCStatus.PASS.value: "on_pass",
    QCStatus.WARNING.value: "on_warning",
    QCStatus.FAIL.value: "on_reject",
}


class WebhookDeliveryError(Exception):
    """All delivery attempts failed. The message never contains the URL."""


def folder_for_job(requested_by: str, config: ServerConfig) -> WatchFolderEntry | None:
    """The watch folder that enqueued this job, or None for manual jobs.

    A folder removed from config after enqueue also returns None: routing
    policy lives in the current config, and a deleted binding has none.
    """
    if not requested_by.startswith("watch:"):
        return None
    name = requested_by.removeprefix("watch:")
    for entry in config.watch_folders:
        if entry.name == name:
            return entry
    return None


def action_for_verdict(entry: WatchFolderEntry, qc_status: str | None) -> RoutingAction | None:
    key = _VERDICT_TO_ACTION_KEY.get(qc_status or "")
    if key is None:
        return None
    action: RoutingAction | None = getattr(entry, key)
    return action


def unique_destination(directory: Path, filename: str) -> Path:
    """Never overwrite: a name collision gets a _1/_2/... suffix before the extension."""
    candidate = directory / filename
    stem, suffix = candidate.stem, candidate.suffix
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def route_file(input_path: Path, action: RoutingAction) -> tuple[str, Path]:
    """Move or copy the input; returns (verb, final destination). OSError propagates."""
    destination = unique_destination(action.destination, input_path.name)
    if action.move_to is not None:
        shutil.move(str(input_path), str(destination))
        return "moved", destination
    shutil.copy2(input_path, destination)
    return "copied", destination


def build_webhook_payload(
    job: JobRecord, entry: WatchFolderEntry, routed_to: Path | None
) -> dict[str, Any]:
    """The POST body: job identity + outcome + the canonical report verbatim.

    report is the full report.json contents for completed jobs (ADR-002: the
    receiver gets the source of truth, not a re-rendering); null when the job
    failed before producing one or the file cannot be read back.
    """
    report: dict[str, Any] | None = None
    if job.status is JobStatus.COMPLETED:
        report_path = Path(job.output_dir) / "report.json"
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning(
                "webhook payload: report.json unreadable",
                extra={"job_id": job.job_id},
            )
    return {
        "event": f"job.{job.status.value}",
        "job_id": job.job_id,
        "folder": entry.name,
        "input_path": job.input_path,
        "preset": f"{job.preset_id}@{job.preset_version}",
        "qc_status": job.qc_status,
        "error_reason": job.error_reason,
        "error_message": job.error_message,
        "routed_to": str(routed_to) if routed_to is not None else None,
        "finished_at": job.finished_at,
        "report": report,
    }


def deliver_webhook(
    url: str,
    payload: dict[str, Any],
    transport: httpx.BaseTransport | None = None,
) -> int:
    """POST the payload; returns the 2xx status code.

    Retries connection errors and 5xx per WEBHOOK_RETRY_WAITS_SECONDS; any
    other status is treated as a permanently misconfigured endpoint. Raises
    WebhookDeliveryError (URL-free message) when every attempt fails.
    """
    host = httpx.URL(url).host
    last_failure = "no attempt made"
    with httpx.Client(timeout=WEBHOOK_TIMEOUT_SECONDS, transport=transport) as client:
        for attempt in range(len(WEBHOOK_RETRY_WAITS_SECONDS) + 1):
            if attempt > 0:
                time.sleep(WEBHOOK_RETRY_WAITS_SECONDS[attempt - 1])
            try:
                response = client.post(
                    url, json=payload, headers={"X-Deepdub-QC-Event": payload["event"]}
                )
            except httpx.HTTPError as exc:
                last_failure = f"{type(exc).__name__} contacting {host}"
                continue
            if 200 <= response.status_code < 300:
                return response.status_code
            last_failure = f"HTTP {response.status_code} from {host}"
            if response.status_code < 500:
                break
    raise WebhookDeliveryError(last_failure)


class PostCompletion:
    """The worker's post-terminal hook: route the input, then notify.

    handle() is called by the worker AFTER the terminal store write, once per
    job, only for COMPLETED/FAILED. It records every outcome - success or
    degradation - as a progress note so the job page tells the whole story.
    """

    def __init__(
        self,
        store: JobStore,
        config: ServerConfig,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._store = store
        self._config = config
        self._transport = transport

    def handle(self, job: JobRecord) -> None:
        entry = folder_for_job(job.requested_by, self._config)
        if entry is None:
            return
        routed_to = self._route(job, entry)
        self._notify(job, entry, routed_to)

    def _route(self, job: JobRecord, entry: WatchFolderEntry) -> Path | None:
        if job.status is not JobStatus.COMPLETED:
            return None
        action = action_for_verdict(entry, job.qc_status)
        if action is None:
            return None
        try:
            verb, destination = route_file(Path(job.input_path), action)
        except OSError as exc:
            logger.error(
                "verdict routing failed; file left in place",
                extra={"job_id": job.job_id, "folder": entry.name, "error": str(exc)},
            )
            self._note(job.job_id, f"routing failed, file left in place: {exc}")
            return None
        logger.info(
            "verdict routing applied",
            extra={
                "job_id": job.job_id,
                "folder": entry.name,
                "verb": verb,
                "destination": str(destination),
            },
        )
        self._note(job.job_id, f"routing: {verb} to {destination} ({job.qc_status})")
        return destination

    def _notify(self, job: JobRecord, entry: WatchFolderEntry, routed_to: Path | None) -> None:
        if entry.webhook_url is None:
            return
        if job.status not in (JobStatus.COMPLETED, JobStatus.FAILED):
            return
        payload = build_webhook_payload(job, entry, routed_to)
        host = httpx.URL(entry.webhook_url).host
        try:
            status_code = deliver_webhook(entry.webhook_url, payload, self._transport)
        except WebhookDeliveryError as exc:
            logger.error(
                "webhook delivery failed",
                extra={"job_id": job.job_id, "folder": entry.name, "error": str(exc)},
            )
            self._note(job.job_id, f"webhook: delivery failed ({exc})")
            return
        logger.info(
            "webhook delivered",
            extra={"job_id": job.job_id, "folder": entry.name, "status_code": status_code},
        )
        self._note(job.job_id, f"webhook: delivered to {host} (HTTP {status_code})")

    def _note(self, job_id: str, label: str) -> None:
        self._store.record_progress(
            job_id,
            {"label": label, "at": datetime.now(UTC).isoformat(timespec="seconds")},
        )
