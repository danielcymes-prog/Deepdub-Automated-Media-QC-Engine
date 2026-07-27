"""Preset governance: approval lock and immutability verification (ADR-013)."""

import logging
from pathlib import Path

import pytest
from typer.testing import CliRunner

from deepdub_qc.cli import app
from deepdub_qc.exceptions import PresetError
from deepdub_qc.exit_codes import ExitCode
from deepdub_qc.presets.governance import (
    LOCK_FILENAME,
    build_lock,
    read_lock,
    verify_approved,
    write_lock,
)
from deepdub_qc.server.catalog import build_catalog

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
runner = CliRunner()

PRESET_TEMPLATE = """\
schema_version: 1.0.0
preset:
  id: {preset_id}
  version: 1.0.0
  client: testclient
  content_type: test
  title: Governance Test
  owner: qa
  status: {status}
  effective_date: 2026-07-22
rules:
  - rule_id: width
    parameter_id: video.width
    operator: equals
    expected:
      value: 1920
"""


def make_preset_dir(tmp_path: Path, status: str = "approved") -> Path:
    root = tmp_path / "presets"
    (root / "clients" / "testclient").mkdir(parents=True)
    (root / "clients" / "testclient" / "p_v1.yaml").write_text(
        PRESET_TEMPLATE.format(preset_id="p", status=status), encoding="utf-8"
    )
    return root


class TestLock:
    def test_lock_records_only_approved(self, tmp_path: Path) -> None:
        root = make_preset_dir(tmp_path, status="draft")
        assert build_lock(root) == {}
        root2 = make_preset_dir(tmp_path / "second", status="approved")
        lock = build_lock(root2)
        assert list(lock) == ["clients/testclient/p_v1.yaml"]

    def test_verify_ok_after_lock(self, tmp_path: Path) -> None:
        root = make_preset_dir(tmp_path)
        write_lock(root)
        assert verify_approved(root) == []

    def test_unlocked_approved_preset_flagged(self, tmp_path: Path) -> None:
        root = make_preset_dir(tmp_path)
        problems = verify_approved(root)  # no lock written
        assert len(problems) == 1
        assert "not recorded" in problems[0]

    def test_tampered_approved_preset_flagged(self, tmp_path: Path) -> None:
        root = make_preset_dir(tmp_path)
        write_lock(root)
        target = root / "clients" / "testclient" / "p_v1.yaml"
        target.write_text(
            target.read_text(encoding="utf-8").replace("value: 1920", "value: 1280"),
            encoding="utf-8",
        )
        problems = verify_approved(root)
        assert len(problems) == 1
        assert "immutable" in problems[0]

    def test_demoted_approved_preset_flagged(self, tmp_path: Path) -> None:
        root = make_preset_dir(tmp_path)
        write_lock(root)
        target = root / "clients" / "testclient" / "p_v1.yaml"
        target.write_text(
            target.read_text(encoding="utf-8").replace("status: approved", "status: draft"),
            encoding="utf-8",
        )
        problems = verify_approved(root)
        assert any("no longer has approved status" in p for p in problems)

    def test_deleted_approved_preset_flagged(self, tmp_path: Path) -> None:
        root = make_preset_dir(tmp_path)
        write_lock(root)
        (root / "clients" / "testclient" / "p_v1.yaml").unlink()
        problems = verify_approved(root)
        assert any("file is missing" in p for p in problems)


def _break_preset_parameter(root: Path) -> Path:
    """Make the preset reference a parameter the catalogue does not implement,
    without touching its approved status — the accidental-breakage scenario."""
    target = root / "clients" / "testclient" / "p_v1.yaml"
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            "parameter_id: video.width", "parameter_id: video.does_not_exist"
        ),
        encoding="utf-8",
    )
    return target


