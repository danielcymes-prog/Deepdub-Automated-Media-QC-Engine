"""Master preset synthesis + library demotion (docs/master-preset-spec.md, ADR-030)."""

import sys
from pathlib import Path

from deepdub_qc.models.parameters import CATALOGUE, ImplementationStatus
from deepdub_qc.presets.loader import load_preset
from deepdub_qc.server.catalog import (
    MASTER_CLIENT,
    PresetInfo,
    build_catalog,
    picker_groups,
    split_current,
    version_key,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from build_master_presets import (  # noqa: E402
    classify,
    load_corpus,
    main,
    render_master,
    synthesize,
)

PRESETS_ROOT = REPO_ROOT / "presets"


class TestSynthesis:
    def test_deterministic_over_the_committed_corpus(self) -> None:
        corpus = [d for d in load_corpus() if classify(d) == "video"]
        first = render_master(
            "master_video", "t", "av_delivery", len(corpus), synthesize(corpus), "2026-07-28"
        )
        second = render_master(
            "master_video", "t", "av_delivery", len(corpus), synthesize(corpus), "2026-07-28"
        )
        assert first == second

    def test_disagreements_carry_distribution_comments(self) -> None:
        corpus = [d for d in load_corpus() if classify(d) == "video"]
        text = render_master(
            "master_video", "t", "av_delivery", len(corpus), synthesize(corpus), "2026-07-28"
        )
        # The corpus demonstrably disagrees on loudness targets; the approving
        # engineer must see the spread, not just the winner.
        assert "# corpus values:" in text

    def test_one_rule_per_parameter_with_unique_ids(self) -> None:
        corpus = [d for d in load_corpus() if classify(d) == "audio"]
        rules = synthesize(corpus)
        parameters = [occ.parameter_id for occ, _ in rules]
        rule_ids = [occ.rule_id for occ, _ in rules]
        assert len(parameters) == len(set(parameters))
        assert len(rule_ids) == len(set(rule_ids))

    def test_severity_and_blocking_are_a_corpus_pair(self) -> None:
        """Independent majorities must not invent a (severity, blocking) combo
        that no corpus rule for that parameter actually has."""
        corpus = [d for d in load_corpus() if classify(d) == "video"]
        pairs_in_corpus: dict[str, set[tuple[str, bool]]] = {}
        for document in corpus:
            defaults = document.get("defaults", {})
            for rule in document.get("rules", []):
                pairs_in_corpus.setdefault(rule["parameter_id"], set()).add(
                    (
                        rule.get("severity", defaults.get("severity", "error")),
                        bool(rule.get("blocking", defaults.get("blocking", True))),
                    )
                )
        for occ, _ in synthesize(corpus):
            assert (occ.severity, occ.blocking) in pairs_in_corpus[occ.parameter_id]


class TestCommittedMasters:
    def test_masters_load_and_reference_only_implemented_parameters(self) -> None:
        for name in ("master_video_v1.yaml", "master_audio_v1.yaml"):
            preset = load_preset(PRESETS_ROOT / "master" / name)
            assert preset.preset.status.value == "draft"  # §30: pending approval
            for rule in preset.rules:
                parameter = CATALOGUE[rule.parameter_id]
                assert parameter.implementation is ImplementationStatus.IMPLEMENTED

    def test_regeneration_refuses_to_overwrite_without_force(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "argv", ["build_master_presets"])
        assert main() == 1  # committed masters exist; nothing may be clobbered


def entry(preset_id: str, version: str, client: str = "acme", listed: bool = True) -> PresetInfo:
    return PresetInfo(
        preset_id=preset_id,
        version=version,
        client=client,
        content_type="av_delivery",
        status="draft",
        title=preset_id,
        description="",
        effective_date="2026-08-01",
        path=Path(f"{preset_id}_{version}.yaml"),
        listed=listed,
    )


class TestVersionCollapse:
    """One current version per preset id; the rest is history (ADR-033)."""

    def test_versions_order_numerically_not_lexically(self) -> None:
        assert version_key("1.10.0") > version_key("1.9.0")

    def test_split_current_keeps_the_numerically_newest(self) -> None:
        catalog = [entry("a", "1.9.0"), entry("a", "1.10.0"), entry("b", "1.0.0")]
        current, history = split_current(catalog)
        assert [(e.preset_id, e.version) for e in current] == [("a", "1.10.0"), ("b", "1.0.0")]
        assert [e.version for e in history["a"]] == ["1.9.0"]
        assert "b" not in history  # single-version presets carry no disclosure

    def test_history_lists_newest_first(self) -> None:
        catalog = [entry("a", "1.0.0"), entry("a", "1.2.0"), entry("a", "1.1.0")]
        _, history = split_current(catalog)
        assert [e.version for e in history["a"]] == ["1.1.0", "1.0.0"]

    def test_picker_offers_only_the_current_version(self) -> None:
        groups = picker_groups([entry("a", "1.0.0"), entry("a", "1.1.0")])
        assert [(p.preset_id, p.version) for _, ps in groups for p in ps] == [("a", "1.1.0")]


class TestLibraryDemotion:
    def test_library_is_unlisted_and_everything_else_listed(self) -> None:
        catalog = build_catalog(PRESETS_ROOT)
        by_id = {entry.preset_id: entry for entry in catalog}
        assert not by_id["vc002_ard_zdf_hdf01a_1080i25_8_track_xdcam_hd422_v1_2"].listed
        assert by_id["marimba_deliver_audio"].listed
        assert by_id["master_video"].listed
        assert by_id["master_audio"].listed

    def test_picker_pins_masters_first_and_hides_the_library(self) -> None:
        groups = picker_groups(build_catalog(PRESETS_ROOT))
        assert groups[0][0] == MASTER_CLIENT
        assert {p.preset_id for p in groups[0][1]} >= {"master_video", "master_audio"}
        clients = [client for client, _ in groups]
        assert "vidchecker-library" not in clients
