"""Watch folders: stability, dedup/re-drop, failure degradation (spec sections 2-5)."""

import os
from pathlib import Path

import pytest

from deepdub_qc.server.config import ConfigError, ServerConfig, validate_runtime
from deepdub_qc.server.store import JobStatus, JobStore
from deepdub_qc.server.watch import MAX_DEFER_ATTEMPTS, Watcher, scan_folder

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def make_config(tmp_path: Path, **folder_overrides) -> ServerConfig:
    media = tmp_path / "media"
    media.mkdir(exist_ok=True)
    drop = media / "drop"
    drop.mkdir(exist_ok=True)
    folder = {
        "name": "test-drop",
        "path": str(drop),
        "preset": "marimba_deliver_audio@1.0.0",
        "extensions": ["wav"],
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


def drop_file(config: ServerConfig, name: str, content: bytes = b"x" * 64, mtime: float = 1000.0):
    target = Path(config.watch_folders[0].path) / name
    target.write_bytes(content)
    os.utime(target, (mtime, mtime))
    return target


def settled(config: ServerConfig) -> float:
    """A 'now' comfortably past the settle window for mtime=1000."""
    return 1000.0 + config.watch_folders[0].settle_seconds + 60


class TestConfig:
    def test_duplicate_names_rejected(self, tmp_path: Path) -> None:
        media = tmp_path / "media"
        media.mkdir()
        folder = {
            "name": "same",
            "path": str(media),
            "preset": "p@1.0.0",
            "extensions": ["wav"],
        }
        with pytest.raises(Exception, match="unique"):
            ServerConfig.model_validate(
                {
                    "schema_version": 1,
                    "paths": {
                        "media_roots": [str(media)],
                        "jobs_root": str(tmp_path / "jobs"),
                        "database": str(tmp_path / "db"),
                    },
                    "tools": {"ffmpeg_path": "/bin/ls", "ffprobe_path": "/bin/ls"},
                    "watch_folders": [folder, dict(folder)],
                }
            )

    def test_extensions_normalized(self, tmp_path: Path) -> None:
        config = make_config(tmp_path, extensions=[".WAV", "Mov"])
        assert config.watch_folders[0].extensions == ["wav", "mov"]

    def test_folder_outside_media_roots_refused(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        config = config.model_copy(
            update={"watch_folders": [config.watch_folders[0].model_copy(update={"path": outside})]}
        )
        from deepdub_qc.server.config import LoadedConfig  # noqa: PLC0415

        with pytest.raises(ConfigError, match="outside every"):
            validate_runtime(LoadedConfig(config=config))

    def test_unknown_preset_is_fatal_at_startup(self, tmp_path: Path) -> None:
        config = make_config(tmp_path, preset="no_such_preset@9.9.9")
        store = JobStore(config.paths.database)
        with pytest.raises(ValueError, match="no_such_preset"):
            Watcher(store, config)


class TestStability:
    def test_new_file_needs_two_scans(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        watcher = Watcher(store, config)
        drop_file(config, "a.wav")
        now = settled(config)
        assert watcher.scan_once(now) == 0, "first sighting must never enqueue"
        assert watcher.scan_once(now + config.watch_folders[0].poll_seconds) == 1

    def test_growing_file_is_not_enqueued(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        watcher = Watcher(store, config)
        drop_file(config, "a.wav", b"x" * 10)
        now = settled(config)
        watcher.scan_once(now)
        drop_file(config, "a.wav", b"x" * 20)  # still copying: bytes changed
        assert watcher.scan_once(now + 10) == 0

    def test_settle_window_respected(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        watcher = Watcher(store, config)
        drop_file(config, "a.wav", mtime=1000.0)
        settle = config.watch_folders[0].settle_seconds
        watcher.scan_once(1000.0 + 1)
        assert watcher.scan_once(1000.0 + settle - 5) == 0, "inside settle window"
        assert watcher.scan_once(1000.0 + settle + 30) == 1, "settled after the window"

    def test_extension_filter(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        watcher = Watcher(store, config)
        drop_file(config, "notes.txt")
        now = settled(config)
        watcher.scan_once(now)
        assert watcher.scan_once(now + 10) == 0

    def test_subfolders_ignored_by_default(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        staged = Path(config.watch_folders[0].path) / "staging"
        staged.mkdir()
        (staged / "a.wav").write_bytes(b"x")
        assert scan_folder(Path(config.watch_folders[0].path), ["wav"], recursive=False) == []
        assert len(scan_folder(Path(config.watch_folders[0].path), ["wav"], recursive=True)) == 1


class TestDedupAndRedrop:
    def test_enqueued_once_with_watch_provenance(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        watcher = Watcher(store, config)
        drop_file(config, "a.wav")
        now = settled(config)
        watcher.scan_once(now)
        watcher.scan_once(now + 10)
        assert watcher.scan_once(now + 20) == 0, "already enqueued"
        jobs = store.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].status is JobStatus.PENDING
        assert jobs[0].requested_by == "watch:test-drop"

    def test_restart_does_not_requeue(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        watcher = Watcher(store, config)
        drop_file(config, "a.wav")
        now = settled(config)
        watcher.scan_once(now)
        watcher.scan_once(now + 10)
        restarted = Watcher(store, config)  # fresh instance, same persistent store
        restarted.scan_once(now + 20)
        assert restarted.scan_once(now + 30) == 0
        assert len(store.list_jobs()) == 1

    def test_redelivery_enqueues_new_job(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        watcher = Watcher(store, config)
        drop_file(config, "a.wav", b"first version!!!", mtime=1000.0)
        now = settled(config)
        watcher.scan_once(now)
        watcher.scan_once(now + 10)
        drop_file(config, "a.wav", b"second version!!", mtime=now + 20)
        redrop_now = now + 20 + config.watch_folders[0].settle_seconds + 60
        watcher.scan_once(redrop_now)
        assert watcher.scan_once(redrop_now + 10) == 1
        jobs = store.list_jobs()
        assert len(jobs) == 2
        assert jobs[0].duplicate_override is True, "re-drop must bypass the confirm flow"


class TestDegradation:
    def test_unreachable_folder_sets_error_and_recovers(self, tmp_path: Path) -> None:
        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        watcher = Watcher(store, config)
        drop = Path(config.watch_folders[0].path)
        drop.rename(tmp_path / "media" / "gone")
        watcher.scan_once(settled(config))
        assert "unreachable" in (watcher.status()[0].error or "")
        (tmp_path / "media" / "gone").rename(drop)
        watcher.scan_once(settled(config) + 10)
        assert watcher.status()[0].error is None

    def test_queue_full_defers_and_parks_after_max_attempts(self, tmp_path: Path) -> None:
        config = make_config(tmp_path).model_copy(deep=True)
        config.jobs.max_queue_length = 0  # type: ignore[misc]
        store = JobStore(config.paths.database)
        watcher = Watcher(store, config)
        drop_file(config, "a.wav")
        now = settled(config)
        watcher.scan_once(now)
        for tick in range(MAX_DEFER_ATTEMPTS + 2):
            watcher.scan_once(now + 10 * (tick + 1))
        assert store.count_jobs() == 0
        status = watcher.status()[0]
        assert status.deferred_count == 1, "parked file still reported"

    def test_disabled_folder_never_scans(self, tmp_path: Path) -> None:
        config = make_config(tmp_path, enabled=False)
        store = JobStore(config.paths.database)
        watcher = Watcher(store, config)
        drop_file(config, "a.wav")
        now = settled(config)
        watcher.scan_once(now)
        assert watcher.scan_once(now + 10) == 0

    def test_no_folders_is_a_noop(self, tmp_path: Path) -> None:
        config = make_config(tmp_path).model_copy(update={"watch_folders": []})
        store = JobStore(config.paths.database)
        watcher = Watcher(store, config)
        assert watcher.scan_once(1000.0) == 0
        assert watcher.status() == []
        watcher.start()  # must not spawn a thread
        watcher.stop()


class TestConsoleSurface:
    def _client(self, tmp_path: Path, with_watcher: bool):
        from fastapi.testclient import TestClient  # noqa: PLC0415

        from deepdub_qc.server.app import create_app  # noqa: PLC0415
        from deepdub_qc.server.config import LoadedConfig  # noqa: PLC0415

        config = make_config(tmp_path)
        store = JobStore(config.paths.database)
        app = create_app(LoadedConfig(config=config), store=store)
        if with_watcher:
            app.state.qc.watcher = Watcher(store, config)
        return TestClient(app)

    def test_api_lists_configured_folders(self, tmp_path: Path) -> None:
        client = self._client(tmp_path, with_watcher=True)
        body = client.get("/api/v1/watch-folders").json()
        assert len(body) == 1
        assert body[0]["name"] == "test-drop"
        assert body[0]["preset_id"] == "marimba_deliver_audio"

    def test_api_without_watcher_is_empty(self, tmp_path: Path) -> None:
        client = self._client(tmp_path, with_watcher=False)
        assert client.get("/api/v1/watch-folders").json() == []

    def test_panel_renders_folder_and_empty_state(self, tmp_path: Path) -> None:
        client = self._client(tmp_path, with_watcher=True)
        page = client.get("/watch").text
        assert "test-drop" in page
        assert "watching" in page
        empty = self._client(tmp_path, with_watcher=False).get("/watch").text
        assert "No watch folders configured" in empty
