# Parameter Catalogue

<!-- GENERATED FILE — do not edit by hand.
     Source: src/deepdub_qc/models/parameters.py
     Regenerate: make params   (CI fails on drift) -->

The vocabulary of measurable facts. A `parameter_id` is the contract between a detector, which produces measurements, and a preset, which writes rules about them (ADR-021).

**59 implemented**, 37 planned, 96 catalogued in total.

## How to read this

- **Implemented** parameters are produced by a detector today. A preset may only reference these; `deepdub-qc presets validate` rejects anything else, with a suggestion for near-misses.
- **Planned** parameters are agreed facts we intend to measure (handoff section 15). They are catalogued so the intent is reviewable, but a rule referencing one is a validation error, not a silent skip.
- **Scope** `file` means one measurement per asset; `stream` means one per stream, carrying a `stream_index` that rule selectors can target. `timed` means the parameter is event-style: one measurement per occurrence, carrying start and end seconds.
- **Accuracy** is deliberately conservative. `validated` means checked against a specification or reference test set; `cross-checked` means compared with another tool on identical bytes where the definitions differ. Everything else is blank: implemented and unit-tested says nothing about agreement with a broadcast meter. See `docs/VALIDATION.md`.
- **Caveats** are binding on preset authors. A threshold written without reading them may not mean what the author intends.

## File

| Parameter | Name | Type | Unit | Scope | Detector | Accuracy | Description |
|---|---|---|---|---|---|---|---|
| `file.extension` | File Extension | string | — | file | metadata.ffprobe | — | Lowercased file extension without the leading dot. |
| `file.readable` | File Readable | boolean | — | file | metadata.ffprobe | — | Whether the input file exists and is readable by the process. |
| `file.sha256` | File SHA-256 | string | — | file | *planned* | — | SHA-256 of the input bytes. Already recorded on the asset in every result; catalogued for completeness, not yet rule-addressable. |
| `file.size_bytes` | File Size | integer | B | file | metadata.ffprobe | — | Size of the input file in bytes. |
| `filename.pattern` | Filename | string | — | file | metadata.ffprobe | — | The file's basename, for rules that match delivery naming conventions with the regex operator. |

## Container

| Parameter | Name | Type | Unit | Scope | Detector | Accuracy | Description |
|---|---|---|---|---|---|---|---|
| `container.duration` | Container Duration | float | s | file | metadata.ffprobe | — | Total programme duration reported by the container. |
| `container.format` | Container Format | string | — | file | metadata.ffprobe | — | Container format normalized to a single token (mov, mp4, mkv, wav). |
| `container.overall_bitrate` | Overall Bitrate | integer | bit/s | file | metadata.ffprobe | — | Total bitrate across all streams. |
| `container.start_time` | Container Start Time | float | s | file | metadata.ffprobe | — | Start time offset of the container timeline. |
| `container.timecode_present` | Timecode Track Present | boolean | — | file | metadata.ffprobe | — | Whether the container carries a timecode track. |
| `container.timecode_start` | Start Timecode | string | — | file | metadata.ffprobe | — | First timecode value, as SMPTE HH:MM:SS:FF. |
| `container.truncated` | Container Truncated | boolean | — | file | *planned* | — | Whether the file appears cut short relative to its declared duration. |

### Container caveats

- `container.overall_bitrate` — Only emitted when the container declares an overall bit rate; some formats omit it.
- `container.timecode_present` — Found via the container or stream 'timecode' tag (MOV tmcd track, MXF material package). Embedded VITC/ancillary timecode without a tag is not detected.
- `container.timecode_start` — Only emitted when a 'timecode' tag exists; drop-frame timecodes keep their semicolon separator as reported.

## Video

