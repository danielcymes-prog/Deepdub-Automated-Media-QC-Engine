"""Dual-mono detection: are two channels of a stream the same signal?

Why: a dubbed master delivered with the same mono mix on L and R (or a
duplicated channel inside a 5.1 track) passes every loudness and level check
while being a real delivery defect. Vidchecker's Dual Mono test guards this;
five of the seven Deepdub templates enable it (docs/vidchecker-import.md).

How: one ffmpeg decode per multichannel stream. The filter graph fans the
stream into per-channel taps and per-pair difference signals (``pan`` computes
``cA-cB`` directly), merges them back into one multichannel probe stream, and
runs a single ``astats`` - whose per-channel blocks then carry the RMS of
every original channel and every pair difference in a deterministic order.

Decision (measurement definition, not client policy - ADR-001): a pair is a
duplicate when its difference RMS is at or below DUPLICATE_DIFF_THRESHOLD_DB
*and* at least one of the two channels carries programme content
(CONTENT_FLOOR_DB) - two silent channels are silence, not dual mono. The
boolean parameter is true when any analyzed pair is a duplicate; flagged
pairs are listed in measurement metadata.

Inputs: astats stderr from the merged probe stream.
Outputs: per-channel RMS values and the duplicate-risk verdict.
Side effects: none in the helpers (pure parsing/decision).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

from deepdub_qc.detectors.audio.common import (
    AUDIO_ANALYSIS_TIMEOUT,
    AudioStreamRef,
    list_audio_streams,
)
from deepdub_qc.detectors.base import Detector, DetectorRunError, QCContext
from deepdub_qc.detectors.registry import register
from deepdub_qc.models.enums import Category
from deepdub_qc.models.measurement import Measurement
from deepdub_qc.utils import ids
from deepdub_qc.utils.subprocess import ToolError, ToolResult, run_tool

#: Measurement definition: a pair difference at/below this RMS is "the same
#: signal". Real dual mono measures far below (bit-identical is digital
#: silence); genuinely stereo content measures tens of dB above.
DUPLICATE_DIFF_THRESHOLD_DB = -80.0
#: Measurement definition: at least one channel of a flagged pair must carry
#: content above this RMS - silent pairs are silence, not dual mono.
CONTENT_FLOOR_DB = -60.0
#: Streams wider than this compare only their first channels (pair count grows
#: quadratically; broadcast masters are <= 8 channels per track).
MAX_ANALYZED_CHANNELS = 8
#: astats reports digital silence as -inf; represented numerically as this.
DIGITAL_SILENCE_DB = -144.0

_CHANNEL_HEADER = re.compile(r"\]\s*Channel:\s*(\d+)\s*$", re.MULTILINE)
_RMS_LEVEL = re.compile(r"\]\s*RMS level dB:\s*(-?(?:[\d.]+|inf))\s*$", re.MULTILINE)


def channel_pairs(channels: int) -> list[tuple[int, int]]:
    """Deterministic pair order for the analyzed channels of a stream."""
    analyzed = min(channels, MAX_ANALYZED_CHANNELS)
    return list(combinations(range(analyzed), 2))


def pair_analysis_filter(ordinal: int, channels: int) -> str:
    """Filter graph: per-channel taps + per-pair differences -> one astats.

    Merged channel order is the parse contract: first the analyzed original
    channels, then one difference signal per pair from channel_pairs().
    """
    analyzed = min(channels, MAX_ANALYZED_CHANNELS)
    pairs = channel_pairs(channels)
    total = analyzed + len(pairs)
    graph = [f"[0:a:{ordinal}]asplit={total}" + "".join(f"[i{k}]" for k in range(total))]
    for k in range(analyzed):
        graph.append(f"[i{k}]pan=mono|c0=c{k}[m{k}]")
    for j, (a, b) in enumerate(pairs):
        graph.append(f"[i{analyzed + j}]pan=mono|c0=c{a}-c{b}[m{analyzed + j}]")
    merged_inputs = "".join(f"[m{k}]" for k in range(total))
    graph.append(f"{merged_inputs}amerge=inputs={total},astats[probe]")
    return ";".join(graph)


def parse_channel_rms(stderr: str) -> list[float]:
    """Per-channel 'RMS level dB' values from astats, in channel order.

    astats prints one block per channel followed by an Overall block; only
    the channel blocks are read. -inf becomes DIGITAL_SILENCE_DB.
    """
    overall = stderr.rfind("Overall")
    section = stderr[:overall] if overall != -1 else stderr
    values: list[float] = []
    headers = list(_CHANNEL_HEADER.finditer(section))
    for position, header in enumerate(headers):
        block_end = headers[position + 1].start() if position + 1 < len(headers) else len(section)
        block = section[header.start() : block_end]
        rms = _RMS_LEVEL.search(block)
        if rms is None:
            continue
        raw = rms.group(1)
        values.append(DIGITAL_SILENCE_DB if raw == "-inf" else float(raw))
    return values


@dataclass(frozen=True)
class DuplicatePair:
    """One flagged channel pair with the evidence behind the flag."""

    channel_a: int
    channel_b: int
    difference_rms_db: float
    louder_channel_rms_db: float


def assess_duplicate_risk(
    channel_rms: list[float], pair_rms: list[float], pairs: list[tuple[int, int]]
) -> list[DuplicatePair]:
    """Apply the measurement definition to the parsed RMS values."""
    flagged = []
    for (a, b), diff_rms in zip(pairs, pair_rms, strict=True):
        louder = max(channel_rms[a], channel_rms[b])
        if diff_rms <= DUPLICATE_DIFF_THRESHOLD_DB and louder >= CONTENT_FLOOR_DB:
            flagged.append(
                DuplicatePair(
                    channel_a=a,
                    channel_b=b,
                    difference_rms_db=diff_rms,
                    louder_channel_rms_db=louder,
                )
            )
    return flagged


def _run_pair_analysis(input_path: Path, ordinal: int, channels: int) -> ToolResult:
    args = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-nostats",
        "-i",
        str(input_path),
        "-filter_complex",
        pair_analysis_filter(ordinal, channels),
        "-map",
        "[probe]",
        "-f",
        "null",
        "-",
    ]
    try:
        return run_tool(args, timeout=AUDIO_ANALYSIS_TIMEOUT)
    except ToolError as exc:
        raise DetectorRunError(f"ffmpeg dual-mono analysis failed: {exc}") from exc


@register
class DualMonoDetector(Detector):
    """Duplicate-channel (dual mono) risk per audio stream."""

    detector_id = "audio.dualmono.ffmpeg"
    detector_version = "1.0.0"
    parameters = ("audio.duplicate_channel_risk",)

    def is_applicable(self, context: QCContext) -> bool:
        return True  # emits nothing when the file has no audio streams

    def run(self, context: QCContext) -> list[Measurement]:
        measurements = []
        for stream in list_audio_streams(context.input_path):
            if stream.channels is None:
                continue  # channel count unknown: no honest verdict possible
            if stream.channels < 2:
                # A mono stream cannot carry a duplicate pair; emitting False
                # keeps all-stream preset rules from reporting SKIPPED.
                measurements.append(self._measurement(context, stream, value=False, metadata={}))
                continue

            result = _run_pair_analysis(context.input_path, stream.ordinal, stream.channels)
            raw_name = f"dual_mono_a{stream.index}.log"
            context.raw_dir.mkdir(parents=True, exist_ok=True)
            (context.raw_dir / raw_name).write_text(result.stderr, encoding="utf-8")

            analyzed = min(stream.channels, MAX_ANALYZED_CHANNELS)
            pairs = channel_pairs(stream.channels)
            rms = parse_channel_rms(result.stderr)
            if len(rms) != analyzed + len(pairs):
                raise DetectorRunError(
                    f"dual-mono astats returned {len(rms)} channel blocks, "
                    f"expected {analyzed + len(pairs)} (stream {stream.index})"
                )
            flagged = assess_duplicate_risk(rms[:analyzed], rms[analyzed:], pairs)
            metadata = {
                "analyzed_channels": analyzed,
                "stream_channels": stream.channels,
                "duplicate_pairs": [
                    {
                        "channels": [pair.channel_a, pair.channel_b],
                        "difference_rms_db": pair.difference_rms_db,
                        "louder_channel_rms_db": pair.louder_channel_rms_db,
                    }
                    for pair in flagged
                ],
            }
            measurements.append(
                self._measurement(
                    context, stream, value=bool(flagged), metadata=metadata, raw_name=raw_name
                )
            )
        return measurements

    def _measurement(
        self,
        context: QCContext,
        stream: AudioStreamRef,
        value: bool,
        metadata: dict[str, Any],
        raw_name: str | None = None,
    ) -> Measurement:
        parameter_id = "audio.duplicate_channel_risk"
        return Measurement(
            measurement_id=ids.measurement_id(
                self.detector_id,
                self.detector_version,
                parameter_id,
                stream.index,
                None,
                None,
                value,
            ),
            job_id=context.job_id,
            detector_id=self.detector_id,
            detector_version=self.detector_version,
            parameter_id=parameter_id,
            category=Category.AUDIO,
            value=value,
            stream_index=stream.index,
            metadata={
                "duplicate_diff_threshold_db": DUPLICATE_DIFF_THRESHOLD_DB,
                "content_floor_db": CONTENT_FLOOR_DB,
                **metadata,
            },
            raw_artifact_path=f"raw/{raw_name}" if raw_name else None,
        )
