"""Watch folders: files dropped into bound directories become QC jobs.

Why: manual submission does not scale to delivery operations - Vidchecker is
operated almost entirely through its dropboxes (docs/watch-folders-spec.md).
This is the same model on the existing queue: one watcher thread polls the
configured folders and enqueues through the exact `JobStore.enqueue` path the
console uses, so watcher jobs are ordinary jobs with `watch:<name>` provenance.

Design constraints from the spec:
- Polling, not OS notification: folders live on UNC shares where change
  notification is unreliable.
- A file is enqueued only when STABLE: identical size+mtime on two
  consecutive scans and untouched for `settle_seconds` - files still being
  copied must never trigger a job.
- `watch_seen` (persistent, in the job store) remembers what was enqueued so
  a service restart never re-QCs a folder full of processed files; a changed
  size/mtime is a deliberate re-delivery and enqueues again.
- Failures degrade per folder, never the loop: an unloadable preset or
  unreachable directory puts that folder into an error state shown in the
  console panel while other folders keep scanning.
- v1 never moves or deletes input files (routing is the follow-up).

Inputs: WatchFolderEntry config, the job store, the preset catalog.
Outputs: enqueued jobs and per-folder status snapshots for the GUI/API.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from deepdub_qc.server.catalog import PresetInfo, build_catalog, find_preset
from deepdub_qc.server.config import ServerConfig, WatchFolderEntry
from deepdub_qc.server.store import JobStore, JobSubmission, QueueFullError

logger = logging.getLogger(__name__)

#: A deferred file is retried on every scan; after this many failed attempts
#: it is parked until its size/mtime changes (spec section 5).
MAX_DEFER_ATTEMPTS = 10
#: watch_seen entries older than this are pruned during scans (spec section 9.5).
SEEN_RETENTION_DAYS = 90


@dataclass(frozen=True)
class FileSnapshot:
    """One candidate file as observed by a single scan."""

    path: str
    size: int
    mtime: float


@dataclass
class FolderState:
    """Runtime state of one watch folder (mutated only by the watcher thread)."""

    entry: WatchFolderEntry
    preset: PresetInfo
    error: str | None = None
    last_scan_at: float | None = None
    next_scan_at: float = 0.0
    enqueued_total: int = 0
    #: Snapshots from the previous scan, keyed by path (stability comparison).
    previous: dict[str, FileSnapshot] = field(default_factory=dict)
    #: path -> failed attempt count for deferred files.
    deferrals: dict[str, int] = field(default_factory=dict)
    #: Deferred files parked after MAX_DEFER_ATTEMPTS, keyed by (path, size, mtime).
    parked: set[tuple[str, int, float]] = field(default_factory=set)


@dataclass(frozen=True)
class FolderStatus:
    """Read-only view for the console panel and /api/v1/watch-folders."""

    name: str
    path: str
    preset_id: str
    preset_version: str
    preset_status: str
    enabled: bool
    error: str | None
    last_scan_at: float | None
    enqueued_total: int
    deferred_count: int
    #: Human summary of the folder's routing/webhook config (ADR-028); the
    #: webhook URL itself never appears here - it may embed tokens.
    routing: str


def scan_folder(path: Path, extensions: list[str], recursive: bool) -> list[FileSnapshot]:
    """Snapshot matching files. OSErrors propagate to the caller (folder error).

    A missing directory raises rather than reading as empty: `glob` on a
    nonexistent path yields nothing, which would silently mask an unmounted
    share as "no files today".
    """
    if not path.is_dir():
        raise FileNotFoundError(f"not a directory: {path}")
    pattern = "**/*" if recursive else "*"
    snapshots = []
    for candidate in sorted(path.glob(pattern)):
        if not candidate.is_file():
            continue
        if candidate.suffix.lstrip(".").lower() not in extensions:
            continue
        stat = candidate.stat()
        snapshots.append(FileSnapshot(path=str(candidate), size=stat.st_size, mtime=stat.st_mtime))
    return snapshots


def routing_summary(entry: WatchFolderEntry) -> str:
    """One line for the panel: which verdicts route where, and whether a webhook is set."""
    labels = {"on_pass": "pass", "on_warning": "warning", "on_reject": "reject"}
    parts = []
    for key, action in entry.routing_actions.items():
        verb = "move" if action.move_to is not None else "copy"
        parts.append(f"{labels[key]} → {action.destination} ({verb})")
    if entry.webhook_url is not None:
        parts.append("webhook set")
    return "; ".join(parts)


def is_stable(
    snapshot: FileSnapshot,
    previous: FileSnapshot | None,
    now: float,
    settle_seconds: int,
) -> bool:
    """Spec section 2: unchanged across two scans AND settled for long enough."""
    if previous is None:
        return False
    if snapshot.size != previous.size or snapshot.mtime != previous.mtime:
        return False
    return (now - snapshot.mtime) >= settle_seconds


class Watcher:
    """Single background thread scanning every configured watch folder.

    Mirrors Worker's lifecycle (start/stop, daemon thread). `scan_once` is
    public and side-effect-complete so tests drive scans with a fake clock
    and no thread.
    """

    def __init__(
        self,
        store: JobStore,
        config: ServerConfig,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self._store = store
        self._config = config
        self._now = now_fn if now_fn is not None else time.time
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._states = self._resolve_folders()

    def _resolve_folders(self) -> list[FolderState]:
        """Bind every configured folder to its preset; unresolvable is fatal.

        Startup is the moment to fail loudly (strict-config policy); presets
        that break LATER degrade per folder at scan time instead.
        """
        entries = self._config.watch_folders
        if not entries:
            return []
        catalog = build_catalog(self._config.paths.presets_root)
        states = []
        for entry in entries:
            preset_id, _, version = entry.preset.partition("@")
            preset = find_preset(catalog, preset_id, version)
            if preset is None:
                msg = (
                    f"watch folder {entry.name!r}: preset {entry.preset!r} not found "
                    "in the catalog (expected '<preset_id>@<version>')"
                )
                raise ValueError(msg)
            states.append(FolderState(entry=entry, preset=preset))
        return states

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        if not self._states:
            logger.info("no watch folders configured; watcher not started")
            return
        self._thread = threading.Thread(target=self._loop, name="qc-watcher", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.scan_once(self._now())
            self._stop.wait(1.0)

    # ------------------------------------------------------------- scanning

    def scan_once(self, now: float) -> int:
        """Scan every due folder once; returns the number of jobs enqueued."""
        enqueued = 0
        with self._lock:
            for state in self._states:
                if not state.entry.enabled or now < state.next_scan_at:
                    continue
                state.next_scan_at = now + state.entry.poll_seconds
                enqueued += self._scan_folder(state, now)
        self._store.watch_seen_prune(SEEN_RETENTION_DAYS)
        return enqueued

    def _scan_folder(self, state: FolderState, now: float) -> int:
        entry = state.entry
        try:
            snapshots = scan_folder(Path(entry.path), entry.extensions, entry.recursive)
        except OSError as exc:
            if state.error is None:
                logger.error(
                    "watch folder unreachable",
                    extra={"folder": entry.name, "error": str(exc)},
                )
            state.error = f"folder unreachable: {exc}"
            state.last_scan_at = now
            return 0
        if state.error is not None and state.error.startswith("folder unreachable"):
            logger.info("watch folder recovered", extra={"folder": entry.name})
            state.error = None

        enqueued = 0
        for snapshot in snapshots:
            if self._consider(state, snapshot, now):
                enqueued += 1
        state.previous = {snapshot.path: snapshot for snapshot in snapshots}
        state.last_scan_at = now
        return enqueued

    def _consider(  # noqa: PLR0911 - one early return per skip reason
        self, state: FolderState, snapshot: FileSnapshot, now: float
    ) -> bool:
        entry = state.entry
        key = (snapshot.path, snapshot.size, snapshot.mtime)
        if key in state.parked:
            return False
        if not is_stable(snapshot, state.previous.get(snapshot.path), now, entry.settle_seconds):
            return False

        seen = self._store.watch_seen_get(snapshot.path)
        already_enqueued = seen is not None and seen == (snapshot.size, snapshot.mtime)
        if already_enqueued:
            return False
        redelivery = seen is not None  # same path, different bytes: deliberate re-drop

        try:
            preset = self._load_preset(state)
            if preset is None:
                return False
            submission = JobSubmission(
                input_path=snapshot.path,
                input_size_bytes=snapshot.size,
                preset_id=state.preset.preset_id,
                preset_version=state.preset.version,
                preset_path=str(state.preset.path),
                requested_by=f"watch:{entry.name}",
                duplicate_override=redelivery,
            )
            record = self._store.enqueue(
                submission,
                jobs_root=self._config.paths.jobs_root,
                max_queue_length=self._config.jobs.max_queue_length,
            )
        except QueueFullError:
            self._defer(state, snapshot, "queue full")
            return False
        except OSError as exc:
            self._defer(state, snapshot, f"unreadable: {exc}")
            return False

        self._store.watch_seen_record(
            snapshot.path, snapshot.size, snapshot.mtime, entry.name, record.job_id
        )
        state.deferrals.pop(snapshot.path, None)
        state.enqueued_total += 1
        logger.info(
            "watch folder enqueued job",
            extra={
                "folder": entry.name,
                "file": Path(snapshot.path).name,
                "job_id": record.job_id,
                "redelivery": redelivery,
            },
        )
        return True

    def _load_preset(self, state: FolderState) -> object | None:
        """Prove the bound preset still loads; degrade the folder if not."""
        from deepdub_qc.exceptions import PresetError, preset_error_detail  # noqa: PLC0415
        from deepdub_qc.presets.loader import load_preset  # noqa: PLC0415

        try:
            preset = load_preset(state.preset.path)
        except PresetError as exc:
            if state.error is None:
                logger.error(
                    "watch folder preset no longer loads",
                    extra={"folder": state.entry.name, "error": preset_error_detail(exc)},
                )
            state.error = f"preset failed to load: {preset_error_detail(exc)}"
            return None
        if state.error is not None and state.error.startswith("preset failed"):
            state.error = None
        return preset

    def _defer(self, state: FolderState, snapshot: FileSnapshot, reason: str) -> None:
        attempts = state.deferrals.get(snapshot.path, 0) + 1
        state.deferrals[snapshot.path] = attempts
        logger.warning(
            "watch folder deferred file",
            extra={
                "folder": state.entry.name,
                "file": Path(snapshot.path).name,
                "reason": reason,
                "attempt": attempts,
            },
        )
        if attempts >= MAX_DEFER_ATTEMPTS:
            state.parked.add((snapshot.path, snapshot.size, snapshot.mtime))
            state.deferrals.pop(snapshot.path, None)
            logger.error(
                "watch folder parked file after repeated failures",
                extra={"folder": state.entry.name, "file": Path(snapshot.path).name},
            )

    # ------------------------------------------------------------- status

    def status(self) -> list[FolderStatus]:
        with self._lock:
            return [
                FolderStatus(
                    name=state.entry.name,
                    path=str(state.entry.path),
                    preset_id=state.preset.preset_id,
                    preset_version=state.preset.version,
                    preset_status=state.preset.status,
                    enabled=state.entry.enabled,
                    error=state.error,
                    last_scan_at=state.last_scan_at,
                    enqueued_total=state.enqueued_total,
                    deferred_count=len(state.deferrals) + len(state.parked),
                    routing=routing_summary(state.entry),
                )
                for state in self._states
            ]
