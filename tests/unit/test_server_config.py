"""Server config loading/validation (docs/server-config-spec.md)."""

from pathlib import Path

import pytest

from deepdub_qc.server.config import (
    ConfigError,
    DuplicatePolicy,
    load_config,
    validate_runtime,
)

MINIMAL = """\
schema_version: 1
paths:
  media_roots:
    - '{root}'
tools:
  ffmpeg_path: '{ffmpeg}'
  ffprobe_path: '{ffprobe}'
"""


def write_config(tmp_path: Path, body: str | None = None, **extra: str) -> Path:
    media = tmp_path / "media"
    media.mkdir(exist_ok=True)
    ffmpeg = tmp_path / "ffmpeg"
    ffprobe = tmp_path / "ffprobe"
    ffmpeg.write_text("")
    ffprobe.write_text("")
    text = (body or MINIMAL).format(root=media, ffmpeg=ffmpeg, ffprobe=ffprobe, **extra)
    target = tmp_path / "server.yaml"
    target.write_text(text, encoding="utf-8")
    return target


class TestLoadConfig:
    def test_minimal_config_gets_documented_defaults(self, tmp_path: Path) -> None:
        loaded = load_config(write_config(tmp_path), environ={})
        c = loaded.config
        assert c.server.port == 8571
        assert c.server.max_gui_sessions == 2
        assert c.jobs.max_concurrent_jobs == 1
        assert c.jobs.max_file_size_gb == 150
        assert c.jobs.duplicate_inflight_policy is DuplicatePolicy.WARN_CONFIRM
        assert loaded.warnings == []
        assert loaded.env_overrides == []

    def test_unknown_key_is_an_error(self, tmp_path: Path) -> None:
        path = write_config(tmp_path, MINIMAL + "server:\n  prot: 9000\n")
        with pytest.raises(ConfigError, match="prot"):
            load_config(path, environ={})

    def test_missing_required_key_is_an_error(self, tmp_path: Path) -> None:
        path = tmp_path / "server.yaml"
        path.write_text("schema_version: 1\npaths:\n  media_roots: ['x']\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="tools"):
            load_config(path, environ={})

    def test_wrong_schema_version_rejected(self, tmp_path: Path) -> None:
        path = write_config(tmp_path, MINIMAL.replace("schema_version: 1", "schema_version: 2"))
        with pytest.raises(ConfigError, match="schema_version"):
            load_config(path, environ={})

    def test_unc_database_is_fatal(self, tmp_path: Path) -> None:
        # Forward-slash UNC form; the loader treats // and \\\\ alike.
        body = MINIMAL.replace("tools:", "  database: '//nas/share/qc.sqlite3'\ntools:")
        with pytest.raises(ConfigError, match="SQLite on"):
            load_config(write_config(tmp_path, body), environ={})

    def test_unc_jobs_root_warns(self, tmp_path: Path) -> None:
        body = MINIMAL.replace("tools:", "  jobs_root: '//nas/share/jobs'\ntools:")
        loaded = load_config(write_config(tmp_path, body), environ={})
        assert any("write-heavy" in w for w in loaded.warnings)

    def test_non_loopback_host_warns(self, tmp_path: Path) -> None:
        body = MINIMAL + "server:\n  host: 0.0.0.0\n"
        loaded = load_config(write_config(tmp_path, body), environ={})
        assert any("NO AUTHENTICATION" in w for w in loaded.warnings)

    def test_concurrency_above_one_warns(self, tmp_path: Path) -> None:
        body = MINIMAL + "jobs:\n  max_concurrent_jobs: 2\n"
        loaded = load_config(write_config(tmp_path, body), environ={})
        assert any("contend" in w for w in loaded.warnings)

    def test_env_override_applies_and_is_reported(self, tmp_path: Path) -> None:
        loaded = load_config(write_config(tmp_path), environ={"DEEPDUB_QC_SERVER__PORT": "9000"})
        assert loaded.config.server.port == 9000
        assert loaded.env_overrides == ["DEEPDUB_QC_SERVER__PORT"]

    def test_invalid_port_names_constraint(self, tmp_path: Path) -> None:
        loaded_path = write_config(tmp_path, MINIMAL + "server:\n  port: 80\n")
        with pytest.raises(ConfigError, match="port"):
            load_config(loaded_path, environ={})


class TestValidateRuntime:
    def test_unreachable_root_warns_all_unreachable_fatal(self, tmp_path: Path) -> None:
        loaded = load_config(write_config(tmp_path), environ={})
        assert validate_runtime(loaded) == []

        body = MINIMAL.replace("{root}", str(tmp_path / "missing"))
        loaded = load_config(write_config(tmp_path, body), environ={})
        with pytest.raises(ConfigError, match="No usable media_roots"):
            validate_runtime(loaded)

    def test_missing_tool_is_fatal(self, tmp_path: Path) -> None:
        loaded = load_config(write_config(tmp_path), environ={})
        loaded.config.tools.ffmpeg_path.unlink()
        with pytest.raises(ConfigError, match="ffmpeg_path"):
            validate_runtime(loaded)
