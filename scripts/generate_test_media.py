"""Generate synthetic test media for the golden corpus.

Usage:
    python scripts/generate_test_media.py <output_dir>

Creates small, deterministic-metadata fixtures (content bytes may vary across
FFmpeg versions; QC metadata - codecs, resolution, rates, layouts - is stable).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FIXTURES: dict[str, list[str]] = {
    # Conforming reference: 1920x1080 @ 23.976, two stereo 48 kHz audio streams (deu + eng).
    "reference_1080p2398.mov": [
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=1920x1080:rate=24000/1001:duration=2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:duration=2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=880:sample_rate=48000:duration=2",
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-map",
        "2:a",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "pcm_s16le",
        "-ac",
        "2",
        "-metadata:s:a:0",
        "language=ger",
        "-metadata:s:a:1",
        "language=eng",
    ],
    # Wrong resolution, wrong sample rate, missing second audio stream:
    # must FAIL against the Tier 1 preset.
    "wrong_res_720p_44k.mov": [
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=1280x720:rate=24000/1001:duration=2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=44100:duration=2",
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "pcm_s16le",
        "-ac",
        "2",
        "-metadata:s:a:0",
        "language=ger",
    ],
}


def generate(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, args in FIXTURES.items():
        target = output_dir / name
        cmd = ["ffmpeg", "-y", "-v", "error", *args, str(target)]
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        written.append(target)
    return written


if __name__ == "__main__":
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tests/fixtures/media")
    for path in generate(directory):
        print(f"wrote {path}")
