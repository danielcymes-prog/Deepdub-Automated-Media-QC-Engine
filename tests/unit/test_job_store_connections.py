"""Regression tests: JobStore must not leak SQLite connections.

`store.py` used `with self._connect() as conn:` where `_connect` returned a bare
connection. That reads as managed, but `sqlite3.Connection.__exit__` only commits
or rolls back the transaction — it never closes the connection. Each call left an
open handle (2 descriptors under WAL, for the `-wal` and `-shm` files) for
CPython's refcounting to reclaim whenever the local happened to drop.

Consequences observed in practice:

- A pytest session retains a traceback per failure, and each retained frame pins
  its locals — including `conn`. On macOS, whose default `ulimit -n` is 256, this
  exhausted the descriptor table and turned 1 genuine failure into 152
  failures/errors, finally crashing pytest's own temp-dir cleanup with
  `OSError: [Errno 24] Too many open files`. Re-running under `ulimit -n 4096`
  produced `1 failed, 417 passed`.
- A long-running `deepdub-qc serve` process held a descriptor per store call
  until the garbage collector intervened.

Approach: these tests intercept `sqlite3.connect` for the duration of a test and
then probe every connection the store opened to see whether it is still usable.
Counting `sqlite3.Connection` objects on the heap would not work — a closed
connection is still a live object, so a retained traceback keeps the object
(harmless) without keeping the descriptor (the actual defect).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from deepdub_qc.models.enums import JobStatus
from deepdub_qc.server.store import JobStore, JobSubmission, UnknownJobError


@pytest.fixture
def opened_connections(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[sqlite3.Connection]]:
    """Record every connection opened via `sqlite3.connect` during a test.

    `store.py` calls `sqlite3.connect(...)` through the module attribute, so
    patching it here captures exactly the store's connections and nothing else.
    """
    created: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def spy(*args: object, **kwargs: object) -> sqlite3.Connection:
        conn = real_connect(*args, **kwargs)  # type: ignore[arg-type]
        created.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", spy)
    yield created


def still_open(connections: list[sqlite3.Connection]) -> int:
    """How many of these connections still hold their descriptors."""
    count = 0
    for conn in connections:
        try:
            conn.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            continue  # "Cannot operate on a closed database" — correctly released
        count += 1
    return count


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "qc.sqlite3")


def _submission(index: int, tmp_path: Path) -> JobSubmission:
    media = tmp_path / f"media-{index}.mov"
    media.write_bytes(b"\0" * 32)
    return JobSubmission(
        input_path=str(media),
        input_size_bytes=media.stat().st_size,
        preset_id="test-preset",
        preset_version="1",
        preset_path="presets/test-preset.yaml",
        requested_by="operator",
    )


# ---------------------------------------------------------------- the defect


def test_connect_closes_the_connection_on_block_exit(store: JobStore) -> None:
    """The core defect: __exit__ ended the transaction but left the handle open."""
    with store._connect() as conn:
        conn.execute("SELECT 1")

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        conn.execute("SELECT 1")


def test_connect_closes_even_when_the_block_raises(store: JobStore) -> None:
    """The path that actually leaked: a failing transaction inside the block."""
    with pytest.raises(RuntimeError), store._connect() as conn:
        conn.execute("SELECT 1")
        raise RuntimeError("transaction failed")

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        conn.execute("SELECT 1")


class _SetupFailsConnection(sqlite3.Connection):
    """A connection on which the WAL pragma fails, as it does when another
    process holds a lock past the busy timeout."""

    def execute(self, sql: str, *args: object) -> sqlite3.Cursor:  # type: ignore[override]
        if sql.startswith("PRAGMA journal_mode"):
            raise sqlite3.OperationalError("database is locked")
        return super().execute(sql, *args)  # type: ignore[arg-type]


def test_connect_closes_when_connection_setup_fails(
    store: JobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: row_factory and the PRAGMAs originally ran before the
    try/finally, so a locked database leaked the just-opened connection."""
    created: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def locked_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        conn = real_connect(*args, factory=_SetupFailsConnection, **kwargs)  # type: ignore[arg-type]
        created.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", locked_connect)
    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        store.queue_depth()

    assert len(created) == 1, "sanity: _connect really opened a connection"
    assert still_open(created) == 0, (
        "a connection whose setup fails must still be closed; "
        "the setup statements belong inside the try block"
    )


