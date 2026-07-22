"""Preset loader and preset-level invariants."""

from pathlib import Path

import pytest

from deepdub_qc.exceptions import (
    PresetNotFoundError,
    PresetParseError,
    PresetValidationError,
)
from deepdub_qc.models.enums import PresetStatus, Severity
from deepdub_qc.presets.loader import load_preset, preset_sha256

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLE_PRESET = REPO_ROOT / "presets" / "examples" / "generic_broadcast_v1.yaml"

VALID_MINIMAL = """
schema_version: 1.0.0
preset:
  id: test_preset
  version: 1.0.0
  client: generic
  content_type: test
  title: Test Preset
  owner: qa
  status: draft
  effective_date: 2026-07-22
defaults:
  blocking: false
  severity: warning
rules:
  - rule_id: video-width
    parameter_id: video.width
    operator: equals
    expected:
      value: 1920
  - rule_id: loudness
    parameter_id: audio.integrated_loudness
    operator: between
    expected:
      min: -24.0
      max: -22.0
    severity: error
    blocking: true
"""


class TestLoadPreset:
    def test_example_preset_is_valid(self) -> None:
        preset = load_preset(EXAMPLE_PRESET)
        assert preset.preset.id == "generic_broadcast"
        assert preset.preset.status == PresetStatus.DRAFT
        assert len(preset.rules) == 9

    def test_defaults_fill_omitted_severity_and_blocking(self, tmp_path: Path) -> None:
        path = tmp_path / "p.yaml"
        path.write_text(VALID_MINIMAL, encoding="utf-8")
        preset = load_preset(path)
        by_id = {rule.rule_id: rule for rule in preset.rules}
        # omitted -> inherits defaults
        assert by_id["video-width"].severity == Severity.WARNING
        assert by_id["video-width"].blocking is False
        # explicit -> preserved
        assert by_id["loudness"].severity == Severity.ERROR
        assert by_id["loudness"].blocking is True

    def test_missing_file_raises_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(PresetNotFoundError):
            load_preset(tmp_path / "missing.yaml")

    def test_malformed_yaml_raises_parse_error(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("rules: [unclosed", encoding="utf-8")
        with pytest.raises(PresetParseError):
            load_preset(path)

    def test_non_mapping_root_raises_parse_error(self, tmp_path: Path) -> None:
        path = tmp_path / "list.yaml"
        path.write_text("- just\n- a list\n", encoding="utf-8")
        with pytest.raises(PresetParseError):
            load_preset(path)

    def test_duplicate_rule_ids_rejected(self, tmp_path: Path) -> None:
        duplicated = VALID_MINIMAL.replace("rule_id: loudness", "rule_id: video-width")
        path = tmp_path / "dup.yaml"
        path.write_text(duplicated, encoding="utf-8")
        with pytest.raises(PresetValidationError) as excinfo:
            load_preset(path)
        assert any("duplicate rule_id" in err for err in excinfo.value.errors)

    def test_bad_semver_rejected(self, tmp_path: Path) -> None:
        bad = VALID_MINIMAL.replace("version: 1.0.0", "version: v1.0")
        path = tmp_path / "semver.yaml"
        path.write_text(bad, encoding="utf-8")
        with pytest.raises(PresetValidationError) as excinfo:
            load_preset(path)
        assert any("semantic version" in err for err in excinfo.value.errors)

    def test_unknown_top_level_keys_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "extra.yaml"
        path.write_text(VALID_MINIMAL + "\nsurprise: true\n", encoding="utf-8")
        with pytest.raises(PresetValidationError):
            load_preset(path)


class TestPresetSha256:
    def test_hash_is_stable_and_hex(self, tmp_path: Path) -> None:
        path = tmp_path / "p.yaml"
        path.write_text(VALID_MINIMAL, encoding="utf-8")
        digest = preset_sha256(path)
        assert digest == preset_sha256(path)
        assert len(digest) == 64
        int(digest, 16)  # raises if not hex
