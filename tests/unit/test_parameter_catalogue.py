"""Contract tests for the parameter catalogue (ADR-021).

These are the tests that make the catalogue load-bearing. Without them it is a
document that drifts: a detector could start emitting an uncatalogued parameter
(unusable by presets), or the catalogue could promise a parameter nothing
produces (a rule that can never be evaluated).
"""

from __future__ import annotations

import unittest.mock
from pathlib import Path

import pytest

from deepdub_qc.detectors.registry import all_detectors
from deepdub_qc.exceptions import PresetValidationError
from deepdub_qc.models import parameters
from deepdub_qc.models.parameters import CATALOGUE, ImplementationStatus, ValidationStatus
from deepdub_qc.presets.loader import load_preset

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _declared_by_detector() -> dict[str, list[str]]:
    """parameter_id -> detector ids that declare it."""
    declared: dict[str, list[str]] = {}
    for detector in all_detectors():
        for parameter_id in detector.parameters:
            declared.setdefault(parameter_id, []).append(detector.detector_id)
    return declared


class TestCatalogueInternalConsistency:
    def test_ids_are_unique(self) -> None:
        """Uniqueness must be checked against _DEFINITIONS, not CATALOGUE:
        the mapping is unique by construction, so iterating its values can
        never observe a duplicate that keyed construction collapsed."""
        ids = [definition.parameter_id for definition in parameters._DEFINITIONS]
        assert len(ids) == len(set(ids))
        assert len(CATALOGUE) == len(parameters._DEFINITIONS)

    def test_duplicate_definitions_are_refused(self) -> None:
        """_build_catalogue raises rather than letting a later duplicate
        silently replace (and potentially demote) an earlier definition."""
        first = parameters._DEFINITIONS[0]
        with (
            unittest.mock.patch.object(
                parameters, "_DEFINITIONS", (*parameters._DEFINITIONS, first)
            ),
            pytest.raises(ValueError, match="duplicate parameter_id"),
        ):
            parameters._build_catalogue()

    def test_keys_match_definitions(self) -> None:
        for key, definition in CATALOGUE.items():
            assert key == definition.parameter_id

    def test_implemented_iff_detector_named(self) -> None:
        """A parameter is implemented exactly when a detector owns it.

        Guards the two ways this drifts: claiming IMPLEMENTED with no detector
        (nothing produces it) and naming a detector while PLANNED (misleading).
        """
        for definition in CATALOGUE.values():
            implemented = definition.implementation is ImplementationStatus.IMPLEMENTED
            assert implemented == (definition.detector_id is not None), definition.parameter_id

    def test_accuracy_claims_are_backed_by_the_validation_record(self) -> None:
        """Only measurements with external evidence may claim accuracy.

        ADR-021 deliberately keeps this conservative: being implemented and
        unit-tested says nothing about agreement with a broadcast meter. If a
        new parameter needs a claim here, it needs a docs/VALIDATION.md entry
        first — update both together.
        """
        claimed = {
            definition.parameter_id
            for definition in CATALOGUE.values()
            if definition.validation is not ValidationStatus.UNVALIDATED
        }
        assert claimed == {
            # EBU Tech 3341/3342 conformance, 68/68 vectors.
            "audio.integrated_loudness",
            "audio.loudness_range",
            "audio.true_peak",
            "audio.max_short_term_loudness",
            "audio.max_momentary_loudness",
            # Vidchecker parity on identical bytes, differing definitions.
            "audio.tail_silence_duration",
            "audio.low_rms_event",
        }

    def test_planned_parameters_are_not_offered_to_presets(self) -> None:
        implemented = parameters.implemented_ids()
        for definition in CATALOGUE.values():
            if definition.implementation is ImplementationStatus.PLANNED:
                assert definition.parameter_id not in implemented


class TestCatalogueMatchesDetectors:
    def test_every_declared_parameter_is_catalogued(self) -> None:
        """Adding a detector parameter without cataloguing it fails here.

        An uncatalogued parameter is unreachable: presets may not reference it,
        so the measurement would be produced and never evaluated.
        """
        uncatalogued = sorted(set(_declared_by_detector()) - set(CATALOGUE))
        assert not uncatalogued, (
            f"detectors emit uncatalogued parameters: {uncatalogued}. "
            "Add them to models/parameters.py and run `make params`."
        )

    def test_every_declared_parameter_is_marked_implemented(self) -> None:
        wrong_status = sorted(
            parameter_id
            for parameter_id in _declared_by_detector()
            if CATALOGUE[parameter_id].implementation is not ImplementationStatus.IMPLEMENTED
        )
        assert not wrong_status

    def test_every_implemented_parameter_has_a_producer(self) -> None:
        """The reverse drift: the catalogue promising something nothing emits."""
        orphaned = sorted(parameters.implemented_ids() - set(_declared_by_detector()))
        assert not orphaned, (
            f"catalogue marks these implemented but no detector declares them: {orphaned}"
        )

    def test_detector_attribution_is_correct(self) -> None:
        for parameter_id, detector_ids in _declared_by_detector().items():
            assert CATALOGUE[parameter_id].detector_id in detector_ids

    def test_no_parameter_is_claimed_by_two_detectors(self) -> None:
        """Two producers for one parameter makes measurement provenance ambiguous."""
        shared = {
            parameter_id: detector_ids
            for parameter_id, detector_ids in _declared_by_detector().items()
            if len(detector_ids) > 1
        }
        assert not shared


