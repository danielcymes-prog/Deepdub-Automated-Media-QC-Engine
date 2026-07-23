"""Job store: queue semantics, cancel flows, orphan recovery (spec sections 3-6)."""

import threading
from pathlib import Path

import pytest

from deepdub_qc.models.enums import JobStatus
from deepdub_qc.server.store import (
    REASON_INTERRUPTED,
    JobStore,
    JobSubmission,
    QueueFullError,
    UnknownJobError,
)


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "qc.sqlite3")


def submit(store: JobStore, tmp_path: Path, name: str = "a.mov", max_queue_length: int = 20):
    submission = JobSubmission(
        input_path=f"D:\\media\\{name}",
        input_size_bytes=1000,
        preset_id="marimba_delivery",
        preset_version="1.0.0",
        preset_path="presets/clients/marimba/delivery_v1.yaml",
        requested_by="baruch",
    )
    return store.enqueue(submission, jobs_root=tmp_path / "jobs", max_queue_length=max_queue_length)


class TestQueue:
    def test_fifo_claim_order_and_positions(self, store: JobStore, tmp_path: Path) -> None:
        first = submit(store, tmp_path, "a.mov")
        second = submit(store, tmp_path, "b.mov")
        assert store.queue_position(first.job_id) == (1, 2)
        assert store.queue_position(second.job_id) == (2, 2)

        claimed = store.claim_next()
        assert claimed is not None and claimed.job_id == first.job_id
        assert claimed.status is JobStatus.RUNNING
        assert claimed.started_at is not None
        assert store.queue_position(second.job_id) == (1, 1)
        assert store.queue_position(first.job_id) is None  # no longer pending

    def test_queue_full_raises_e6(self, store: JobStore, tmp_path: Path) -> None:
        submit(store, tmp_path, "a.mov", max_queue_length=1)
        with pytest.raises(QueueFullError, match="limit 1"):
            submit(store, tmp_path, "b.mov", max_queue_length=1)

    def test_claim_empty_queue_returns_none(self, store: JobStore) -> None:
        assert store.claim_next() is None

    def test_concurrent_claims_never_double_claim(self, store: JobStore, tmp_path: Path) -> None:
        for i in range(4):
            submit(store, tmp_path, f"f{i}.mov")
        claimed: list[str] = []
        lock = threading.Lock()

        def claim() -> None:
            job = store.claim_next()
            if job is not None:
                with lock:
                    claimed.append(job.job_id)

        threads = [threading.Thread(target=claim) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(claimed) == 4
        assert len(set(claimed)) == 4  # each job claimed exactly once


class TestLifecycle:
    def test_complete_records_verdict_snapshot(self, store: JobStore, tmp_path: Path) -> None:
        job = submit(store, tmp_path)
        store.claim_next()
        store.mark_completed(job.job_id, "FAIL", {"failed": 2, "passed": 10})
        got = store.get(job.job_id)
        assert got.status is JobStatus.COMPLETED
        assert got.qc_status == "FAIL"  # orchestration COMPLETED + media FAIL coexist
        assert got.summary == {"failed": 2, "passed": 10}
        assert got.finished_at is not None

    def test_fail_records_reason(self, store: JobStore, tmp_path: Path) -> None:
        job = submit(store, tmp_path)
        store.claim_next()
        store.mark_failed(job.job_id, "timeout", "Job exceeded 240 minutes")
        got = store.get(job.job_id)
        assert got.status is JobStatus.FAILED
        assert got.error_reason == "timeout"

    def test_progress_events_append_in_order(self, store: JobStore, tmp_path: Path) -> None:
        job = submit(store, tmp_path)
        store.record_progress(job.job_id, {"stage": "probing", "state": "started"})
        store.record_progress(job.job_id, {"stage": "probing", "state": "finished"})
        assert [e["state"] for e in store.get(job.job_id).progress] == ["started", "finished"]

    def test_unknown_job_raises(self, store: JobStore) -> None:
        with pytest.raises(UnknownJobError):
            store.get("nope")


class TestCancel:
    def test_pending_cancel_is_immediate(self, store: JobStore, tmp_path: Path) -> None:
        job = submit(store, tmp_path)
        assert store.request_cancel(job.job_id, "dana") == "cancelled"
        got = store.get(job.job_id)
        assert got.status is JobStatus.CANCELLED
        assert got.cancelled_by == "dana"

    def test_running_cancel_sets_flag(self, store: JobStore, tmp_path: Path) -> None:
        job = submit(store, tmp_path)
        store.claim_next()
        assert store.request_cancel(job.job_id) == "requested"
        assert store.cancel_requested(job.job_id)
        assert store.get(job.job_id).status is JobStatus.RUNNING  # worker finishes it
        store.mark_cancelled(job.job_id)
        assert store.get(job.job_id).status is JobStatus.CANCELLED

    def test_finished_cancel_is_idempotent_e13(self, store: JobStore, tmp_path: Path) -> None:
        job = submit(store, tmp_path)
        store.claim_next()
        store.mark_completed(job.job_id, "PASS", {})
        assert store.request_cancel(job.job_id) == "already_finished"
        assert store.get(job.job_id).status is JobStatus.COMPLETED


class TestRestartRecovery:
    def test_orphaned_running_jobs_fail_queue_preserved(self, tmp_path: Path) -> None:
        """F5: restart mid-job -> orphan FAILED(interrupted), pending intact."""
        database = tmp_path / "qc.sqlite3"
        store = JobStore(database)
        running = submit(store, tmp_path, "running.mov")
        pending = submit(store, tmp_path, "pending.mov")
        store.claim_next()

        restarted = JobStore(database)  # simulates process restart
        recovered = restarted.recover_orphans()
        assert recovered == [running.job_id]
        got = restarted.get(running.job_id)
        assert got.status is JobStatus.FAILED
        assert got.error_reason == REASON_INTERRUPTED
        assert restarted.get(pending.job_id).status is JobStatus.PENDING
        assert restarted.queue_position(pending.job_id) == (1, 1)


class TestDuplicatesAndListing:
    def test_inflight_duplicate_found_by_identity(self, store: JobStore, tmp_path: Path) -> None:
        job = submit(store, tmp_path, "same.mov")
        dup = store.find_inflight_duplicate(
            job.input_path, job.input_size_bytes, job.preset_id, job.preset_version
        )
        assert dup is not None and dup.job_id == job.job_id
        # different preset version -> not a duplicate
        assert (
            store.find_inflight_duplicate(
                job.input_path, job.input_size_bytes, job.preset_id, "2.0.0"
            )
            is None
        )
        # finished jobs are not in-flight duplicates
        store.claim_next()
        store.mark_completed(job.job_id, "PASS", {})
        assert (
            store.find_inflight_duplicate(
                job.input_path, job.input_size_bytes, job.preset_id, job.preset_version
            )
            is None
        )

    def test_list_newest_first_paginated(self, store: JobStore, tmp_path: Path) -> None:
        ids = [submit(store, tmp_path, f"f{i}.mov").job_id for i in range(5)]
        page = store.list_jobs(offset=0, limit=2)
        assert [j.job_id for j in page] == [ids[4], ids[3]]
        page2 = store.list_jobs(offset=2, limit=2)
        assert [j.job_id for j in page2] == [ids[2], ids[1]]
        assert store.count_jobs() == 5

    def test_queue_depth_counts_pending_and_running(self, store: JobStore, tmp_path: Path) -> None:
        submit(store, tmp_path, "a.mov")
        submit(store, tmp_path, "b.mov")
        store.claim_next()
        assert store.queue_depth() == 2  # 1 running + 1 pending
