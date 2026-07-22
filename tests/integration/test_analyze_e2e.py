"""End-to-end integration tests: real media, real ffprobe, full pipeline.

Requires ffmpeg + ffprobe on PATH (skipped otherwise). Media fixtures are
generated once per session by scripts/generate_test_media.py.
"""

import json
import shutil
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from typer.testing import CliRunner

from deepdub_qc.cli import app
from deepdub_qc.models import QCResult, QCStatus
from deepdub_qc.orchestration.pipeline import AnalysisOptions, run_analysis

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from generate_test_media import generate  # noqa: E402

TIER1_PRESET = REPO_ROOT / "tests" / "fixtures" / "presets" / "tier1_metadata_v1.yaml"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None,
        reason="ffmpeg/ffprobe not available",
    ),
]

runner = CliRunner()


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("media")
    generate(directory)
    return directory


class TestAnalyzePipeline:
    def test_reference_file_passes(self, media_dir: Path, tmp_path: Path) -> None:
        result = run_analysis(
            media_dir / "reference_1080p2398.mov",
            TIER1_PRESET,
            tmp_path / "job",
            AnalysisOptions(render_pdf=False),
        )
        failed = [
            f for f in result.findings if f.status not in (QCStatus.PASS, QCStatus.NOT_APPLICABLE)
        ]
        assert result.summary.overall_status is QCStatus.PASS, [
            (f.rule_id, f.status, f.message) for f in failed
        ]
        assert result.summary.total_checks == 17
        assert (tmp_path / "job" / "report.json").is_file()
        assert (tmp_path / "job" / "report.html").is_file()
        assert (tmp_path / "job" / "raw" / "ffprobe.json").is_file()

    def test_wrong_file_fails_with_expected_findings(self, media_dir: Path, tmp_path: Path) -> None:
        result = run_analysis(
            media_dir / "wrong_res_720p_44k.mov",
            TIER1_PRESET,
            tmp_path / "job",
            AnalysisOptions(render_pdf=False),
        )
        assert result.summary.overall_status is QCStatus.FAIL
        by_id = {f.rule_id: f.status for f in result.findings}
        assert by_id["video-width"] is QCStatus.FAIL
        assert by_id["video-height"] is QCStatus.FAIL
        assert by_id["audio-sample-rate"] is QCStatus.FAIL
        assert by_id["audio-stream-count"] is QCStatus.FAIL
        assert by_id["video-codec"] is QCStatus.PASS
        assert by_id["container-format"] is QCStatus.PASS
        # German-language stream exists but at 44.1 kHz -> non-blocking warning
        assert by_id["audio-german-sample-rate"] is QCStatus.WARNING

    def test_report_json_is_valid_qcresult(self, media_dir: Path, tmp_path: Path) -> None:
        run_analysis(
            media_dir / "reference_1080p2398.mov",
            TIER1_PRESET,
            tmp_path / "job",
            AnalysisOptions(render_pdf=False),
        )
        text = (tmp_path / "job" / "report.json").read_text(encoding="utf-8")
        restored = QCResult.model_validate_json(text)
        assert restored.preset.preset_id == "tier1_metadata_test"
        assert restored.media_summary["timecode_frame_rate"] == 23.976
        assert len(restored.media_summary["audio_streams"]) == 2  # type: ignore[arg-type]


VOLATILE_PATHS = ("started_at", "completed_at", "duration_seconds", "created_at", "job_id")


def _mask_volatile(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            key: ("MASKED" if key in VOLATILE_PATHS else _mask_volatile(value))
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_mask_volatile(item) for item in node]
    return node


class TestDeterminism:
    def test_repeat_runs_identical_modulo_volatile_fields(
        self, media_dir: Path, tmp_path: Path
    ) -> None:
        """ADR-008: same input + preset + environment => identical canonical output."""
        reports = []
        for i, job_id in enumerate(
            (
                UUID("00000000-0000-4000-8000-0000000000a1"),
                UUID("00000000-0000-4000-8000-0000000000b2"),
            )
        ):
            run_analysis(
                media_dir / "reference_1080p2398.mov",
                TIER1_PRESET,
                tmp_path / f"job{i}",
                AnalysisOptions(render_pdf=False, job_id=job_id),
            )
            parsed = json.loads((tmp_path / f"job{i}" / "report.json").read_text(encoding="utf-8"))
            reports.append(json.dumps(_mask_volatile(parsed), sort_keys=True))
        assert reports[0] == reports[1]


class TestAnalyzeCli:
    def test_cli_pass_exit_zero(self, media_dir: Path, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "analyze",
                "--input",
                str(media_dir / "reference_1080p2398.mov"),
                "--preset",
                str(TIER1_PRESET),
                "--output",
                str(tmp_path / "job"),
                "--no-pdf",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "PASS" in result.output

    def test_cli_fail_exit_two(self, media_dir: Path, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "analyze",
                "--input",
                str(media_dir / "wrong_res_720p_44k.mov"),
                "--preset",
                str(TIER1_PRESET),
                "--output",
                str(tmp_path / "job"),
                "--no-pdf",
            ],
        )
        assert result.exit_code == 2, result.output

    def test_cli_missing_input_exit_five(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "analyze",
                "--input",
                str(tmp_path / "missing.mov"),
                "--preset",
                str(TIER1_PRESET),
                "--output",
                str(tmp_path / "job"),
                "--no-pdf",
            ],
        )
        assert result.exit_code == 5

    def test_cli_invalid_preset_exit_four(self, media_dir: Path, tmp_path: Path) -> None:
        bad_preset = tmp_path / "bad.yaml"
        bad_preset.write_text("schema_version: 1.0.0\n", encoding="utf-8")
        result = runner.invoke(
            app,
            [
                "analyze",
                "--input",
                str(media_dir / "reference_1080p2398.mov"),
                "--preset",
                str(bad_preset),
                "--output",
                str(tmp_path / "job"),
                "--no-pdf",
            ],
        )
        assert result.exit_code == 4