| Parameter | Name | Type | Unit | Scope | Detector | Accuracy | Description |
|---|---|---|---|---|---|---|---|
| `video.bit_depth` | Video Bit Depth | integer | bit | stream | metadata.ffprobe | — | Bits per colour component. |
| `video.bitrate` | Video Bitrate | integer | bit/s | stream | metadata.ffprobe | — | Video stream bitrate. |
| `video.black_frame_count` | Black Frame Event Count | integer | — | stream | video.incidents.ffmpeg | — | Number of black spans detected in the stream. |
| `video.black_frame_event` | Black Frame Event | float | s | stream, timed | video.incidents.ffmpeg | — | Duration of one detected black span. Emitted once per span, with start and end seconds. |
| `video.codec` | Video Codec | string | — | stream | metadata.ffprobe | — | Video codec name per stream (prores, h264, ...). |
| `video.color_primaries` | Colour Primaries | string | — | stream | metadata.ffprobe | — | Colour primaries (bt709, bt2020, ...). |
| `video.color_space` | Colour Space | string | — | stream | metadata.ffprobe | — | Matrix coefficients / colour space. |
| `video.corrupt_frame_event` | Corrupt Frame Event | float | s | file, timed | *planned* | — | A frame with decode errors or statistical outliers. Backlog #36: Vidchecker flagged such a frame on the RHOA M&E master that we localized only indirectly, via a one-frame gap between black spans. |
| `video.display_aspect_ratio` | Display Aspect Ratio | string | — | stream | metadata.ffprobe | — | Display aspect ratio as declared by the stream (e.g. '16:9'). |
| `video.field_order` | Field Order | string | — | stream | metadata.ffprobe | — | Field order: 'progressive', 'tff' or 'bff'. |
| `video.frame_rate` | Frame Rate | float | fps | stream | metadata.ffprobe | — | Average frame rate, normalized to three decimal places. |
| `video.frame_rate_mode` | Frame Rate Mode | string | — | file | *planned* | — | Constant or variable frame rate. |
| `video.freeze_frame_count` | Freeze Frame Event Count | integer | — | stream | video.incidents.ffmpeg | — | Number of frozen spans detected in the stream. |
| `video.freeze_frame_event` | Freeze Frame Event | float | s | stream, timed | video.incidents.ffmpeg | — | Duration of one detected frozen span. Emitted once per span, with start and end seconds. |
| `video.hdr_metadata_present` | HDR Metadata Present | boolean | — | file | *planned* | — | Whether HDR static or dynamic metadata is present. |
| `video.height` | Video Height | integer | px | stream | metadata.ffprobe | — | Coded frame height. |
| `video.letterbox_detected` | Letterbox Detected | boolean | — | file | *planned* | — | Whether the active picture is pillarboxed or letterboxed. |
| `video.level` | Video Level | string | — | stream | metadata.ffprobe | — | Codec level as reported by ffprobe, stringified. |
| `video.luma_avg` | Luma Average | float | — | stream | video.incidents.ffmpeg | — | Mean Y value across the stream (signalstats). |
| `video.luma_max` | Luma Maximum | float | — | stream | video.incidents.ffmpeg | — | Maximum Y value observed across the stream (signalstats). |
| `video.luma_min` | Luma Minimum | float | — | stream | video.incidents.ffmpeg | — | Minimum Y value observed across the stream (signalstats). |
| `video.pixel_format` | Pixel Format | string | — | stream | metadata.ffprobe | — | Pixel format name (yuv422p10le, yuv420p, ...). |
| `video.profile` | Video Profile | string | — | stream | metadata.ffprobe | — | Codec profile as reported by ffprobe (e.g. 'HQ', 'High 4:2:2 Intra'). |
| `video.sample_aspect_ratio` | Sample Aspect Ratio | string | — | stream | metadata.ffprobe | — | Pixel aspect ratio as declared by the stream (e.g. '1:1'). |
| `video.scan_type` | Scan Type | string | — | stream | metadata.ffprobe | — | 'progressive' or 'interlaced', derived from the declared field order. |
| `video.signal_range_event` | Signal Range Event | float | s | file, timed | *planned* | — | Span where luma or chroma exceeds the legal broadcast range. |
| `video.stream_count` | Video Stream Count | integer | — | file | metadata.ffprobe | — | Number of video streams in the file. |
| `video.transfer_characteristics` | Transfer Characteristics | string | — | stream | metadata.ffprobe | — | Transfer function (bt709, pq, hlg, ...). |
| `video.width` | Video Width | integer | px | stream | metadata.ffprobe | — | Coded frame width. |

