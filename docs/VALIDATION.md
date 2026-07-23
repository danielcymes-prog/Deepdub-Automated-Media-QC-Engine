# Validation Record — Vidchecker Parity (Risk R2)

Evidence that deepdub-qc measurements agree with Telestream Vidchecker on
production material. Each entry compares both tools on the **same file bytes**.

## Parity point 1 — ART_OF_CRIME_S08_EP01_FRA.wav (2026-07-23)

- **File:** 848,530,934 bytes, WAV PCM 24-bit / 48 kHz / stereo, 49:06.24
  (identical size in both reports; deepdub-qc sha256
  `9c6326a2f4b6f5eccda016f70e418692ec2178fdb8e00f125201641cd4db972b`)
- **Vidchecker:** 8.2.2, template "Deliver-Audio" (id 115), XML report
  task 34286, run 2026-07-22, verdict **Warning** (3 alerts)
- **deepdub-qc:** 0.1.0, `audio.analysis.ffmpeg/1.0.0`, ffmpeg
  N-121567-g00c23bafb0, preset `marimba_deliver_audio` v1.0.0
  (sha `b0350520…`), verdict **WARNING**

| Measurement | Vidchecker | deepdub-qc | Delta | Assessment |
|---|---|---|---|---|
| Integrated loudness (ITU 1770 / EBU I) | -25.35 LUFS | -25.4 LUFS | 0.05 LU | Within broadcast meter tolerance (±0.1 LU) |
| Min level / trailing silence duration | 178.3 s | 178.496 s | 0.2 s | Different definitions (-95 dB RMS windowed vs -60 dB silencedetect) converge on the same event |
| Violation span | 00:46:07 → 00:49:06 | 2767.744 s → 2946.24 s | < 1 s | Vidchecker timecodes truncated to whole seconds |
| Clipping | no alerts | flat factor 0.0, peak -6.25 dBFS | — | Agreement (headroom precludes clipping) |
| Codec / rate / channels / bit depth | PCM / 48 kHz / 2ch / 24-bit | pcm_s24le / 48 kHz / 2ch | — | Agreement |
| Overall verdict | Warning | WARNING | — | Same verdict, same root cause |

**Reproducibility note:** the same file was analyzed twice (2026-07-22 with
three separate audio detectors; 2026-07-23 with the consolidated single-pass
detector). Every measurement was bit-identical across the architecture
change (ADR-008 in practice).

## Method notes

- **Automated harness:** `deepdub-qc compare -r report.json -x vidchecker.xml`
  (src/deepdub_qc/comparison/) encodes this method - byte-identity check
  first, then loudness (+/-0.3 LU default), min-level/silence spans
  (+/-1.0 s, max-overlap matching), clipping presence, and detection of
  tests Vidchecker could not run. Exit 0 = parity, 2 = mismatch,
  5 = different files. `--markdown-out` emits a table for this document.
  Re-run on parity point 1: 4 MATCH, 0 MISMATCH.

- Vidchecker XML report export (namespace `http://www.vidcheck.com/services`)
  is machine-readable: `TaskAlert` elements carry `AlertTypeId`, spans, and
  `DetailParams` (e.g. `LoudnessDb`). The comparison harness (backlog #32)
  should consume this format rather than PDF.
- An earlier attempted comparison used reports from *different masters of the
  same episode* (`V02_FINAL MIX` vs `FRA`): durations and silence structure
  matched but levels differed by 2.4 LU. Parity claims require identical
  bytes; the file size + hash check is mandatory.

## EBU Tech 3341/3342 conformance (2026-07-23)

The full EBU Loudness test set v05 (68 assertable vectors) was run through
the toolchain (ffmpeg ebur128 + deepdub-qc parser). **All 68 pass** against
the specification targets and tolerances (manifest:
`tests/fixtures/ebu_manifest.yaml`; suite:
`tests/integration/test_ebu_conformance.py`, skips when fixtures absent):

- Integrated loudness: all cases within +/-0.1 LU, including 5.0/5.1
  multichannel (case 6) and both program-material sequences.
- Loudness range: 10/5/20/15/5/15 LU targets all measured exactly (+/-1 LU).
- Max short-term (cases 9, 10-1..20): within +/-0.1 LU.
- True peak (cases 15-23): -6.0 / +3.0 / 0.0 dBTP all inside +0.2/-0.4 dB.
- Max momentary (case 13 bursts): documented limitation - max M derives
  from 100 ms ebur128 log lines, undersampling very short bursts by up to
  0.5 LU; tolerance relaxed to -0.6 in the manifest for those vectors only.

Environment: ffmpeg 4.4.2 (dev sandbox). Re-run on the pinned Docker image
and on the RDP with `uv run pytest tests/integration/test_ebu_conformance.py`
after placing the test set under tests/fixtures/ebu/.

## Capability gap — Alphorn AD multi-mono master (2026-07-23)

MCHNCL_EPS-201 (Mechanical, audio-only MOV, 3,141,703,557 bytes, 45:19.84,
8 x mono PCM 24/48k = 5.1 + 2.0 downmix; layout confirmed by ffprobe:
FL FR C LFE BL BR DL DR). Both tools ran the same bytes:

- **Vidchecker 8.2.2** (template "Delivery", task 34384, 2 s): produced
  **zero measurements**. Its audio tests bind to track 1 channels 1-2; every
  track is mono, so loudness/clipping/min-level/dual-mono all reported
  "Some channels configured in this test are not present. This test will
  not be run." Verdict Warning = nine could-not-test alerts.
- **deepdub-qc 0.1.0** (preset `alphorn_ad_full_mix` draft, 7 min 3 s):
  full loudness/true-peak/silence/clipping measurements for **all eight
  tracks**. Structure PASS (mov, 8 tracks, mono, pcm_s24le, 48 kHz);
  no clipping on any track (flat factor 0.0, peaks <= -2.07 dBFS);
  per-track integrated loudness FL -28.8 / FR -28.9 / C -22.4 /
  LFE -70.0 / BL -33.5 / BR -33.2 / DL -21.6 / DR -21.7 LUFS.
  One WARNING: the LFE track's -70 LUFS falls outside the placeholder
  loudness bounds - correct behavior for a generic per-track rule, and
  evidence the preset needs channel-role-aware expectations (exempt LFE).

Not a measurement-parity point (Vidchecker produced no numbers to compare);
recorded as a **capability demonstration**: multi-mono localization
masters - the dominant Deepdub asset shape - are testable per-track by
deepdub-qc and untestable by the Vidchecker template model in use.

**Follow-up identified:** filename targets like "-27LU" apply to the 5.1
program measured jointly (ITU 1770 channel weighting), not to individual
mono tracks. Requires a track-grouping loudness capability (backlog #35).

## Outstanding validation

- Video-side parity (black frames, freeze frames) — needs a Vidchecker
  report + deepdub-qc run on the same MOV.
- Multi-parameter coverage: Vidchecker "Clipping (medium)" on a file that
  actually clips, vs our flat-factor/peak indicators.
- Spec-grade max-momentary metering (replace log-line sampling; removes the
  case-13 tolerance relaxation).
