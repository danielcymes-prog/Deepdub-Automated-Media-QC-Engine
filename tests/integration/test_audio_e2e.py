"""M4 audio QC end-to-end: loudness, silence, clipping on generated fixtures."""

import shutil
import sys
from pathlib import Path
from uuid import UUID

import pytest

from deepdub_qc.detectors.audio.loudness import LoudnessDetector
from deepdub_qc.detectors.base import QCContext
from deepdub_qc.models import QCStatus
from deepdub_qc.orchestration.pipeline import AnalysisOptions, run_analysis

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from generate_test_media import generate  # noqa: E402

TIER2_PRESET = REPO_ROOT / "tests" / "fixtures" / "presets" / "tier2_audio_v1.yaml"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None,
        reason="ffmpeg/ffprobe not available",
    ),
]


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("audio_media")
    generate(directory)
    return directory


class TestAudioQC:
    def test_conforming_audio_passes(self, media_dir: Path, tmp_path: Path) -> None:
        result = run_analysis(
            media_dir / "audio_ok.wav",
            TIER2_PRESET,
            tmp_path / "job",
            AnalysisOptions(render_pdf=False),
        )
        problems = [
            (f.rule_id, f.status, f.message)
            for f in result.findings
            if f.status not in (QCStatus.PASS, QCStatus.NOT_APPLICABLE, QCStatus.SKIPPED)
        ]
        assert result.summary.overall_status is QCStatus.PASS, problems
        by_id = {f.rule_id: f for f in result.findings}
        assert by_id["integrated-loudness"].status is QCStatus.PASS
        actual = by_id["integrated-loudness"].actual
        assert actual is not None
        assert -24.0 <= float(actual.value) <= -22.0  # type: ignore[arg-type]
        # WAV has no video stream: the A/V delta rule must SKIP, not fail.
        assert by_id["av-duration-delta"].status is QCStatus.SKIPPED

    def test_clipped_audio_fails_loudness_and_clipping(
        self, media_dir: Path, tmp_path: Path
    ) -> None:
        result = run_analysis(
            media_dir / "audio_clipped.wav",
            TIER2_PRESET,
            tmp_path / "job",
            AnalysisOptions(render_pdf=False),
        )
        assert result.summary.overall_status is QCStatus.FAIL
        by_id = {f.rule_id: f.status for f in result.findings}
        assert by_id["integrated-loudness"] is QCStatus.FAIL
        assert by_id["true-peak"] is QCStatus.FAIL
        assert by_id["clipping-flat-factor"] is QCStatus.FAIL

    def test_silences_produce_warnings_with_timestamps(
        self, media_dir: Path, tmp_path: Path
    ) -> None:
        result = run_analysis(
            media_dir / "audio_silences.wav",
            TIER2_PRESET,
            tmp_path / "job",
            AnalysisOptions(render_pdf=False),
        )
        assert result.summary.overall_status is QCStatus.WARNING, [
            (f.rule_id, f.status, f.message) for f in result.findings
        ]
        by_id = {f.rule_id: f for f in result.findings}
        assert by_id["head-silence"].status is QCStatus.WARNING
        assert by_id["tail-silence"].status is QCStatus.WARNING
        internal = by_id["internal-silence"]
        assert internal.status is QCStatus.WARNING
        # The internal-silence incident carries the event's span (engine
        # propagates event timestamps to findings).
        assert internal.start_seconds is not None
        assert 2.8 <= internal.start_seconds <= 3.2
        assert internal.end_seconds is not None
        assert 3.6 <= internal.end_seconds <= 4.0

    def test_raw_audio_logs_preserved(self, media_dir: Path, tmp_path: Path) -> None:
        run_analysis(
            media_dir / "audio_ok.wav",
            TIER2_PRESET,
            tmp_path / "job",
            AnalysisOptions(render_pdf=False),
        )
        raw = tmp_path / "job" / "raw"
        assert list(raw.glob("ebur128_a*.log"))
        assert list(raw.glob("silencedetect_a*.log"))
        assert list(raw.glob("astats_a*.log"))


class TestLoudnessReproducibility:
    def test_repeated_measurement_identical(self, media_dir: Path, tmp_path: Path) -> None:
        """ADR-008: loudness measurements must be bit-identical run-to-run."""
        detector = LoudnessDetector()
        job_id = UUID("00000000-0000-4000-8000-0000000000c3")
        runs = []
        for i in range(2):
            context = QCContext(
                job_id=job_id,
                input_path=media_dir / "audio_ok.wav",
                raw_dir=tmp_path / f"raw{i}",
            )
            measurements = detector.run(context)
            runs.append(sorted((m.parameter_id, m.stream_index, m.value) for m in measurements))
        assert runs[0] == runs[1]
        assert runs[0], "loudness detector produced no measurements"
