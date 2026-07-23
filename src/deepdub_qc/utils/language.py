"""Language-tag normalization (backlog #33).

Why: containers disagree about language codes. MOV stores ISO 639-2/B
("ger", "fre"), MXF often 639-2/T ("deu", "fra"), sidecars and specs use
639-1 ("de", "fr") or BCP-47 ("de-DE"). Without one canonical form,
language-based rule selectors silently miss streams (field report:
``language=deu`` dropped by the MOV muxer, ``ger`` accepted).

Canonical form: lowercase ISO 639-1 where a mapping exists; otherwise the
lowercased primary subtag unchanged. Both measurements and preset selector
values are normalized, so presets may use any of the synonym spellings.

Inputs: a raw language tag (or None). Outputs: normalized tag (or None).
Side effects: none.
"""

from __future__ import annotations

#: ISO 639-2 (bibliographic and terminological) -> ISO 639-1 for languages
#: seen in dubbing/localization work. Unmapped codes pass through unchanged.
_ISO_639_2_TO_1 = {
    "alb": "sq",
    "sqi": "sq",
    "ara": "ar",
    "arm": "hy",
    "hye": "hy",
    "baq": "eu",
    "eus": "eu",
    "bul": "bg",
    "bur": "my",
    "mya": "my",
    "cat": "ca",
    "chi": "zh",
    "zho": "zh",
    "cze": "cs",
    "ces": "cs",
    "dan": "da",
    "dut": "nl",
    "nld": "nl",
    "eng": "en",
    "est": "et",
    "fin": "fi",
    "fre": "fr",
    "fra": "fr",
    "geo": "ka",
    "kat": "ka",
    "ger": "de",
    "deu": "de",
    "gre": "el",
    "ell": "el",
    "heb": "he",
    "hin": "hi",
    "hrv": "hr",
    "hun": "hu",
    "ice": "is",
    "isl": "is",
    "ind": "id",
    "ita": "it",
    "jpn": "ja",
    "kor": "ko",
    "lav": "lv",
    "lit": "lt",
    "mac": "mk",
    "mkd": "mk",
    "may": "ms",
    "msa": "ms",
    "nor": "no",
    "per": "fa",
    "fas": "fa",
    "pol": "pl",
    "por": "pt",
    "rum": "ro",
    "ron": "ro",
    "rus": "ru",
    "slo": "sk",
    "slk": "sk",
    "slv": "sl",
    "spa": "es",
    "srp": "sr",
    "swe": "sv",
    "tha": "th",
    "tur": "tr",
    "ukr": "uk",
    "vie": "vi",
    "wel": "cy",
    "cym": "cy",
}


def normalize_language(tag: str | None) -> str | None:
    """Canonical lowercase language code; None and empty pass through as None.

    "ger", "deu", "de", "de-DE" all normalize to "de". Unknown codes are
    returned lowercased (primary subtag only) so nothing is invented.
    """
    if tag is None:
        return None
    primary = tag.strip().lower().replace("_", "-").split("-", 1)[0]
    if not primary:
        return None
    return _ISO_639_2_TO_1.get(primary, primary)