def test_repeated_operations_leave_no_connection_open(
    store: JobStore, tmp_path: Path, opened_connections: list[sqlite3.Connection]
) -> None:
    """The leak in aggregate, across the read and write paths."""
    for index in range(40):
        record = store.enqueue(
            _submission(index, tmp_path), jobs_root=tmp_path / "jobs", max_queue_length=100
        )
        store.get(record.job_id)
        store.list_jobs(offset=0, limit=10)

    assert len(opened_connections) >= 120, "sanity: the store really opened connections"
    leaked = still_open(opened_connections)
    assert leaked == 0, (
        f"{leaked} of {len(opened_connections)} connections are still open; "
        "_connect must close in a finally block"
    )


def test_connections_close_even_while_tracebacks_are_retained(
    store: JobStore, opened_connections: list[sqlite3.Connection]
) -> None:
    """The precise failure mode that produced 152 spurious failures.

    Retaining exception objects is what pytest does for every failure: the
    traceback keeps each frame, and each frame keeps its locals. Before the fix
    that pinned an *open* connection per retained frame. Now the object may
    survive, but its descriptor does not.
    """
    retained: list[BaseException] = []
    for _ in range(40):
        try:
            with store._connect() as conn:
                conn.execute("SELECT 1")
                raise RuntimeError("boom")
        except RuntimeError as exc:
            retained.append(exc)  # keeps __traceback__ → frame → locals → conn

    assert len(retained) == 40, "sanity: the frames really are retained"
    leaked = still_open(opened_connections)
    assert leaked == 0, (
        f"{leaked} connections pinned open by retained tracebacks; this is what "
        "exhausted the descriptor table"
    )


def test_store_survives_more_operations_than_a_low_descriptor_limit(
    store: JobStore, tmp_path: Path
) -> None:
    """Guards the scenario end to end: macOS defaults to `ulimit -n 256`, so
    roughly 130 unclosed WAL connections is enough to break the process."""
    for index in range(150):
        store.enqueue(
            _submission(index, tmp_path), jobs_root=tmp_path / "jobs", max_queue_length=500
        )
    assert store.count_jobs() == 150
    assert store.queue_depth() == 150


# ------------------------------------------- semantics that must be preserved


def test_successful_writes_are_still_committed(store: JobStore, tmp_path: Path) -> None:
    """Adding the close must not have cost us commit-on-success."""
    record = store.enqueue(
        _submission(0, tmp_path), jobs_root=tmp_path / "jobs", max_queue_length=10
    )
    # `get` opens a fresh connection, so it can only see committed data.
    assert store.get(record.job_id).job_id == record.job_id


def test_raising_blocks_are_still_rolled_back(store: JobStore) -> None:
    """`with conn` semantics preserved: a raising block must not persist."""
    with pytest.raises(RuntimeError), store._connect() as conn:
        # Every NOT NULL column without a default must be supplied, including
        # duplicate_key — the E5 identity the store derives on enqueue.
        conn.execute(
            "INSERT INTO jobs (job_id, status, input_path, input_size_bytes, "
            "preset_id, preset_version, preset_path, requested_by, output_dir, "
            "created_at, duplicate_key) VALUES ('rollback-me', 'pending', '/x', "
            "1, 'p', '1', 'p.yaml', 'op', '/out', '2026-07-26T00:00:00Z', 'k')"
        )
        raise RuntimeError("abort")

    with pytest.raises(UnknownJobError):
        store.get("rollback-me")


def test_begin_immediate_paths_still_work(store: JobStore, tmp_path: Path) -> None:
    """`claim_next` and `recover_orphans` issue an explicit BEGIN IMMEDIATE
    inside the managed block; the added close must not disturb that."""
    record = store.enqueue(
        _submission(0, tmp_path), jobs_root=tmp_path / "jobs", max_queue_length=10
    )
    claimed = store.claim_next()
    assert claimed is not None
    assert claimed.job_id == record.job_id
    assert store.get(record.job_id).status is JobStatus.RUNNING

    # A second claim finds nothing pending, and must not deadlock on itself.
    assert store.claim_next() is None

    recovered = store.recover_orphans()
    assert recovered == [record.job_id]
    assert store.get(record.job_id).status is JobStatus.FAILED
