"""M5 video incident QC end-to-end: black/freeze detection + thumbnail evidence."""

import shutil
import sys
from pathlib import Path

import pytest

from deepdub_qc.models import QCStatus
from deepdub_qc.orchestration.pipeline import AnalysisOptions, run_analysis

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from generate_test_media import generate  # noqa: E402

TIER3_PRESET = REPO_ROOT / "tests" / "fixtures" / "presets" / "tier3_video_v1.yaml"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None,
        reason="ffmpeg/ffprobe not available",
    ),
]


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("video_media")
    generate(directory)
    return directory


class TestVideoIncidents:
    def test_clean_video_passes(self, media_dir: Path, tmp_path: Path) -> None:
        result = run_analysis(
            media_dir / "reference_1080p2398.mov",
            TIER3_PRESET,
            tmp_path / "job",
            AnalysisOptions(render_pdf=False),
        )
        assert result.summary.overall_status is QCStatus.PASS, [
            (f.rule_id, f.status, f.message) for f in result.findings
        ]
        assert not result.evidence

    def test_incident_video_fails_with_timestamped_evidence(
        self, media_dir: Path, tmp_path: Path
    ) -> None:
        result = run_analysis(
            media_dir / "video_incidents.mov",
            TIER3_PRESET,
            tmp_path / "job",
            AnalysisOptions(render_pdf=False),
        )
        assert result.summary.overall_status is QCStatus.FAIL
        by_id = {f.rule_id: f for f in result.findings}

        black = by_id["black-frames"]
        assert black.status is QCStatus.FAIL
        assert black.start_seconds is not None
        assert 1.3 <= black.start_seconds <= 1.7  # black segment starts ~1.52s
        assert black.evidence_ids, "black-frame failure must carry thumbnail evidence"

        freeze = by_id["freeze-frames"]
        assert freeze.status is QCStatus.WARNING
        assert freeze.start_seconds is not None

        # Evidence records resolve and files exist on disk.
        assert result.evidence
        for record in result.evidence:
            assert record.finding_id in {f.finding_id for f in result.findings}
            evidence_file = tmp_path / "job" / record.path
            assert evidence_file.is_file()
            assert evidence_file.stat().st_size > 0
            assert record.sha256
        assert result.artifacts.evidence_directory == "evidence/"

    def test_audio_only_file_skips_video_rules(self, media_dir: Path, tmp_path: Path) -> None:
        result = run_analysis(
            media_dir / "audio_ok.wav",
            TIER3_PRESET,
            tmp_path / "job",
            AnalysisOptions(render_pdf=False),
        )
        by_id = {f.rule_id: f.status for f in result.findings}
        # No video stream: luma rule skips; black/freeze not_exists rules pass
        # vacuously (no events measured, none present).
        assert by_id["luma-average"] is QCStatus.SKIPPED
        assert by_id["black-frames"] is QCStatus.PASS
