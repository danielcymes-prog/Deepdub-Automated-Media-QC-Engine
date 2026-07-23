"""Full-stack acceptance: GUI submit -> real pipeline -> report served.

Covers server-gui-spec acceptance criteria 1-3 and 9 with real ffmpeg:
a job submitted through the web form runs the SAME pipeline as the CLI
and the canonical artifacts come back through the API.
"""

import json
import shutil
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from deepdub_qc.models.enums import JobStatus
from deepdub_qc.server.app import create_app
from deepdub_qc.server.config import LoadedConfig, ServerConfig
from deepdub_qc.server.store import JobStore
from deepdub_qc.server.worker import Worker

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from generate_test_media import generate  # noqa: E402

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None,
        reason="ffmpeg/ffprobe not available",
    ),
]


@pytest.fixture(scope="module")
def media_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("serve_media")
    generate(directory)
    return directory


def test_gui_submit_runs_pipeline_and_serves_canonical_report(
    media_dir: Path, tmp_path: Path
) -> None:
    ffmpeg = Path(shutil.which("ffmpeg"))
    config = ServerConfig.model_validate(
        {
            "schema_version": 1,
            "paths": {
                "media_roots": [str(media_dir)],
                "jobs_root": str(tmp_path / "jobs"),
                "database": str(tmp_path / "qc.sqlite3"),
                "presets_root": str(REPO_ROOT / "presets"),
            },
            "tools": {
                "ffmpeg_path": str(ffmpeg),
                "ffprobe_path": str(Path(shutil.which("ffprobe"))),
            },
        }
    )
    store = JobStore(config.paths.database)
    app = create_app(LoadedConfig(config=config), store=store)
    client = TestClient(app)
    worker = Worker(store, config, poll_interval=0.05)
    worker.start()
    try:
        # Submit through the GUI form, exactly as an operator would.
        response = client.post(
            "/submit",
            data={
                "input_path": str(media_dir / "audio_ok.wav"),
                "preset": "marimba_deliver_audio@1.0.0",
                "requested_by": "baruch",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        job_id = response.headers["location"].rsplit("/", 1)[1]

        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            job = store.get(job_id)
            if job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
                break
            time.sleep(0.2)
        job = store.get(job_id)
        assert job.status is JobStatus.COMPLETED, (job.error_reason, job.error_message)
        assert job.qc_status in ("PASS", "WARNING", "FAIL")
        assert job.progress, "stage events were recorded"

        # Canonical artifacts served through the API (acceptance 9).
        report = client.get(f"/api/v1/qc/jobs/{job_id}/report")
        assert report.status_code == 200
        canonical = json.loads(report.content)
        assert canonical["summary"]["overall_status"] == job.qc_status
        assert canonical["asset"]["filename"] == "audio_ok.wav"
        assert client.get(f"/api/v1/qc/jobs/{job_id}/report.html").status_code == 200

        # Detail page renders the verdict from the canonical report.
        html = client.get(f"/jobs/{job_id}").text
        assert "Open HTML report" in html
    finally:
        worker.stop()
