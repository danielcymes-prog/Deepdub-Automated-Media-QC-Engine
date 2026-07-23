# EBU Loudness Test Set fixtures

Place the WAV files from the **EBU Loudness test set v05** in this directory
to enable the loudness conformance suite
(`tests/integration/test_ebu_conformance.py`).

- Download: https://tech.ebu.ch/publications/ebu_loudness_test_set
- Licence: EBU provides the material for **technical testing purposes only**,
  so the WAVs are intentionally NOT committed to this repository
  (see `.gitignore`). The conformance suite skips automatically when the
  files are absent.
- Expected values and tolerances live in `tests/fixtures/ebu_manifest.yaml`
  (committed), taken from EBU Tech 3341 v3 and Tech 3342 v3.
