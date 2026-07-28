"""Verdict routing + completion webhooks (docs/watch-folders-spec.md section 10, ADR-028)."""

import json
from pathlib import Path

import httpx
import pytest

from deepdub_qc.server import routing
from deepdub_qc.server.config import (
    ConfigError,
    LoadedConfig,
    RoutingAction,
    ServerConfig,
    validate_runtime,
)
from deepdub_qc.server.routing import (
    PostCompletion,
    WebhookDeliveryError,
    action_for_verdict,
    deliver_webhook,
    folder_for_job,
    route_file,
    unique_destination,
)
from deepdub_qc.server.store import JobRecord, JobStore, JobSubmission

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def make_config(tmp_path: Path, **folder_overrides) -> ServerConfig:
    """One watch folder with pass/reject move routing inside one media root."""
    media = tmp_path / "media"
    media.mkdir(exist_ok=True)
    drop = media / "drop"
    drop.mkdir(exist_ok=True)
    (media / "pass").mkdir(exist_ok=True)
    (media / "reject").mkdir(exist_ok=True)
    folder = {
        "name": "test-drop",
        "path": str(drop),
        "preset": "marimba_deliver_audio@1.0.0",
        "extensions": ["wav"],
        "on_pass": {"move_to": str(media / "pass")},
        "on_reject": {"move_to": str(media / "reject")},
        **folder_overrides,
    }
    return ServerConfig.model_validate(
        {
            "schema_version": 1,
            "paths": {
                "media_roots": [str(media)],
                "jobs_root": str(tmp_path / "jobs"),
                "database": str(tmp_path / "qc.sqlite3"),
                "presets_root": str(REPO_ROOT / "presets"),
            },
            "tools": {"ffmpeg_path": "/bin/ls", "ffprobe_path": "/bin/ls"},
            "watch_folders": [folder],
        }
    )


def finish_job(
    store: JobStore,
    config: ServerConfig,
    name: str = "a.wav",
    qc_status: str = "PASS",
    requested_by: str = "watch:test-drop",
    outcome: str = "completed",
) -> JobRecord:
    """Enqueue a file from the drop folder and drive it to a terminal state."""
    media_file = Path(config.watch_folders[0].path) / name
    if not media_file.exists():
        media_file.write_bytes(b"x" * 64)
    submission = JobSubmission(
        input_path=str(media_file),
        input_size_bytes=64,
        preset_id="p",
        preset_version="1.0.0",
        preset_path="unused.yaml",
        requested_by=requested_by,
    )
    record = store.enqueue(submission, jobs_root=config.paths.jobs_root, max_queue_length=20)
    store.claim_next()
    if outcome == "completed":
        store.mark_completed(record.job_id, qc_status, {"overall_status": qc_status})
    else:
        store.mark_failed(record.job_id, "pipeline_error", "boom")
    return store.get(record.job_id)


def notes(store: JobStore, job_id: str) -> list[str]:
    return [event["label"] for event in store.get(job_id).progress]