### Video caveats

- `video.bit_depth` — From bits_per_raw_sample when ffprobe reports it, else derived from the pixel-format token (yuv422p10le -> 10, plain 'p' suffix -> 8); streams reporting neither emit no measurement.
- `video.bitrate` — Only emitted when the stream declares a bit rate; many MXF/MOV essence streams do not.
- `video.black_frame_event` — ffmpeg blackdetect thresholds (0.5 s minimum, 0.10 pixel threshold) are detector constants, not preset-configurable. Spans shorter than the minimum are not reported.
- `video.color_primaries` — Declared metadata only; unflagged streams emit no measurement.
- `video.color_space` — Declared metadata only; unflagged streams emit no measurement.
- `video.display_aspect_ratio` — Declared metadata only; not measured from the picture.
- `video.field_order` — Normalized from ffprobe's flags (tt/tb -> tff by coded order, bb/bt -> bff); the raw value is preserved in measurement metadata. Streams with unknown field order emit no measurement.
- `video.frame_rate` — Rational rates (24000/1001) are rounded for comparison; use the approximately_equals operator with a tolerance rather than equals.
- `video.freeze_frame_event` — ffmpeg freezedetect thresholds (-60 dB noise, 1.0 s minimum) are detector constants. Legitimate static content (title cards, letterboxed slates) registers as frozen.
- `video.level` — ffprobe reports numeric level codes: H.264 4.1 is '41'; MPEG-2 uses enum values ('4' High, '6' High-1440, '8' Main, '10' Low).
- `video.profile` — Profile strings are ffprobe's names, which differ from vendor spec sheets (ProRes 422 HQ reports as 'HQ').
- `video.sample_aspect_ratio` — Declared metadata only; not measured from the picture.
- `video.scan_type` — Derived from stream flags, not baseband cadence analysis: progressive-segmented or telecined material reports its flagged value.
- `video.transfer_characteristics` — Declared metadata only; unflagged streams emit no measurement.

## Audio