class TestLookupHelpers:
    def test_get_returns_definition(self) -> None:
        definition = parameters.get("audio.integrated_loudness")
        assert definition is not None
        assert definition.unit == "LUFS"

    def test_get_unknown_returns_none(self) -> None:
        assert parameters.get("audio.not_a_real_parameter") is None

    def test_suggest_finds_near_miss(self) -> None:
        assert "audio.integrated_loudness" in parameters.suggest("audio.integrated_loudnes")

    def test_suggest_finds_transposition(self) -> None:
        assert "video.width" in parameters.suggest("video.witdh")

    def test_suggest_returns_nothing_for_gibberish(self) -> None:
        assert parameters.suggest("zzzzzzzzzzzz") == []

    def test_suggest_never_offers_planned_parameters(self) -> None:
        """Suggesting an unimplemented parameter would send the author in circles."""
        implemented = parameters.implemented_ids()
        for probe in ("deepdub.unresolved_qc_marker", "subtitle.cue_counts", "video.bit_dept"):
            assert set(parameters.suggest(probe)) <= implemented


class TestPresetParameterValidation:
    """Load-time rejection of rules no detector can satisfy."""

    def _write(self, path: Path, parameter_id: str) -> Path:
        path.write_text(
            "schema_version: 1.0.0\n"
            "preset:\n"
            "  id: catalogue_probe\n"
            "  version: 1.0.0\n"
            "  client: test\n"
            "  content_type: test\n"
            "  title: Catalogue probe\n"
            "  description: Fixture for parameter-catalogue validation.\n"
            "  owner: engineering\n"
            "  status: draft\n"
            "  effective_date: 2026-07-26\n"
            "rules:\n"
            "  - rule_id: probe\n"
            f"    parameter_id: {parameter_id}\n"
            "    operator: exists\n"
            "    severity: error\n"
            "    blocking: true\n",
            encoding="utf-8",
        )
        return path

    def test_implemented_parameter_is_accepted(self, tmp_path: Path) -> None:
        preset = load_preset(self._write(tmp_path / "ok.yaml", "audio.integrated_loudness"))
        assert preset.rules[0].parameter_id == "audio.integrated_loudness"

    def test_unknown_parameter_is_rejected_with_a_suggestion(self, tmp_path: Path) -> None:
        with pytest.raises(PresetValidationError) as excinfo:
            load_preset(self._write(tmp_path / "typo.yaml", "audio.integrated_loudnes"))

        errors = " ".join(excinfo.value.errors)
        assert "not in the parameter catalogue" in errors
        assert "audio.integrated_loudness" in errors, "the near-match should be suggested"

    def test_planned_parameter_is_rejected_as_unmeasurable(self, tmp_path: Path) -> None:
        """The silent-pass path ADR-021 closes.

        Before the catalogue, a non-blocking rule over an unproduced parameter
        became a SKIPPED finding and the operator saw a complete-looking report
        for a check that never ran.
        """
        with pytest.raises(PresetValidationError) as excinfo:
            load_preset(self._write(tmp_path / "planned.yaml", "deepdub.unresolved_qc_markers"))

        errors = " ".join(excinfo.value.errors)
        assert "not implemented yet" in errors
        assert "could never be evaluated" in errors

    def test_error_names_the_offending_rule(self, tmp_path: Path) -> None:
        with pytest.raises(PresetValidationError) as excinfo:
            load_preset(self._write(tmp_path / "named.yaml", "audio.nonsense"))
        assert "rules.probe.parameter_id" in " ".join(excinfo.value.errors)


class TestShippedPresetsRemainValid:
    """Regression guard: enforcing the catalogue must not break real presets."""

    @pytest.mark.parametrize(
        "preset_path",
        sorted(
            list((REPO_ROOT / "presets").rglob("*.yaml"))
            + list((REPO_ROOT / "tests" / "fixtures" / "presets").rglob("*.yaml"))
        ),
        ids=lambda path: path.name,
    )
    def test_preset_loads(self, preset_path: Path) -> None:
        load_preset(preset_path)
