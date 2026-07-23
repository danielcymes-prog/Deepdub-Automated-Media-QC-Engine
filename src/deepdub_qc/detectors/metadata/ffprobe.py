"""FFprobe metadata detector: Tier 1 container/stream measurements.

Why: nearly every Tier 1 check (handoff section 16) derives from container
metadata. One ffprobe invocation yields all of it; raw JSON is preserved at
raw/ffprobe.json for auditability.

Outputs: normalized Measurements. Frame rates arrive as rationals
("24000/1001") and are normalized to floats rounded to 3 decimals, with the
exact rational preserved in measurement metadata (DATA_MODEL_REVIEW item 8).
"""

from __future__ import annotations

import json
import logging
import os
from fractions import Fraction
from typing import Any

from deepdub_qc.detectors.base import Detector, DetectorRunError, QCContext
from deepdub_qc.detectors.registry import register
from deepdub_qc.models.enums import Category
from deepdub_qc.models.measurement import Measurement
from deepdub_qc.utils import ids
from deepdub_qc.utils.language import normalize_language
from deepdub_qc.utils.subprocess import ToolError, run_tool

logger = logging.getLogger(__name__)

RAW_FILENAME = "ffprobe.json"
_FFPROBE_TIMEOUT = 120.0


def parse_frame_rate(raw: str | None) -> tuple[float | None, str | None]:
    """Normalize an ffprobe rational frame rate to (float rounded 3dp, rational).

    "24000/1001" -> (23.976, "24000/1001"); "25/1" -> (25.0, "25/1").
    Returns (None, raw) for missing/degenerate values like "0/0".
    """
    if not raw:
        return None, raw
    try:
        fraction = Fraction(raw)
    except (ValueError, ZeroDivisionError):
        return None, raw
    if fraction <= 0:
        return None, raw
    return round(float(fraction), 3), raw


def normalize_container_format(format_name: str | None, extension: str) -> str | None:
    """Resolve ffprobe's demuxer list to a single container format.

    ffprobe reports demuxer groups ("mov,mp4,m4a,3gp,3g2,mj2"); presets compare
    against a single token. If the file extension appears in the group, use it;
    otherwise use the first group entry. Raw value preserved in metadata.
    """
    if format_name is None:
        return None
    parts = [p.strip() for p in format_name.split(",")]
    if extension in parts:
        return extension
    return parts[0]


def build_media_summary(parsed: dict[str, Any]) -> dict[str, Any]:
    """Reviewer-facing stream maps for QCResult.media_summary.

    Includes timecode_frame_rate (first video stream) used by renderers to
    derive HH:MM:SS:FF timecodes from canonical seconds.
    """
    fmt = parsed.get("format", {})
    streams = parsed.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    subs = [s for s in streams if s.get("codec_type") == "subtitle"]

    summary: dict[str, Any] = {
        "container": {
            "format": fmt.get("format_name"),
            "duration_seconds": _as_float(fmt.get("duration")),
            "overall_bitrate": fmt.get("bit_rate"),
        },
        "video_streams": [
            {
                "index": s.get("index"),
                "codec": s.get("codec_name"),
                "resolution": f"{s.get('width')}x{s.get('height')}",
                "frame_rate": parse_frame_rate(s.get("r_frame_rate"))[0],
                "pixel_format": s.get("pix_fmt"),
            }
            for s in video
        ],
        "audio_streams": [
            {
                "index": s.get("index"),
                "codec": s.get("codec_name"),
                "sample_rate": _as_int(s.get("sample_rate")),
                "channels": s.get("channels"),
                "channel_layout": s.get("channel_layout"),
                "language": normalize_language((s.get("tags") or {}).get("language")),
            }
            for s in audio
        ],
        "subtitle_streams": [
            {
                "index": s.get("index"),
                "codec": s.get("codec_name"),
                "language": normalize_language((s.get("tags") or {}).get("language")),
            }
            for s in subs
        ],
    }
    if video:
        fps, _ = parse_frame_rate(video[0].get("r_frame_rate"))
        if fps:
            summary["timecode_frame_rate"] = fps
    return summary


