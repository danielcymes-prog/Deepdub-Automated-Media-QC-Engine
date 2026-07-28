"""Console preset editor: versioned saves, conflict guard, validation atomicity
(docs/master-preset-spec.md section 5, ADR-031)."""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from deepdub_qc.presets.loader import load_preset
from deepdub_qc.server.app import create_app
from deepdub_qc.server.config import LoadedConfig, ServerConfig
from deepdub_qc.server.editor import (
    EditorError,
    RuleEdit,
    VersionConflictError,
    apply_edits,
    editable_model,
)
from deepdub_qc.server.store import JobStore

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def env(tmp_path: Path):
    """An app over a WRITABLE presets root holding a copy of the audio master."""
    presets_root = tmp_path / "presets"
    (presets_root / "master").mkdir(parents=True)
    shutil.copy(
        REPO_ROOT / "presets" / "master" / "master_audio_v1.yaml",
        presets_root / "master" / "master_audio_v1.yaml",
    )
    media = tmp_path / "media"
    media.mkdir()
    (tmp_path / "ffmpeg").write_text("")
    (tmp_path / "ffprobe").write_text("")
    config = ServerConfig.model_validate(
        {
            "schema_version": 1,
            "paths": {
                "media_roots": [str(media)],
                "jobs_root": str(tmp_path / "jobs"),
                "database": str(tmp_path / "qc.sqlite3"),
                "presets_root": str(presets_root),
            },
            "tools": {
                "ffmpeg_path": str(tmp_path / "ffmpeg"),
                "ffprobe_path": str(tmp_path / "ffprobe"),
            },
        }
    )
    store = JobStore(config.paths.database)
    app = create_app(LoadedConfig(config=config), store=store)
    return presets_root, TestClient(app)


def master_path(presets_root: Path) -> Path:
    return presets_root / "master" / "master_audio_v1.yaml"


def make_edit(model: dict, rule_id: str, **overrides) -> RuleEdit:
    rule = next(r for r in model["rules"] if r["rule_id"] == rule_id)
    return RuleEdit(
        rule_id=rule_id,
        enabled=overrides.get("enabled", rule["enabled"]),
        severity=overrides.get("severity", rule["severity"]),
        blocking=overrides.get("blocking", rule["blocking"]),
        expected=overrides.get("expected", {}),
    )


class TestEditableModel:
    def test_rules_carry_catalogue_context_and_resolved_defaults(self, env) -> None:
        presets_root, _ = env
        model = editable_model(master_path(presets_root))
        assert model["preset_id"] == "master_audio"
        assert model["severities"] == ["info", "warning", "error", "critical"]
        loudness = next(
            r for r in model["rules"] if r["parameter_id"] == "audio.integrated_loudness"
        )
        assert set(loudness["expected"]) == {"min", "max"}
        assert loudness["severity"] in ("info", "warning", "error", "critical")
        assert loudness["catalogue_description"]


class TestApplyEdits:
    def test_save_creates_next_minor_draft_with_provenance(self, env) -> None:
        presets_root, _ = env
        base = master_path(presets_root)
        model = editable_model(base)
        loudness = next(
            r for r in model["rules"] if r["parameter_id"] == "audio.integrated_loudness"
        )
        catalog = []  # no newer versions anywhere
        new_path = apply_edits(
            base_path=base,
            base_version="1.0.0",
            catalog=catalog,
            edits=[
                make_edit(
                    model,
                    loudness["rule_id"],
                    severity="critical",
                    expected={"min": "-25", "max": "-21"},
                )
            ],
            edited_by="A/V Engineer",
            note="loudness window per new delivery spec",
        )
        assert new_path.name == "master_audio_v1_1.yaml"
        saved = load_preset(new_path)
        assert str(saved.preset.version) == "1.1.0"
        assert saved.preset.status.value == "draft"
        assert saved.preset.supersedes == "1.0.0"
        rule = next(r for r in saved.rules if r.parameter_id == "audio.integrated_loudness")
        assert rule.expected.min == -25.0
        assert rule.expected.max == -21.0
        assert rule.severity.value == "critical"
        header = new_path.read_text(encoding="utf-8")
        assert "Edited by: A/V Engineer" in header
        assert "loudness window per new delivery spec" in header
        # The base version is untouched: versioned saves, never in-place edits.
        assert str(load_preset(base).preset.version) == "1.0.0"

    def test_disabling_keeps_the_rule_in_the_file(self, env) -> None:
        presets_root, _ = env
        base = master_path(presets_root)
        model = editable_model(base)
        target = model["rules"][0]["rule_id"]
        new_path = apply_edits(
            base_path=base,
            base_version="1.0.0",
            catalog=[],
            edits=[make_edit(model, target, enabled=False)],
            edited_by="qc",
            note="",
        )
        saved = load_preset(new_path)
        rule = next(r for r in saved.rules if r.rule_id == target)
        assert rule.enabled is False  # present but off - nothing is ever lost

    def test_stale_base_is_a_conflict(self, env) -> None:
        presets_root, _ = env
        base = master_path(presets_root)
        model = editable_model(base)
        apply_edits(base, "1.0.0", [], [make_edit(model, model["rules"][0]["rule_id"])], "qc", "")
        from deepdub_qc.server.catalog import build_catalog  # noqa: PLC0415

        catalog = build_catalog(presets_root)  # now contains 1.1.0
        with pytest.raises(VersionConflictError, match=r"1\.1\.0"):
            apply_edits(
                base, "1.0.0", catalog, [make_edit(model, model["rules"][0]["rule_id"])], "qc", ""
            )

    def test_invalid_edit_saves_nothing(self, env) -> None:
        presets_root, _ = env
        base = master_path(presets_root)
        model = editable_model(base)
        loudness = next(
            r for r in model["rules"] if r["parameter_id"] == "audio.integrated_loudness"
        )
        before = sorted(p.name for p in base.parent.iterdir())
        with pytest.raises(EditorError, match="failed validation"):
            apply_edits(
                base,
                "1.0.0",
                [],
                [
                    make_edit(model, loudness["rule_id"], expected={"min": "-10", "max": "-20"})
                ],  # min > max
                "qc",
                "",
            )
        assert sorted(p.name for p in base.parent.iterdir()) == before

    def test_anonymous_saves_are_refused(self, env) -> None:
        presets_root, _ = env
        base = master_path(presets_root)
        model = editable_model(base)
        with pytest.raises(EditorError, match="name is required"):
            apply_edits(
                base, "1.0.0", [], [make_edit(model, model["rules"][0]["rule_id"])], "  ", ""
            )


