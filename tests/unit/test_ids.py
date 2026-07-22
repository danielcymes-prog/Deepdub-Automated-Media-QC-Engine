"""Determinism of content-derived identifiers (ADR-008)."""

from deepdub_qc.utils.ids import deterministic_id, finding_id, measurement_id


class TestDeterministicId:
    def test_same_inputs_same_id(self) -> None:
        a = deterministic_id("audio.loudness", 1, -19.7)
        b = deterministic_id("audio.loudness", 1, -19.7)
        assert a == b

    def test_different_inputs_different_id(self) -> None:
        assert deterministic_id("a", 1) != deterministic_id("a", 2)

    def test_order_matters(self) -> None:
        assert deterministic_id("a", "b") != deterministic_id("b", "a")

    def test_none_is_distinct_from_empty_string(self) -> None:
        assert deterministic_id(None) != deterministic_id("")

    def test_dict_key_order_is_irrelevant(self) -> None:
        assert deterministic_id({"x": 1, "y": 2}) == deterministic_id({"y": 2, "x": 1})


class TestDomainIds:
    def test_measurement_id_stable(self) -> None:
        args = ("metadata.ffprobe", "1.0.0", "video.width", 0, None, None, 1920)
        assert measurement_id(*args) == measurement_id(*args)

    def test_finding_id_depends_on_status(self) -> None:
        base = ("video-width", "1.0.0", "video.width", 0, None)
        assert finding_id(*base, "PASS") != finding_id(*base, "FAIL")