def _as_float(value: Any) -> float | None:
    try:
        return round(float(value), 3) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


@register
class FfprobeDetector(Detector):
    """Container and stream metadata via ffprobe."""

    detector_id = "metadata.ffprobe"
    detector_version = "1.2.0"  # 1.2.0: normalized language tags (backlog #33)
    parameters = (
        "audio.duration",
        "audio.video_duration_delta",
        "file.readable",
        "file.extension",
        "file.size_bytes",
        "filename.pattern",
        "container.format",
        "container.duration",
        "video.stream_count",
        "video.codec",
        "video.width",
        "video.height",
        "video.frame_rate",
        "video.pixel_format",
        "audio.stream_count",
        "audio.codec",
        "audio.sample_rate",
        "audio.channel_count",
        "audio.channel_layout",
        "audio.language",
        "subtitle.stream_count",
    )

    def is_applicable(self, context: QCContext) -> bool:
        return True  # metadata applies to every asset

    def run(self, context: QCContext) -> list[Measurement]:
        path = context.input_path
        readable = path.is_file() and os.access(path, os.R_OK)
        measurements = [
            self._measurement(context, "file.readable", Category.FILE, readable),
            self._measurement(context, "filename.pattern", Category.FILE, path.name),
            self._measurement(
                context, "file.extension", Category.FILE, path.suffix.lstrip(".").lower()
            ),
        ]
        if not readable:
            raise DetectorRunError(f"input file is not readable: {path.name}")
        measurements.append(
            self._measurement(context, "file.size_bytes", Category.FILE, path.stat().st_size, "B")
        )

        parsed = self._probe(context)
        measurements.extend(self._container_measurements(context, parsed))
        measurements.extend(self._stream_measurements(context, parsed))
        return measurements

    # ------------------------------------------------------------------ internals

    def _probe(self, context: QCContext) -> dict[str, Any]:
        args = [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(context.input_path),
        ]
        try:
            result = run_tool(args, timeout=_FFPROBE_TIMEOUT)
        except ToolError as exc:
            raise DetectorRunError(f"ffprobe failed: {exc}") from exc

        context.raw_dir.mkdir(parents=True, exist_ok=True)
        (context.raw_dir / RAW_FILENAME).write_text(result.stdout, encoding="utf-8")

        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise DetectorRunError(f"ffprobe produced invalid JSON: {exc}") from exc
        if not isinstance(parsed, dict) or "format" not in parsed:
            raise DetectorRunError("ffprobe output missing format block (corrupt input?)")
        logger.info(
            "ffprobe completed",
            extra={
                "detector_id": self.detector_id,
                "job_id": str(context.job_id),
                "stream_count": len(parsed.get("streams", [])),
            },
        )
        return parsed

    def _container_measurements(
        self, context: QCContext, parsed: dict[str, Any]
    ) -> list[Measurement]:
        fmt = parsed.get("format", {})
        out = []
        format_name = fmt.get("format_name")
        if format_name is not None:
            extension = context.input_path.suffix.lstrip(".").lower()
            out.append(
                self._measurement(
                    context,
                    "container.format",
                    Category.CONTAINER,
                    normalize_container_format(format_name, extension),
                    metadata={
                        "format_name_raw": format_name,
                        "format_long_name": fmt.get("format_long_name"),
                    },
                )
            )
        duration = _as_float(fmt.get("duration"))
        if duration is not None:
            out.append(
                self._measurement(context, "container.duration", Category.CONTAINER, duration, "s")
            )
        return out

    def _stream_measurements(self, context: QCContext, parsed: dict[str, Any]) -> list[Measurement]:
        streams = parsed.get("streams", [])
        by_type: dict[str, list[dict[str, Any]]] = {"video": [], "audio": [], "subtitle": []}
        for stream in streams:
            kind = stream.get("codec_type")
            if kind in by_type:
                by_type[kind].append(stream)

        out = [
            self._measurement(context, "video.stream_count", Category.VIDEO, len(by_type["video"])),
            self._measurement(context, "audio.stream_count", Category.AUDIO, len(by_type["audio"])),
            self._measurement(
                context, "subtitle.stream_count", Category.SUBTITLE, len(by_type["subtitle"])
            ),
        ]

        for stream in by_type["video"]:
            index = stream.get("index")
            out.append(
                self._measurement(
                    context,
                    "video.codec",
                    Category.VIDEO,
                    stream.get("codec_name"),
                    stream_index=index,
                )
            )
            out.append(
                self._measurement(
                    context,
                    "video.width",
                    Category.VIDEO,
                    stream.get("width"),
                    "px",
                    stream_index=index,
                )
            )
            out.append(
                self._measurement(
                    context,
                    "video.height",
                    Category.VIDEO,
                    stream.get("height"),
                    "px",
                    stream_index=index,
                )
            )
            fps, rational = parse_frame_rate(stream.get("r_frame_rate"))
            if fps is not None:
                out.append(
                    self._measurement(
                        context,
                        "video.frame_rate",
                        Category.VIDEO,
                        fps,
                        "fps",
                        stream_index=index,
                        metadata={"rational": rational},
                    )
                )
            out.append(
                self._measurement(
                    context,
                    "video.pixel_format",
                    Category.VIDEO,
                    stream.get("pix_fmt"),
                    stream_index=index,
                )
            )

        fmt_duration = _as_float(parsed.get("format", {}).get("duration"))
        # A/V delta only exists when a video stream exists; container duration
        # is the fallback for a video stream that lacks a per-stream duration.
        video_duration = None
        if by_type["video"]:
            video_duration = _as_float(by_type["video"][0].get("duration"))
            if video_duration is None:
                video_duration = fmt_duration

        for stream in by_type["audio"]:
            index = stream.get("index")
            # Canonical form (backlog #33): "ger"/"deu"/"de-DE" all -> "de".
            language = normalize_language((stream.get("tags") or {}).get("language"))
            audio_duration = _as_float(stream.get("duration"))
            if audio_duration is None:
                audio_duration = fmt_duration
            if audio_duration is not None:
                out.append(
                    self._measurement(
                        context,
                        "audio.duration",
                        Category.AUDIO,
                        audio_duration,
                        "s",
                        stream_index=index,
                    )
                )
                if video_duration is not None:
                    out.append(
                        self._measurement(
                            context,
                            "audio.video_duration_delta",
                            Category.AUDIO,
                            round(audio_duration - video_duration, 3),
                            "s",
                            stream_index=index,
                        )
                    )
            out.append(
                self._measurement(
                    context,
                    "audio.codec",
                    Category.AUDIO,
                    stream.get("codec_name"),
                    stream_index=index,
                )
            )
            out.append(
                self._measurement(
                    context,
                    "audio.sample_rate",
                    Category.AUDIO,
                    _as_int(stream.get("sample_rate")),
                    "Hz",
                    stream_index=index,
                )
            )
            out.append(
                self._measurement(
                    context,
                    "audio.channel_count",
                    Category.AUDIO,
                    stream.get("channels"),
                    stream_index=index,
                )
            )
            out.append(
                self._measurement(
                    context,
                    "audio.channel_layout",
                    Category.AUDIO,
                    stream.get("channel_layout"),
                    stream_index=index,
                )
            )
            if language is not None:
                out.append(
                    self._measurement(
                        context, "audio.language", Category.AUDIO, language, stream_index=index
                    )
                )
        return out

    def _measurement(
        self,
        context: QCContext,
        parameter_id: str,
        category: Category,
        value: Any,
        unit: str | None = None,
        stream_index: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Measurement:
        return Measurement(
            measurement_id=ids.measurement_id(
                self.detector_id,
                self.detector_version,
                parameter_id,
                stream_index,
                None,
                None,
                value,
            ),
            job_id=context.job_id,
            detector_id=self.detector_id,
            detector_version=self.detector_version,
            parameter_id=parameter_id,
            category=category,
            value=value,
            unit=unit,
            stream_index=stream_index,
            metadata=metadata or {},
            raw_artifact_path=f"raw/{RAW_FILENAME}",
        )