class TestEditorRoutes:
    def test_editable_api_and_versioned_save(self, env) -> None:
        _, client = env
        model = client.get("/api/v1/presets/master_audio/1.0.0/editable").json()
        loudness = next(
            r for r in model["rules"] if r["parameter_id"] == "audio.integrated_loudness"
        )
        response = client.post(
            "/api/v1/presets/master_audio/versions",
            json={
                "base_version": "1.0.0",
                "edited_by": "api-test",
                "note": "tighten loudness",
                "rules": [
                    {
                        "rule_id": loudness["rule_id"],
                        "enabled": True,
                        "severity": "error",
                        "blocking": True,
                        "expected": {"min": -24.5, "max": -22.5},
                    }
                ],
            },
        )
        assert response.status_code == 201
        assert response.json()["version"] == "1.1.0"
        # The catalog refreshed in-process: the new draft is immediately real.
        versions = {(p["preset_id"], p["version"]) for p in client.get("/api/v1/presets").json()}
        assert ("master_audio", "1.1.0") in versions
        assert "master_audio@1.1.0" in client.get("/").text  # submit picker too

        stale = client.post(
            "/api/v1/presets/master_audio/versions",
            json={"base_version": "1.0.0", "edited_by": "x", "rules": []},
        )
        assert stale.status_code == 409

    def test_gui_editor_roundtrip(self, env) -> None:
        _, client = env
        page = client.get("/presets/master_audio/1.0.0/edit")
        assert page.status_code == 200
        assert "new draft version" in page.text
        assert "audio.integrated_loudness" in page.text

        model = client.get("/api/v1/presets/master_audio/1.0.0/editable").json()
        form = {"edited_by": "gui-test", "note": "form save"}
        for rule in model["rules"]:
            prefix = f"r__{rule['rule_id']}__"
            if rule["enabled"]:
                form[f"{prefix}enabled"] = "on"
            if rule["blocking"]:
                form[f"{prefix}blocking"] = "on"
            form[f"{prefix}severity"] = rule["severity"]
            for key, value in rule["expected"].items():
                form[f"{prefix}{key}"] = (
                    ", ".join(str(v) for v in value) if isinstance(value, list) else str(value)
                )
        response = client.post(
            "/presets/master_audio/1.0.0/edit", data=form, follow_redirects=False
        )
        assert response.status_code == 303
        assert "saved=master_audio@1.1.0" in response.headers["location"]
        banner = client.get("/presets?saved=master_audio@1.1.0").text
        assert "Saved" in banner and "master_audio@1.1.0" in banner

    def test_gui_validation_failure_keeps_typed_values(self, env) -> None:
        _, client = env
        model = client.get("/api/v1/presets/master_audio/1.0.0/editable").json()
        loudness = next(
            r for r in model["rules"] if r["parameter_id"] == "audio.integrated_loudness"
        )
        prefix = f"r__{loudness['rule_id']}__"
        form = {
            "edited_by": "gui-test",
            f"{prefix}min": "-10",
            f"{prefix}max": "-20",  # min > max: invalid
            f"{prefix}severity": loudness["severity"],
            f"{prefix}enabled": "on",
        }
        response = client.post("/presets/master_audio/1.0.0/edit", data=form)
        assert response.status_code == 200  # re-rendered editor, not a redirect
        assert "failed validation" in response.text
        assert 'value="-10"' in response.text  # typed values survive the error

    def test_unknown_preset_is_a_clean_404_page(self, env) -> None:
        _, client = env
        page = client.get("/presets/nope/9.9.9/edit")
        assert "Unknown preset" in page.text
