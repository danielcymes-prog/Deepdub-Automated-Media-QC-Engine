"""Dual-mono detector against real ffmpeg on synthesized fixtures.

The fixtures encode the three cases the measurement definition separates:
duplicated channels with content (flag), genuinely different channels
(no flag), and digital silence on both channels (no flag - silence is not
dual mono).
"""

import subprocess
import sys
from pathlib import Path
from uuid import UUID

import pytest

from deepdub_qc.detectors.audio.dual_mono import DualMonoDetector
from deepdub_qc.detectors.base import QCContext

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_toolchain,
]

JOB_ID = UUID("00000000-0000-4000-8000-0000000000d4")

_FIXTURES: dict[str, list[str]] = {
    # sine -> -ac 2 duplicates the channel: dual mono by construction.
    "dual_mono.wav": [
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:duration=2",
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
    ],
    # Two different sines joined: honest stereo.
    "true_stereo.wav": [
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:duration=2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=880:sample_rate=48000:duration=2",
        "-filter_complex",
        "[0:a][1:a]join=inputs=2:channel_layout=stereo[a]",
        "-map",
        "[a]",
        "-c:a",
        "pcm_s16le",
    ],
    # Digital silence on both channels: identical, but not dual mono.
    "silent_stereo.wav": [
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=48000:duration=2",
        "-c:a",
        "pcm_s16le",
    ],
    "mono.wav": [
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:duration=2",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
    ],
}


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("dual_mono_media")
    for name, args in _FIXTURES.items():
        subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-y", *args, str(directory / name)],
            check=True,
            capture_output=True,
            timeout=120,
        )
    return directory


def run_detector(media_dir: Path, tmp_path: Path, filename: str) -> list:
    context = QCContext(job_id=JOB_ID, input_path=media_dir / filename, raw_dir=tmp_path / "raw")
    return DualMonoDetector().run(context)


class TestDualMonoDetector:
    def test_duplicated_channels_are_flagged(self, media_dir: Path, tmp_path: Path) -> None:
        measurements = run_detector(media_dir, tmp_path, "dual_mono.wav")
        assert len(measurements) == 1
        measurement = measurements[0]
        assert measurement.value is True
        pairs = measurement.metadata["duplicate_pairs"]
        assert [tuple(p["channels"]) for p in pairs] == [(0, 1)]
        assert (tmp_path / "raw").glob("dual_mono_a*.log"), "raw astats log must be preserved"

    def test_true_stereo_is_clean(self, media_dir: Path, tmp_path: Path) -> None:
        measurements = run_detector(media_dir, tmp_path, "true_stereo.wav")
        assert len(measurements) == 1
        assert measurements[0].value is False
        assert measurements[0].metadata["duplicate_pairs"] == []

    def test_silent_stereo_is_not_dual_mono(self, media_dir: Path, tmp_path: Path) -> None:
        measurements = run_detector(media_dir, tmp_path, "silent_stereo.wav")
        assert len(measurements) == 1
        assert measurements[0].value is False

    def test_mono_reports_false_without_analysis(self, media_dir: Path, tmp_path: Path) -> None:
        measurements = run_detector(media_dir, tmp_path, "mono.wav")
        assert len(measurements) == 1
        assert measurements[0].value is False
        assert not (tmp_path / "raw").exists(), "mono streams must not decode at all"

    def test_verdict_is_reproducible(self, media_dir: Path, tmp_path: Path) -> None:
        """ADR-008: same input, same verdict and measurement id, run to run."""
        runs = []
        for i in range(2):
            context = QCContext(
                job_id=JOB_ID,
                input_path=media_dir / "dual_mono.wav",
                raw_dir=tmp_path / f"raw{i}",
            )
            measurements = DualMonoDetector().run(context)
            runs.append([(m.measurement_id, m.parameter_id, m.value) for m in measurements])
        assert runs[0] == runs[1]
