"""Server configuration: one YAML file -> one validated ServerConfig.

Why: on a shared host, "which config is live" must have exactly one answer
(docs/server-config-spec.md, principle 1). The YAML is parsed into a typed
Pydantic model; unknown keys are errors (typo protection); invalid values
abort startup naming the key and constraint. `DEEPDUB_QC_` environment
variables override individual keys (double underscore = section separator)
and are reported so startup logs can echo them.

Inputs: a YAML path (plus os.environ). Outputs: ``LoadedConfig`` with the
validated model, startup warnings, and applied overrides.
Side effects: none here — startup checks that touch the filesystem live in
``validate_runtime`` so unit tests can cover pure parsing separately.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PureWindowsPath
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from deepdub_qc.exceptions import DeepdubQCError

ENV_PREFIX = "DEEPDUB_QC_"
SUPPORTED_SCHEMA_MAJOR = 1


class ConfigError(DeepdubQCError):
    """The server configuration is invalid; the server must not start."""


class DuplicatePolicy(StrEnum):
    WARN_CONFIRM = "warn_confirm"
    REJECT = "reject"
    ALLOW = "allow"


class PdfRendererKind(StrEnum):
    PLAYWRIGHT = "playwright"
    WEASYPRINT = "weasyprint"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")  # unknown keys are errors


class ServerSection(_Section):
    host: str = "127.0.0.1"
    port: Annotated[int, Field(ge=1024, le=65535)] = 8571
    max_gui_sessions: Annotated[int, Field(ge=1)] = 2
    gui_session_ttl_minutes: Annotated[int, Field(ge=1)] = 15
    queue_poll_interval_seconds: Annotated[int, Field(ge=1, le=60)] = 2


class JobsSection(_Section):
    max_concurrent_jobs: Annotated[int, Field(ge=1)] = 1
    max_queue_length: Annotated[int, Field(ge=1)] = 20
    max_job_duration_minutes: Annotated[int, Field(ge=1)] = 240
    max_file_size_gb: Annotated[int, Field(ge=1)] = 150
    duplicate_inflight_policy: DuplicatePolicy = DuplicatePolicy.WARN_CONFIRM


class PathsSection(_Section):
    media_roots: Annotated[list[Path], Field(min_length=1)]
    jobs_root: Path = Path("C:/DeepdubQC/data/jobs")
    database: Path = Path("C:/DeepdubQC/data/qc.sqlite3")
    presets_root: Path = Path("presets")


class ToolsSection(_Section):
    ffmpeg_path: Path
    ffprobe_path: Path
    expected_ffmpeg_version: str | None = None
    subprocess_timeout_seconds: Annotated[int, Field(ge=1)] = 600


class PdfSection(_Section):
    renderer: PdfRendererKind = PdfRendererKind.PLAYWRIGHT
    render_timeout_seconds: Annotated[int, Field(ge=1)] = 120


class LoggingSection(_Section):
    level: LogLevel = LogLevel.INFO
    directory: Path = Path("C:/DeepdubQC/logs/app")
    retention_days: Annotated[int, Field(ge=1)] = 30


class ServerConfig(_Section):
    """The complete Phase 3.5 server configuration (docs/server-config-spec.md)."""

    schema_version: int
    server: ServerSection = ServerSection()
    jobs: JobsSection = JobsSection()
    paths: PathsSection
    tools: ToolsSection
    pdf: PdfSection = PdfSection()
    logging: LoggingSection = LoggingSection()


@dataclass(frozen=True)
class LoadedConfig:
    config: ServerConfig
    warnings: list[str] = field(default_factory=list)
    env_overrides: list[str] = field(default_factory=list)


def _is_unc(path: Path) -> bool:
    return str(PureWindowsPath(path)).startswith("\\\\") or str(path).startswith("//")


def _apply_env_overrides(data: dict[str, Any], environ: dict[str, str]) -> list[str]:
    """Apply DEEPDUB_QC_SECTION__KEY=value overrides in place; return applied names."""
    applied = []
    for name, raw in sorted(environ.items()):
        if not name.startswith(ENV_PREFIX):
            continue
        parts = name[len(ENV_PREFIX) :].lower().split("__")
        if len(parts) != 2:
            continue  # only section__key form is supported
        section, key = parts
        data.setdefault(section, {})
        if not isinstance(data[section], dict):
            raise ConfigError(f"Env override {name} targets non-section key {section!r}")
        data[section][key] = raw
        applied.append(name)
    return applied


def load_config(path: Path, environ: dict[str, str] | None = None) -> LoadedConfig:
    """Parse and validate the server YAML (pure: no filesystem probes here).

    Raises ConfigError with an actionable message on any problem.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Cannot read server config {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Server config {path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"Server config {path} must be a YAML mapping")

    env_overrides = _apply_env_overrides(raw, environ if environ is not None else dict(os.environ))

    schema_version = raw.get("schema_version")
    if not isinstance(schema_version, int) or schema_version != SUPPORTED_SCHEMA_MAJOR:
        raise ConfigError(
            f"Unsupported config schema_version {schema_version!r}; "
            f"this build supports {SUPPORTED_SCHEMA_MAJOR}. See upgrade notes."
        )

    try:
        config = ServerConfig.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError; re-raise typed
        raise ConfigError(f"Invalid server config {path}: {exc}") from exc

    warnings = []
    if config.server.host not in ("127.0.0.1", "localhost", "::1"):
        warnings.append(
            f"server.host={config.server.host!r} is not loopback and the server has "
            "NO AUTHENTICATION - anyone who can reach this port can submit jobs."
        )
    if config.jobs.max_concurrent_jobs > 1:
        warnings.append(
            f"jobs.max_concurrent_jobs={config.jobs.max_concurrent_jobs}: concurrent "
            "jobs on one host contend for disk/CPU and blur per-job runtime metrics."
        )
    if _is_unc(config.paths.jobs_root):
        warnings.append(
            f"paths.jobs_root={config.paths.jobs_root} is a network path; job output "
            "is write-heavy - local disk strongly recommended."
        )
    if _is_unc(config.paths.database):
        raise ConfigError(
            f"paths.database={config.paths.database} is a network path: SQLite on "
            "SMB is a corruption risk. Use a local disk."
        )
    return LoadedConfig(config=config, warnings=warnings, env_overrides=env_overrides)


def validate_runtime(loaded: LoadedConfig) -> list[str]:
    """Filesystem/tool startup checks (docs/server-config-spec.md section 4).

    Returns additional warnings; raises ConfigError on fatal problems.
    Separated from load_config so parsing is unit-testable without a real
    filesystem layout.
    """
    config = loaded.config
    warnings = []

    usable_roots = 0
    for root in config.paths.media_roots:
        if root.is_dir():
            usable_roots += 1
        else:
            warnings.append(f"media root not currently reachable: {root}")
    if usable_roots == 0:
        raise ConfigError(
            "No usable media_roots: none of the configured paths are reachable "
            f"({', '.join(str(r) for r in config.paths.media_roots)})"
        )

    for name, tool in (
        ("ffmpeg_path", config.tools.ffmpeg_path),
        ("ffprobe_path", config.tools.ffprobe_path),
    ):
        if not tool.is_file():
            raise ConfigError(f"tools.{name} does not exist: {tool}")

    if config.tools.expected_ffmpeg_version is not None:
        from deepdub_qc.utils.subprocess import ToolError, run_tool  # noqa: PLC0415

        try:
            result = run_tool([str(config.tools.ffmpeg_path), "-version"], timeout=30.0)
        except ToolError as exc:
            raise ConfigError(f"Cannot run ffmpeg for version check: {exc}") from exc
        first_line = result.stdout.splitlines()[0] if result.stdout else ""
        if config.tools.expected_ffmpeg_version not in first_line:
            raise ConfigError(
                f"FFmpeg version mismatch (determinism guard, ADR-008): expected "
                f"{config.tools.expected_ffmpeg_version!r} in {first_line!r}"
            )
    return warnings