class TestConfigValidation:
    def test_action_requires_exactly_one_destination(self, tmp_path: Path) -> None:
        with pytest.raises(Exception, match="exactly one"):
            RoutingAction.model_validate({"move_to": str(tmp_path), "copy_to": str(tmp_path)})
        with pytest.raises(Exception, match="exactly one"):
            RoutingAction.model_validate({})

    def test_webhook_url_must_be_http(self, tmp_path: Path) -> None:
        with pytest.raises(Exception, match="pattern"):
            make_config(tmp_path, webhook_url="ftp://example.internal/hook")

    def test_destination_equal_to_scanned_path_refused(self, tmp_path: Path) -> None:
        drop = tmp_path / "media" / "drop"
        with pytest.raises(Exception, match="re-enqueued"):
            make_config(tmp_path, on_pass={"move_to": str(drop)})

    def test_recursive_destination_inside_scanned_area_refused(self, tmp_path: Path) -> None:
        sub = tmp_path / "media" / "drop" / "pass"
        with pytest.raises(Exception, match="re-enqueued"):
            make_config(tmp_path, recursive=True, on_pass={"move_to": str(sub)})

    def test_non_recursive_subfolder_destination_allowed(self, tmp_path: Path) -> None:
        sub = tmp_path / "media"
        config = make_config(tmp_path, on_pass={"move_to": str(sub / "drop" / "done")})
        (sub / "drop" / "done").mkdir()
        assert validate_runtime(LoadedConfig(config=config)) == []

    def test_missing_destination_directory_refused(self, tmp_path: Path) -> None:
        config = make_config(tmp_path, on_pass={"move_to": str(tmp_path / "media" / "nope")})
        with pytest.raises(ConfigError, match="not a directory"):
            validate_runtime(LoadedConfig(config=config))

    def test_destination_outside_media_roots_refused(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        config = make_config(tmp_path, on_pass={"move_to": str(outside)})
        with pytest.raises(ConfigError, match="outside every configured media root"):
            validate_runtime(LoadedConfig(config=config))


class TestVerdictMapping:
    def test_verdicts_map_to_their_actions(self, tmp_path: Path) -> None:
        entry = make_config(tmp_path).watch_folders[0]
        assert action_for_verdict(entry, "PASS") is entry.on_pass
        assert action_for_verdict(entry, "FAIL") is entry.on_reject

    def test_unset_verdict_has_no_fallback(self, tmp_path: Path) -> None:
        entry = make_config(tmp_path).watch_folders[0]  # on_warning unset
        assert action_for_verdict(entry, "WARNING") is None

    def test_error_never_routes(self, tmp_path: Path) -> None:
        entry = make_config(tmp_path).watch_folders[0]
        assert action_for_verdict(entry, "ERROR") is None
        assert action_for_verdict(entry, None) is None


class TestFolderForJob:
    def test_manual_jobs_have_no_folder(self, tmp_path: Path) -> None:
        assert folder_for_job("baruch", make_config(tmp_path)) is None

    def test_removed_folder_has_no_policy(self, tmp_path: Path) -> None:
        assert folder_for_job("watch:gone", make_config(tmp_path)) is None

    def test_watch_jobs_resolve_their_folder(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        assert folder_for_job("watch:test-drop", config) is config.watch_folders[0]


class TestRouteFile:
    def test_move_relocates_the_source(self, tmp_path: Path) -> None:
        source = tmp_path / "a.wav"
        source.write_bytes(b"x")
        dest_dir = tmp_path / "pass"
        dest_dir.mkdir()
        action = RoutingAction.model_validate({"move_to": str(dest_dir)})
        verb, destination = route_file(source, action)
        assert verb == "moved"
        assert destination == dest_dir / "a.wav"
        assert destination.exists() and not source.exists()

    def test_copy_keeps_the_source(self, tmp_path: Path) -> None:
        source = tmp_path / "a.wav"
        source.write_bytes(b"x")
        dest_dir = tmp_path / "pass"
        dest_dir.mkdir()
        action = RoutingAction.model_validate({"copy_to": str(dest_dir)})
        verb, destination = route_file(source, action)
        assert verb == "copied"
        assert destination.exists() and source.exists()

    def test_collisions_get_numeric_suffixes(self, tmp_path: Path) -> None:
        (tmp_path / "a.wav").write_bytes(b"1")
        (tmp_path / "a_1.wav").write_bytes(b"2")
        assert unique_destination(tmp_path, "a.wav") == tmp_path / "a_2.wav"
        assert unique_destination(tmp_path, "b.wav") == tmp_path / "b.wav"


class TestPostCompletion:
    def test_pass_verdict_moves_the_input(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        job = finish_job(store, config, qc_status="PASS")
        PostCompletion(store, config).handle(job)
        assert not Path(job.input_path).exists()
        assert (tmp_path / "media" / "pass" / "a.wav").exists()
        assert any("routing: moved" in note for note in notes(store, job.job_id))

    def test_fail_verdict_routes_to_reject(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        job = finish_job(store, config, qc_status="FAIL")
        PostCompletion(store, config).handle(job)
        assert (tmp_path / "media" / "reject" / "a.wav").exists()

    def test_unset_warning_leaves_file_in_place(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        job = finish_job(store, config, qc_status="WARNING")
        PostCompletion(store, config).handle(job)
        assert Path(job.input_path).exists()
        assert notes(store, job.job_id) == []

    def test_error_status_never_routes(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        job = finish_job(store, config, qc_status="ERROR")
        PostCompletion(store, config).handle(job)
        assert Path(job.input_path).exists()

    def test_failed_job_leaves_file_for_investigation(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        job = finish_job(store, config, outcome="failed")
        PostCompletion(store, config).handle(job)
        assert Path(job.input_path).exists()

    def test_manual_job_is_untouched(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        job = finish_job(store, config, requested_by="baruch")
        PostCompletion(store, config).handle(job)
        assert Path(job.input_path).exists()
        assert notes(store, job.job_id) == []

    def test_routing_failure_degrades_to_a_note(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        job = finish_job(store, config, qc_status="PASS")
        Path(job.input_path).unlink()  # grabbed by someone between QC and routing
        PostCompletion(store, config).handle(job)  # must not raise
        assert any("routing failed" in note for note in notes(store, job.job_id))


def capture_transport(responses: list[httpx.Response]) -> tuple[httpx.MockTransport, list]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return responses[min(len(requests), len(responses)) - 1]

    return httpx.MockTransport(handler), requests


class TestWebhook:
    def test_completed_job_posts_report_verbatim(self, tmp_path: Path) -> None:
        config = make_config(tmp_path, webhook_url="https://example.internal/hooks/qc")
        store = JobStore(config.paths.database)
        job = finish_job(store, config, qc_status="PASS")
        report = {"overall_status": "PASS", "findings": []}
        output_dir = Path(job.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")

        transport, requests = capture_transport([httpx.Response(200)])
        PostCompletion(store, config, transport=transport).handle(job)

        assert len(requests) == 1
        payload = json.loads(requests[0].content)
        assert payload["event"] == "job.completed"
        assert payload["qc_status"] == "PASS"
        assert payload["folder"] == "test-drop"
        assert payload["report"] == report
        assert payload["routed_to"] == str(tmp_path / "media" / "pass" / "a.wav")
        assert requests[0].headers["X-Deepdub-QC-Event"] == "job.completed"
        assert any(
            "webhook: delivered to example.internal (HTTP 200)" in note
            for note in notes(store, job.job_id)
        )

    def test_failed_job_notifies_without_report(self, tmp_path: Path) -> None:
        config = make_config(tmp_path, webhook_url="https://example.internal/hooks/qc")
        store = JobStore(config.paths.database)
        job = finish_job(store, config, outcome="failed")
        transport, requests = capture_transport([httpx.Response(200)])
        PostCompletion(store, config, transport=transport).handle(job)
        payload = json.loads(requests[0].content)
        assert payload["event"] == "job.failed"
        assert payload["error_reason"] == "pipeline_error"
        assert payload["report"] is None

    def test_server_errors_retry_then_succeed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(routing, "WEBHOOK_RETRY_WAITS_SECONDS", (0.0, 0.0))
        transport, requests = capture_transport(
            [httpx.Response(500), httpx.Response(200), httpx.Response(200)]
        )
        status = deliver_webhook("https://h.internal/x", {"event": "job.completed"}, transport)
        assert status == 200
        assert len(requests) == 2

    def test_client_errors_never_retry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(routing, "WEBHOOK_RETRY_WAITS_SECONDS", (0.0, 0.0))
        transport, requests = capture_transport([httpx.Response(404)])
        with pytest.raises(WebhookDeliveryError, match="HTTP 404"):
            deliver_webhook("https://h.internal/x", {"event": "job.completed"}, transport)
        assert len(requests) == 1

    def test_delivery_failure_notes_host_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(routing, "WEBHOOK_RETRY_WAITS_SECONDS", ())
        secret_url = "https://example.internal/hooks/qc?token=SECRET"
        config = make_config(tmp_path, webhook_url=secret_url)
        store = JobStore(config.paths.database)
        job = finish_job(store, config, qc_status="PASS")

        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        PostCompletion(store, config, transport=httpx.MockTransport(refuse)).handle(job)
        failure_notes = [note for note in notes(store, job.job_id) if "webhook" in note]
        assert failure_notes and "delivery failed" in failure_notes[0]
        assert all("SECRET" not in note and "token" not in note for note in failure_notes)