class TestSwallowedPresetErrorsAreVisible:
    """Regression: PresetError was caught with a bare `continue`, so a preset
    that stopped loading vanished from the lock (and the catalog) silently."""

    def test_build_lock_logs_skipped_presets(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        root = make_preset_dir(tmp_path)
        _break_preset_parameter(root)
        with caplog.at_level(logging.WARNING, logger="deepdub_qc.presets.governance"):
            assert build_lock(root) == {}
        assert any("p_v1.yaml" in record.message for record in caplog.records)

    def test_write_lock_refuses_to_drop_a_locked_preset_that_stopped_loading(
        self, tmp_path: Path
    ) -> None:
        root = make_preset_dir(tmp_path)
        write_lock(root)
        _break_preset_parameter(root)
        before = read_lock(root)
        with pytest.raises(PresetError, match="no longer loads"):
            write_lock(root)
        assert read_lock(root) == before, "a refused regeneration must not touch the lock"

    def test_write_lock_still_allows_deliberate_demotion(self, tmp_path: Path) -> None:
        """A demoted preset loads fine; dropping it is a reviewable decision,
        not silent breakage, so regeneration must keep working."""
        root = make_preset_dir(tmp_path)
        write_lock(root)
        target = root / "clients" / "testclient" / "p_v1.yaml"
        target.write_text(
            target.read_text(encoding="utf-8").replace("status: approved", "status: draft"),
            encoding="utf-8",
        )
        write_lock(root)
        assert read_lock(root) == {}

    def test_write_lock_still_allows_deleted_preset(self, tmp_path: Path) -> None:
        """Deletion is visible in the lock diff and flagged by verify_approved;
        regeneration itself must not crash on it."""
        root = make_preset_dir(tmp_path)
        write_lock(root)
        (root / "clients" / "testclient" / "p_v1.yaml").unlink()
        write_lock(root)
        assert read_lock(root) == {}

    def test_build_catalog_logs_skipped_presets(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        root = make_preset_dir(tmp_path)
        _break_preset_parameter(root)
        with caplog.at_level(logging.WARNING, logger="deepdub_qc.server.catalog"):
            assert build_catalog(root) == []
        assert any(
            "p_v1.yaml" in record.message and "video.does_not_exist" in record.message
            for record in caplog.records
        ), "the loader's actionable message must reach the log"


class TestGovernanceCli:
    def test_verify_clean_directory(self, tmp_path: Path) -> None:
        root = make_preset_dir(tmp_path)
        write_lock(root)
        result = runner.invoke(app, ["presets", "verify", str(root)])
        assert result.exit_code == 0, result.output

    def test_verify_reports_violation(self, tmp_path: Path) -> None:
        root = make_preset_dir(tmp_path)  # approved but never locked
        result = runner.invoke(app, ["presets", "verify", str(root)])
        assert result.exit_code == ExitCode.INVALID_CONFIGURATION

    def test_lock_command_writes_file(self, tmp_path: Path) -> None:
        root = make_preset_dir(tmp_path)
        result = runner.invoke(app, ["presets", "lock", str(root)])
        assert result.exit_code == 0, result.output
        assert (root / LOCK_FILENAME).is_file()

    def test_validate_directory(self, tmp_path: Path) -> None:
        root = make_preset_dir(tmp_path)
        result = runner.invoke(app, ["presets", "validate", str(root)])
        assert result.exit_code == 0, result.output

    def test_validate_directory_with_invalid_preset(self, tmp_path: Path) -> None:
        root = make_preset_dir(tmp_path)
        (root / "broken.yaml").write_text("schema_version: 1.0.0\n", encoding="utf-8")
        result = runner.invoke(app, ["presets", "validate", str(root)])
        assert result.exit_code == ExitCode.INVALID_CONFIGURATION


class TestRepositoryPresets:
    """The presets shipped in this repository must always be valid and verified."""

    def test_all_repo_presets_valid(self) -> None:
        result = runner.invoke(app, ["presets", "validate", str(REPO_ROOT / "presets")])
        assert result.exit_code == 0, result.output

    def test_repo_approval_lock_verified(self) -> None:
        assert verify_approved(REPO_ROOT / "presets") == []

    def test_marimba_presets_translate_vidchecker_template(self) -> None:
        from deepdub_qc.presets.loader import load_preset  # noqa: PLC0415

        preset = load_preset(
            REPO_ROOT / "presets" / "clients" / "marimba" / "deliver_audio_v1.yaml"
        )
        assert preset.preset.client == "marimba"
        rule_ids = {rule.rule_id for rule in preset.rules}
        assert {"integrated-loudness", "clipping-flat-factor", "internal-silence"} <= rule_ids
        loudness = next(r for r in preset.rules if r.rule_id == "integrated-loudness")
        assert loudness.blocking is True
