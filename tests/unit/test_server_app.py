"""FastAPI app: API contract, GUI pages, containment, session cap (spec 2-7)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from deepdub_qc.server.app import create_app
from deepdub_qc.server.config import LoadedConfig, ServerConfig
from deepdub_qc.server.store import JobStore

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def env(tmp_path: Path):
    media = tmp_path / "media"
    media.mkdir()
    (tmp_path / "ffmpeg").write_text("")
    (tmp_path / "ffprobe").write_text("")
    config = ServerConfig.model_validate(
        {
            "schema_version": 1,
            "server": {"max_gui_sessions": 2, "gui_session_ttl_minutes": 15},
            "paths": {
                "media_roots": [str(media)],
                "jobs_root": str(tmp_path / "jobs"),
                "database": str(tmp_path / "qc.sqlite3"),
                "presets_root": str(REPO_ROOT / "presets"),
            },
            "tools": {
                "ffmpeg_path": str(tmp_path / "ffmpeg"),
                "ffprobe_path": str(tmp_path / "ffprobe"),
            },
        }
    )
    store = JobStore(config.paths.database)
    app = create_app(LoadedConfig(config=config), store=store)
    client = TestClient(app)
    return config, store, app, client


def submit_payload(media_root: Path, name: str = "ep.wav") -> dict:
    target = media_root / name
    if not target.exists():
        target.write_bytes(b"x" * 64)
    return {
        "input_path": str(target),
        "preset_id": "marimba_deliver_audio",
        "preset_version": "1.0.0",
        "requested_by": "baruch",
    }


class TestApi:
    def test_health(self, env) -> None:
        _, _, _, client = env
        body = client.get("/api/v1/health").json()
        assert body["status"] == "ok"
        assert body["queue_depth"] == 0

    def test_presets_listing(self, env) -> None:
        _, _, _, client = env
        presets = client.get("/api/v1/presets").json()
        ids = {(p["preset_id"], p["version"]) for p in presets}
        assert ("marimba_deliver_audio", "1.0.0") in ids

    def test_submit_list_detail_cancel_roundtrip(self, env) -> None:
        config, _, _, client = env
        created = client.post("/api/v1/qc/jobs", json=submit_payload(config.paths.media_roots[0]))
        assert created.status_code == 201
        job = created.json()
        assert job["status"] == "pending"
        assert job["queue_position"] == 1

        listed = client.get("/api/v1/qc/jobs").json()
        assert listed["total"] == 1
        assert listed["jobs"][0]["job_id"] == job["job_id"]

        detail = client.get(f"/api/v1/qc/jobs/{job['job_id']}").json()
        assert detail["requested_by"] == "baruch"

        cancel = client.post(f"/api/v1/qc/jobs/{job['job_id']}/cancel", json={})
        assert cancel.json()["result"] == "cancelled"

    def test_submit_validation_errors_are_coded(self, env) -> None:
        config, _, _, client = env
        payload = submit_payload(config.paths.media_roots[0])
        payload["input_path"] = str(config.paths.media_roots[0] / "missing.wav")
        response = client.post("/api/v1/qc/jobs", json=payload)
        assert response.status_code == 422
        assert response.json()["errors"][0]["code"] == "E1"

    def test_duplicate_conflict_and_override(self, env) -> None:
        config, _, _, client = env
        payload = submit_payload(config.paths.media_roots[0])
        assert client.post("/api/v1/qc/jobs", json=payload).status_code == 201
        conflict = client.post("/api/v1/qc/jobs", json=payload)
        assert conflict.status_code == 409
        payload["duplicate_override"] = True
        assert client.post("/api/v1/qc/jobs", json=payload).status_code == 201

    def test_artifact_serving_and_traversal_rejection(self, env) -> None:
        config, store, _, client = env
        created = client.post(
            "/api/v1/qc/jobs", json=submit_payload(config.paths.media_roots[0])
        ).json()
        job = store.get(created["job_id"])
        job_dir = Path(job.output_dir)
        (job_dir / "evidence").mkdir(parents=True)
        (job_dir / "report.json").write_text('{"summary": {}}', encoding="utf-8")
        (job_dir / "evidence" / "thumb.png").write_bytes(b"png")
        secret = job_dir.parent.parent / "secret.txt"
        secret.write_text("nope")

        assert client.get(f"/api/v1/qc/jobs/{job.job_id}/report").status_code == 200
        assert (
            client.get(f"/api/v1/qc/jobs/{job.job_id}/files/evidence/thumb.png").status_code == 200
        )
        # crafted traversal must 404, never leak (acceptance criterion 9)
        assert client.get(f"/api/v1/qc/jobs/{job.job_id}/files/../../secret.txt").status_code == 404
        assert client.get(f"/api/v1/qc/jobs/{job.job_id}/report.pdf").status_code == 404

    def test_browse_is_root_contained(self, env) -> None:
        config, _, _, client = env
        root = config.paths.media_roots[0]
        (root / "sub").mkdir()
        (root / "ep.mov").write_bytes(b"x")

        roots = client.get("/api/v1/browse").json()
        assert roots["entries"][0]["kind"] == "root"

        listing = client.get("/api/v1/browse", params={"path": str(root)}).json()
        names = [e["name"] for e in listing["entries"]]
        assert names == ["sub", "ep.mov"]  # dirs first

        outside = client.get("/api/v1/browse", params={"path": str(root.parent)})
        assert outside.status_code == 403

    def test_validate_path_endpoint(self, env) -> None:
        config, _, _, client = env
        media = config.paths.media_roots[0] / "ok.wav"
        media.write_bytes(b"x" * 2048)
        good = client.get("/api/v1/validate-path", params={"path": str(media)}).json()
        assert good["ok"] and good["size_bytes"] == 2048
        bad = client.get("/api/v1/validate-path", params={"path": str(media) + ".nope"}).json()
        assert not bad["ok"] and bad["code"] == "E1"


class TestGui:
    def test_submit_page_renders_spec_microcopy(self, env) -> None:
        _, _, _, client = env
        html = client.get("/").text
        assert "Submit a QC job" in html
        assert "nothing is uploaded" in html
        assert "Run QC" in html

    def test_submit_form_errors_render_inline(self, env) -> None:
        _, _, _, client = env
        response = client.post(
            "/submit",
            data={"input_path": "D:\\nope.mov", "preset": "x@1", "requested_by": ""},
        )
        assert response.status_code == 200
        assert "field-error" in response.text

    def test_submit_redirects_to_detail_then_shows_queued(self, env) -> None:
        config, _, _, client = env
        media = config.paths.media_roots[0] / "ep.wav"
        media.write_bytes(b"x" * 32)
        response = client.post(
            "/submit",
            data={
                "input_path": str(media),
                "preset": "marimba_deliver_audio@1.0.0",
                "requested_by": "baruch",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        detail = client.get(response.headers["location"]).text
        assert "Queued — position 1" in detail
        assert "One job runs at a time." in detail

    def test_duplicate_shows_submit_anyway(self, env) -> None:
        config, _, _, client = env
        media = config.paths.media_roots[0] / "ep.wav"
        media.write_bytes(b"x" * 32)
        form = {
            "input_path": str(media),
            "preset": "marimba_deliver_audio@1.0.0",
            "requested_by": "baruch",
        }
        client.post("/submit", data=form)
        again = client.post("/submit", data=form)
        assert "Submit anyway" in again.text

    def test_jobs_page_separates_state_and_verdict(self, env) -> None:
        config, store, _, client = env
        created = client.post(
            "/api/v1/qc/jobs", json=submit_payload(config.paths.media_roots[0])
        ).json()
        store.claim_next()
        store.mark_completed(created["job_id"], "FAIL", {"failed": 2})
        html = client.get("/jobs").text
        assert "● Done" in html  # orchestration state...
        assert "FAIL" in html  # ...and media verdict, as separate systems

    def test_completed_detail_reads_canonical_report(self, env) -> None:
        """The detail page summary comes from report.json, not the snapshot."""
        config, store, _, client = env
        created = client.post(
            "/api/v1/qc/jobs", json=submit_payload(config.paths.media_roots[0])
        ).json()
        store.claim_next()
        store.mark_completed(created["job_id"], "FAIL", {"passed": 999})  # stale snapshot
        job = store.get(created["job_id"])
        job_dir = Path(job.output_dir)
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "report.json").write_text(
            json.dumps(
                {
                    "summary": {
                        "overall_status": "FAIL",
                        "total_checks": 24,
                        "passed": 20,
                        "warnings": 2,
                        "failed": 2,
                        "errors": 0,
                        "blocking_failures": 2,
                    },
                    "findings": [
                        {
                            "rule_id": "integrated-loudness",
                            "display_name": "Integrated Loudness",
                            "status": "FAIL",
                            "blocking": True,
                            "expected": {"min": -24.0, "max": -22.0, "unit": "LUFS"},
                            "actual": {"value": -19.7, "unit": "LUFS"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        html = client.get(f"/jobs/{job.job_id}").text
        assert "20 passed" in html  # canonical file, not the 999 snapshot
        assert "Integrated Loudness" in html
        assert "BLOCKING" in html
        assert "Open HTML report" in html

    def test_presets_page_states_governance(self, env) -> None:
        _, _, _, client = env
        html = client.get("/presets").text
        assert "this list is read-only" in html
        assert "marimba_deliver_audio@1.0.0" in html

    def test_session_cap_third_browser_gets_503(self, env) -> None:
        _, _, app, _ = env
        first = TestClient(app)
        second = TestClient(app)
        third = TestClient(app)
        assert first.get("/").status_code == 200
        assert second.get("/").status_code == 200
        response = third.get("/")
        assert response.status_code == 503
        assert "Both operator slots are in use" in response.text
        # existing sessions keep working; the API is exempt from the cap
        assert first.get("/jobs").status_code == 200
        assert third.get("/api/v1/health").status_code == 200
