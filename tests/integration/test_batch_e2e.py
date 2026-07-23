"""Batch mode end-to-end: directory of media -> per-file jobs + summary."""

import json
import shutil
import sys
from pathlib import Path

import pytest

from deepdub_qc.orchestration.batch import (
    EmptyBatchError,
    batch_status,
    discover_media,
    run_batch,
)
from deepdub_qc.orchestration.pipeline import AnalysisOptions

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
    directory = tmp_path_factory.mktemp("batch_media")
    generate(directory)
    return directory


class TestBatch:
    def test_batch_runs_every_file_and_writes_summary(
        self, media_dir: Path, tmp_path: Path
    ) -> None:
        # Restrict to WAVs to keep the batch fast and deterministic.
        wav_dir = tmp_path / "inputs"
        wav_dir.mkdir()
        for name in ("audio_ok.wav", "audio_silences.wav"):
            shutil.copy(media_dir / name, wav_dir / name)

        output_root = tmp_path / "batch_out"
        progress: list[str] = []
        items = run_batch(
            wav_dir,
            TIER2_PRESET,
            output_root,
            AnalysisOptions(render_pdf=False, on_progress=progress.append),
        )

        assert [item.filename for item in items] == ["audio_ok.wav", "audio_silences.wav"]
        by_name = {item.filename: item for item in items}
        assert by_name["audio_ok.wav"].status == "PASS"
        assert by_name["audio_silences.wav"].status == "WARNING"
        assert batch_status(items) == "WARNING"
        assert progress[0].startswith("[1/2]")

        for item in items:
            assert (item.output_dir / "report.json").is_file()

        summary = json.loads((output_root / "batch_summary.json").read_text(encoding="utf-8"))
        assert summary["batch_status"] == "WARNING"
        assert summary["total"] == 2
        assert [entry["filename"] for entry in summary["items"]] == [
            "audio_ok.wav",
            "audio_silences.wav",
        ]

    def test_empty_directory_raises(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(EmptyBatchError):
            run_batch(empty, TIER2_PRESET, tmp_path / "out")

    def test_discovery_is_sorted_and_filtered(self, tmp_path: Path) -> None:
        (tmp_path / "b.wav").write_bytes(b"")
        (tmp_path / "a.mov").write_bytes(b"")
        (tmp_path / "notes.txt").write_bytes(b"")
        assert [p.name for p in discover_media(tmp_path)] == ["a.mov", "b.wav"]