| Parameter | Name | Type | Unit | Scope | Detector | Accuracy | Description |
|---|---|---|---|---|---|---|---|
| `audio.bit_depth` | Audio Bit Depth | integer | bit | file | *planned* | — | Bits per sample for PCM streams. |
| `audio.channel_count` | Channel Count | integer | — | stream | metadata.ffprobe | — | Number of channels in the stream. |
| `audio.channel_layout` | Channel Layout | string | — | stream | metadata.ffprobe | — | Channel layout descriptor (mono, stereo, 5.1). |
| `audio.clipping_event` | Clipping Event | float | s | file, timed | *planned* | — | A timestamped clipping occurrence. Not implemented: clipping is currently surfaced as the whole-stream indicators peak_level, flat_factor and peak_count rather than located in time. |
| `audio.codec` | Audio Codec | string | — | stream | metadata.ffprobe | — | Audio codec name per stream (pcm_s24le, aac, ...). |
| `audio.dc_offset` | DC Offset | float | — | stream | audio.analysis.ffmpeg | — | Mean sample offset from zero (astats); should be near zero. |
| `audio.duplicate_channel_risk` | Duplicate Channel Risk | boolean | — | stream | audio.dualmono.ffmpeg | — | Whether two channels of the stream carry the same signal, indicating a dual-mono error. Flagged pairs are listed in measurement metadata. |
| `audio.duration` | Audio Duration | float | s | stream | metadata.ffprobe | — | Duration of the audio stream. |
| `audio.flat_factor` | Flat Factor | float | — | stream | audio.analysis.ffmpeg | — | astats flat factor: consecutive samples pinned at peak. Greater than zero indicates clipping. |
| `audio.group_integrated_loudness` | Group Integrated Loudness | float | LUFS | file | *planned* | — | Integrated loudness of a preset-declared channel group measured jointly with ITU-1770 weighting. This, not the per-track value, is what client filename targets such as '-27LU' refer to on multi-mono masters (backlog #35). |
| `audio.group_loudness_range` | Group Loudness Range | float | LU | file | *planned* | — | Loudness range of a preset-declared channel group (backlog #35). |
| `audio.group_true_peak` | Group True Peak | float | dBTP | file | *planned* | — | Maximum true peak across a preset-declared channel group (backlog #35). |
| `audio.head_silence_duration` | Head Silence | float | s | stream | audio.analysis.ffmpeg | — | Length of the silent span at the start of the stream. |
| `audio.integrated_loudness` | Integrated Loudness | float | LUFS | stream | audio.analysis.ffmpeg | validated | EBU R128 programme loudness over the whole stream. |
| `audio.internal_silence_count` | Internal Silence Count | integer | — | stream | audio.analysis.ffmpeg | — | Number of internal silent spans detected. |
| `audio.internal_silence_event` | Internal Silence Event | float | s | stream, timed | audio.analysis.ffmpeg | — | Duration of one silent span inside the programme. Emitted once per span, with start and end seconds. |
| `audio.language` | Audio Language | string | — | stream | metadata.ffprobe | — | Stream language tag, normalized to ISO 639-1 where possible so presets may reference either form (backlog #33). |
| `audio.loudness_range` | Loudness Range | float | LU | stream | audio.analysis.ffmpeg | validated | EBU R128 loudness range (LRA). |
| `audio.low_rms_event` | Low RMS Event | float | s | stream, timed | audio.analysis.ffmpeg | cross-checked | Duration of one span whose windowed RMS stays at or below -90 dB. Approximates Vidchecker's Min Level test (backlog #34). |
| `audio.low_rms_event_count` | Low RMS Event Count | integer | — | stream | audio.analysis.ffmpeg | — | Number of low-RMS spans detected after merging adjacent windows. |
| `audio.max_momentary_loudness` | Max Momentary Loudness | float | LUFS | stream | audio.analysis.ffmpeg | validated | Highest 400 ms momentary loudness value. |
| `audio.max_short_term_loudness` | Max Short-Term Loudness | float | LUFS | stream | audio.analysis.ffmpeg | validated | Highest 3-second short-term loudness value. |
| `audio.peak_count` | Peak Count | integer | — | stream | audio.analysis.ffmpeg | — | Number of samples at peak level (astats). |
| `audio.peak_level` | Peak Level | float | dBFS | stream | audio.analysis.ffmpeg | — | Sample peak level from astats, a hard-clipping indicator. |
| `audio.phase_correlation` | Phase Correlation | float | — | file | *planned* | — | Inter-channel phase correlation, for detecting out-of-phase pairs. |
| `audio.sample_rate` | Sample Rate | integer | Hz | stream | metadata.ffprobe | — | Sampling frequency per stream. |
| `audio.stream_count` | Audio Stream Count | integer | — | file | metadata.ffprobe | — | Number of audio streams (tracks) in the file. |
| `audio.tail_silence_duration` | Tail Silence | float | s | stream | audio.analysis.ffmpeg | cross-checked | Length of the silent span at the end of the stream. |
| `audio.true_peak` | True Peak | float | dBTP | stream | audio.analysis.ffmpeg | validated | EBU R128 maximum true peak level. |
| `audio.video_duration_delta` | Audio/Video Duration Delta | float | s | stream | metadata.ffprobe | — | Audio stream duration minus video stream duration. |

### Audio caveats

- `audio.duplicate_channel_risk` — Whole-stream measure: a pair is a duplicate when its difference signal stays at or below -80 dB RMS AND at least one channel carries content above -60 dB RMS (silent pairs are not flagged); brief divergence anywhere in the programme clears the flag, unlike Vidchecker's windowed variant. Streams wider than 8 channels compare only their first 8. Mono streams report false.
- `audio.head_silence_duration` — Silence is defined as below -60 dB for at least 0.5 s.
- `audio.integrated_loudness` — Measured per track. On multi-mono masters a channel-group target (e.g. 5.1 measured jointly with ITU-1770 weighting) is NOT what this reports — see backlog #35 and audio.group_integrated_loudness.
- `audio.language` — Not emitted when the stream carries no language metadata.
- `audio.low_rms_event` — 5-second RMS windows; -90 dB threshold is a detector constant.
- `audio.max_momentary_loudness` — Derived from 100 ms ebur128 log lines, which undersamples very short bursts by up to 0.5 LU (EBU 3341 case 13). Spec-grade metering is outstanding work in docs/VALIDATION.md.
- `audio.tail_silence_duration` — Converged with Vidchecker's Min Level within 0.2 s on parity point 1 despite different definitions (-60 dB silencedetect vs -95 dB windowed RMS).

## Subtitle and caption

| Parameter | Name | Type | Unit | Scope | Detector | Accuracy | Description |
|---|---|---|---|---|---|---|---|
| `subtitle.characters_per_line` | Characters Per Line | integer | — | file | *planned* | — | Maximum characters on any subtitle line. |
| `subtitle.characters_per_second` | Characters Per Second | float | char/s | file | *planned* | — | Reading-speed measure per cue. |
| `subtitle.codec` | Subtitle Codec | string | — | file | *planned* | — | Subtitle codec or format per stream. |
| `subtitle.cue_count` | Subtitle Cue Count | integer | — | file | *planned* | — | Number of subtitle cues. |
| `subtitle.default_flag` | Subtitle Default Flag | boolean | — | file | *planned* | — | Whether the stream is marked default. |
| `subtitle.encoding_error_event` | Encoding Error | string | — | file, timed | *planned* | — | A character that failed to decode in the declared encoding. |
| `subtitle.forced_flag` | Subtitle Forced Flag | boolean | — | file | *planned* | — | Whether the stream is marked forced. |
| `subtitle.invalid_markup_event` | Invalid Markup | string | — | file, timed | *planned* | — | A cue containing malformed markup. |
| `subtitle.language` | Subtitle Language | string | — | file | *planned* | — | Subtitle stream language tag. |
| `subtitle.line_count` | Subtitle Line Count | integer | — | file | *planned* | — | Maximum simultaneous lines in any cue. |
| `subtitle.out_of_bounds_event` | Out-of-Bounds Cue | float | s | file, timed | *planned* | — | A cue timed outside the programme duration. |
| `subtitle.overlap_event` | Subtitle Overlap Event | float | s | file, timed | *planned* | — | Two cues displayed at the same time. |
| `subtitle.stream_count` | Subtitle Stream Count | integer | — | file | metadata.ffprobe | — | Number of subtitle streams in the file. |
| `subtitle.zero_duration_event` | Zero-Duration Cue | float | s | file, timed | *planned* | — | A cue whose out-time equals its in-time. |

## Deepdub workflow

| Parameter | Name | Type | Unit | Scope | Detector | Accuracy | Description |
|---|---|---|---|---|---|---|---|
| `deepdub.dialogue_outside_segment_event` | Dialogue Outside Segment | float | s | file, timed | *planned* | — | Speech detected outside any defined segment. |
| `deepdub.expected_episode_duration` | Expected Episode Duration | float | s | file | *planned* | — | Duration the Composer project expects for this episode. |
| `deepdub.export_duration_delta` | Export Duration Delta | float | s | file | *planned* | — | Difference between the exported media and the Composer timeline. |
| `deepdub.export_version_mismatch` | Export Version Mismatch | boolean | — | file | *planned* | — | The export does not match the Composer version it claims. |
| `deepdub.missing_generated_segments` | Missing Generated Segments | integer | — | file | *planned* | — | Segments with no generated dub audio. |
| `deepdub.missing_mix_segments` | Missing Mix Segments | integer | — | file | *planned* | — | Segments absent from the final mix. |
| `deepdub.required_language_missing` | Required Language Missing | boolean | — | file | *planned* | — | A language the delivery requires is absent. |
| `deepdub.required_stem_missing` | Required Stem Missing | boolean | — | file | *planned* | — | A required stem (dialogue, M&E, effects) is absent. |
| `deepdub.segment_overlap_event` | Segment Overlap | float | s | file, timed | *planned* | — | Two segments overlapping in time. |
| `deepdub.unresolved_qc_markers` | Unresolved QC Markers | integer | — | file | *planned* | — | Composer QC markers still open at export time. |
| `deepdub.workspace_metadata_mismatch` | Workspace Metadata Mismatch | boolean | — | file | *planned* | — | Asset metadata disagrees with the Composer workspace record. |
