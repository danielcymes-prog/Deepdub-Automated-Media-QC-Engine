"""Language-tag normalization (backlog #33)."""

import pytest

from deepdub_qc.utils.language import normalize_language


class TestNormalizeLanguage:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("ger", "de"),  # ISO 639-2/B (MOV muxer)
            ("deu", "de"),  # ISO 639-2/T
            ("de", "de"),  # already 639-1
            ("de-DE", "de"),  # BCP-47 region subtag stripped
            ("DE_de", "de"),  # case/underscore tolerated
            ("fre", "fr"),
            ("fra", "fr"),
            ("eng", "en"),
            ("jpn", "ja"),
            ("chi", "zh"),
            ("zho", "zh"),
            ("und", "und"),  # undetermined passes through
            ("qaa", "qaa"),  # unknown/private-use passes through lowercased
            ("QAA", "qaa"),
        ],
    )
    def test_mappings(self, raw: str, expected: str) -> None:
        assert normalize_language(raw) == expected

    def test_none_and_empty(self) -> None:
        assert normalize_language(None) is None
        assert normalize_language("") is None
        assert normalize_language("  ") is None
