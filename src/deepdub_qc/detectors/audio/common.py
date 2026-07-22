"""Shared helpers for per-stream audio analysis.

Audio detectors decode the full file; a 100 GB master may take a long time,
so audio analysis uses a dedicated (long) timeout and streams via ffmpeg -
media is never loaded into RAM.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from deepdub_qc.detectors.base import DetectorRunError
from deepdub_qc.utils.subprocess import ToolError, run_tool

#: Full-file audio decode limit. Recorded, not tuned, for MVP (handoff section 29).
AUDIO_ANALYSIS_TIMEOUT = 3600.0


@dataclass(frozen=True)
class AudioStreamRef:
    """One audio stream: ffprobe global index, per-type ordinal, duration."""

    index: int
    ordinal: int
    duration_seconds: float | None


def list_audio_streams(input_path: Path) -> list[AudioStreamRef]:
    """Enumerate audio streams with durations via a fast ffprobe call.

    Raises DetectorRunError if the file cannot be probed.
    """
    args = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index,duration",
        "-show_entries",
        "format=duration",
        "-print_format",
        "json",
        str(input_path),
    ]
    try:
        result = run_tool(args, timeout=120.0)
    except ToolError as exc:
        raise DetectorRunError(f"ffprobe stream enumeration failed: {exc}") from exc
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DetectorRunError(f"ffprobe produced invalid JSON: {exc}") from exc

    fallback = _to_float(parsed.get("format", {}).get("duration"))
    streams = []
    for ordinal, stream in enumerate(parsed.get("streams", [])):
        duration = _to_float(stream.get("duration"))
        streams.append(
            AudioStreamRef(
                index=int(stream["index"]),
                ordinal=ordinal,
                duration_seconds=duration if duration is not None else fallback,
            )
        )
    return streams


def run_audio_filter(input_path: Path, ordinal: int, audio_filter: str) -> str:
    """Decode one audio stream through a filter chain; return captured stderr.

    ffmpeg filter analysis output (ebur128, silencedetect, astats) is written
    to stderr; the decoded audio is discarded (-f null).
    """
    args = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        str(input_path),
        "-map",
        f"0:a:{ordinal}",
        "-filter:a",
        audio_filter,
        "-f",
        "null",
        "-",
    ]
    try:
        result = run_tool(args, timeout=AUDIO_ANALYSIS_TIMEOUT)
    except ToolError as exc:
        raise DetectorRunError(f"ffmpeg audio analysis failed: {exc}") from exc
    return result.stderr


def _to_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
