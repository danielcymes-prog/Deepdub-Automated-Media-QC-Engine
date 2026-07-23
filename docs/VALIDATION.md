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

- Vidchecker XML report export (namespace `http://www.vidcheck.com/services`)
  is machine-readable: `TaskAlert` elements carry `AlertTypeId`, spans, and
  `DetailParams` (e.g. `LoudnessDb`). The comparison harness (backlog #32)
  should consume this format rather than PDF.
- An earlier attempted comparison used reports from *different masters of the
  same episode* (`V02_FINAL MIX` vs `FRA`): durations and silence structure
  matched but levels differed by 2.4 LU. Parity claims require identical
  bytes; the file size + hash check is mandatory.

## Outstanding validation

- EBU Tech 3341/3342 reference vectors (formal loudness conformance) —
  requires the official test files (network-restricted in the dev sandbox).
- Video-side parity (black frames, freeze frames) — needs a Vidchecker
  report + deepdub-qc run on the same MOV.
- Multi-parameter coverage: Vidchecker "Clipping (medium)" on a file that
  actually clips, vs our flat-factor/peak indicators.
