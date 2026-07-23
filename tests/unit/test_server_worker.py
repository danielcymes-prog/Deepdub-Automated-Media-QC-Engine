"""Worker execution flows and submission validation (spec sections 4-6)."""

import time
from pathlib import Path

import pytest

from deepdub_qc.exceptions import DeepdubQCError
from deepdub_qc.models.enums import JobStatus
from deepdub_qc.server.catalog import build_catalog
from deepdub_qc.server.config import ServerConfig
from deepdub_qc.server.store import JobStore, JobSubmission
from deepdub_qc.server.validation import validate_submission
from deepdub_qc.server.worker import (
    JobCancelledError,
    JobTimeoutError,
    Worker,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def make_config(tmp_path: Path, **jobs_overrides) -> ServerConfig:
    media = tmp_path / "media"
    media.mkdir(exist_ok=True)
    (tmp_path / "ffmpeg").write_text("")
    (tmp_path / "ffprobe").write_text("")
    return ServerConfig.model_validate(
        {
            "schema_version": 1,
            "paths": {
                "media_roots": [str(media)],
                "jobs_root": str(tmp_path / "jobs"),
                "database": str(tmp_path / "qc.sqlite3"),
                "presets_root": str(REPO_ROOT / "presets"),
            },
            "tools": {
                "ffmpeg_path": str(tmp_path / "ffmpeg"),
                "ffprobe_path": str(tmp_path / "ffprobe"),
            },
            "jobs": jobs_overrides,
        }
    )


def enqueue(store: JobStore, config: ServerConfig, name: str = "a.mov") -> str:
    media = config.paths.media_roots[0] / name
    media.write_bytes(b"x" * 100)
    submission = JobSubmission(
        input_path=str(media),
        input_size_bytes=100,
        preset_id="p",
        preset_version="1.0.0",
        preset_path="unused.yaml",
        requested_by="baruch",
    )
    return store.enqueue(submission, jobs_root=config.paths.jobs_root, max_queue_length=20).job_id


def run_worker_until(store: JobStore, config: ServerConfig, runner, job_ids: list[str]) -> None:
    worker = Worker(store, config, runner=runner, poll_interval=0.02)
    worker.start()
    deadline = time.monotonic() + 10
    try:
        while time.monotonic() < deadline:
            statuses = {store.get(j).status for j in job_ids}
            if statuses.isdisjoint({JobStatus.PENDING, JobStatus.RUNNING}):
                return
            time.sleep(0.02)
        raise AssertionError("worker did not finish jobs in time")
    finally:
        worker.stop()


class TestWorkerFlows:
    def test_success_records_verdict_and_progress(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        job_id = enqueue(store, config)

        def runner(input_path, preset_path, output_dir, on_progress):
            on_progress("[1/2] probing")
            on_progress("[2/2] rendering")
            return "WARNING", {"passed": 5, "warnings": 1}

        run_worker_until(store, config, runner, [job_id])
        job = store.get(job_id)
        assert job.status is JobStatus.COMPLETED
        assert job.qc_status == "WARNING"  # COMPLETED job + media verdict coexist
        assert [e["label"] for e in job.progress] == ["[1/2] probing", "[2/2] rendering"]

    def test_jobs_run_strictly_serially_in_fifo_order(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        first = enqueue(store, config, "a.mov")
        second = enqueue(store, config, "b.mov")
        order: list[str] = []

        def runner(input_path, preset_path, output_dir, on_progress):
            order.append(Path(input_path).name)
            return "PASS", {}

        run_worker_until(store, config, runner, [first, second])
        assert order == ["a.mov", "b.mov"]

    def test_pipeline_error_fails_job_with_reason(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        job_id = enqueue(store, config)

        def runner(*args, **kwargs):
            raise DeepdubQCError("ffprobe could not read this file")

        run_worker_until(store, config, runner, [job_id])
        job = store.get(job_id)
        assert job.status is JobStatus.FAILED
        assert job.error_reason == "pipeline_error"
        assert "ffprobe" in (job.error_message or "")

    def test_crash_is_contained_as_internal_error(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        job_id = enqueue(store, config)

        def runner(*args, **kwargs):
            raise ValueError("boom")

        run_worker_until(store, config, runner, [job_id])
        assert store.get(job_id).error_reason == "internal_error"

    def test_cancel_flag_cancels_between_stages(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        job_id = enqueue(store, config)

        def runner(input_path, preset_path, output_dir, on_progress):
            store.request_cancel(job_id)  # operator clicks Cancel mid-run
            on_progress("stage after cancel")  # raises JobCancelledError
            raise AssertionError("unreachable")

        run_worker_until(store, config, runner, [job_id])
        assert store.get(job_id).status is JobStatus.CANCELLED

    def test_timeout_signal_fails_with_timeout_reason(self, tmp_path: Path) -> None:
        config = make_config(tmp_path, max_job_duration_minutes=1)
        store = JobStore(config.paths.database)
        job_id = enqueue(store, config)

        def runner(*args, **kwargs):
            raise JobTimeoutError("deadline")

        run_worker_until(store, config, runner, [job_id])
        job = store.get(job_id)
        assert job.status is JobStatus.FAILED
        assert job.error_reason == "timeout"
        assert "60" in (job.error_message or "") or "1 minute" in (job.error_message or "")

    def test_cancel_error_from_callback_cancels(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        job_id = enqueue(store, config)

        def runner(*args, **kwargs):
            raise JobCancelledError("cancelled")

        run_worker_until(store, config, runner, [job_id])
        assert store.get(job_id).status is JobStatus.CANCELLED

    def test_start_recovers_orphans(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        job_id = enqueue(store, config)
        store.claim_next()  # simulate a previous process that died mid-run

        worker = Worker(store, config, runner=lambda *a, **k: ("PASS", {}))
        worker.start()
        worker.stop()
        assert store.get(job_id).status is JobStatus.FAILED
        assert store.get(job_id).error_reason == "interrupted_by_restart"


@pytest.fixture(scope="module")
def catalog():
    return build_catalog(REPO_ROOT / "presets")


class TestValidation:
    def make(self, tmp_path: Path, **jobs) -> tuple[ServerConfig, JobStore]:
        config = make_config(tmp_path, **jobs)
        return config, JobStore(config.paths.database)

    def submit(self, config, store, catalog, path: str, **kwargs):
        defaults = dict(
            raw_path=path,
            preset_id="marimba_deliver_audio",
            preset_version="1.0.0",
            requested_by="baruch",
            config=config,
            store=store,
            catalog=catalog,
        )
        defaults.update(kwargs)
        return validate_submission(**defaults)

    def test_valid_submission_resolves_everything(self, tmp_path: Path, catalog) -> None:
        config, store = self.make(tmp_path)
        media = config.paths.media_roots[0] / "ep.wav"
        media.write_bytes(b"x" * 10)
        result = self.submit(config, store, catalog, str(media))
        assert result.ok, result.errors
        assert result.submission is not None
        assert result.submission.input_size_bytes == 10
        assert result.submission.preset_path.endswith("deliver_audio_v1.yaml")

    def test_missing_file_is_e1(self, tmp_path: Path, catalog) -> None:
        config, store = self.make(tmp_path)
        result = self.submit(config, store, catalog, str(tmp_path / "media" / "no.wav"))
        assert [e.code for e in result.errors] == ["E1"]

    def test_path_outside_roots_is_e2(self, tmp_path: Path, catalog) -> None:
        config, store = self.make(tmp_path)
        outside = tmp_path / "outside.wav"
        outside.write_bytes(b"x")
        result = self.submit(config, store, catalog, str(outside))
        assert [e.code for e in result.errors] == ["E2"]
        assert "allowed media root" in result.errors[0].message

    def test_oversize_file_is_e3(self, tmp_path: Path, catalog) -> None:
        config, store = self.make(tmp_path, max_file_size_gb=1)
        media = config.paths.media_roots[0] / "big.wav"
        with media.open("wb") as handle:  # sparse file: size without disk usage
            handle.seek(2 * 1024**3)
            handle.write(b"\0")
        result = self.submit(config, store, catalog, str(media))
        assert [e.code for e in result.errors] == ["E3"]

    def test_unknown_preset_is_e4(self, tmp_path: Path, catalog) -> None:
        config, store = self.make(tmp_path)
        media = config.paths.media_roots[0] / "ep.wav"
        media.write_bytes(b"x")
        result = self.submit(
            config, store, catalog, str(media), preset_id="nope", preset_version="9.9.9"
        )
        assert [e.code for e in result.errors] == ["E4"]

    def test_empty_requested_by_is_error(self, tmp_path: Path, catalog) -> None:
        config, store = self.make(tmp_path)
        media = config.paths.media_roots[0] / "ep.wav"
        media.write_bytes(b"x")
        result = self.submit(config, store, catalog, str(media), requested_by="   ")
        assert any(e.field == "requested_by" for e in result.errors)

    def test_duplicate_inflight_warn_confirm_and_override(self, tmp_path: Path, catalog) -> None:
        config, store = self.make(tmp_path)
        media = config.paths.media_roots[0] / "ep.wav"
        media.write_bytes(b"x" * 10)
        first = self.submit(config, store, catalog, str(media))
        store.enqueue(first.submission, jobs_root=config.paths.jobs_root, max_queue_length=20)

        again = self.submit(config, store, catalog, str(media))
        assert not again.ok
        assert again.duplicate is not None  # E5: warn + confirm

        overridden = self.submit(config, store, catalog, str(media), duplicate_override=True)
        assert overridden.ok

    def test_duplicate_reject_policy_is_hard_error(self, tmp_path: Path, catalog) -> None:
        config, store = self.make(tmp_path, duplicate_inflight_policy="reject")
        media = config.paths.media_roots[0] / "ep.wav"
        media.write_bytes(b"x" * 10)
        first = self.submit(config, store, catalog, str(media))
        store.enqueue(first.submission, jobs_root=config.paths.jobs_root, max_queue_length=20)
        again = self.submit(config, store, catalog, str(media))
        assert [e.code for e in again.errors] == ["E5"]


class TestCatalog:
    def test_repo_presets_are_catalogued(self, catalog) -> None:
        ids = {(p.preset_id, p.version) for p in catalog}
        assert ("marimba_deliver_audio", "1.0.0") in ids
        assert ("alphorn_ad_full_mix", "1.0.0") in ids
        clients = [p.client for p in catalog]
        assert clients == sorted(clients)  # grouped for the picker
