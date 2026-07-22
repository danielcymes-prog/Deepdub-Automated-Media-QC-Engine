# Deepdub Automated Media QC
## Claude Code Project Handoff and Build Specification

**Project status:** Greenfield internal tooling project  
**Primary goal:** Build a local-first automated media quality-control engine that can eventually become an integrated Composer feature.  
**Primary priority:** Generate clear, reliable, reviewable QC reports.  
**Initial replacement target:** The subset of Vidchecker capabilities that matter most to Deepdub delivery workflows.  
**Implementation principle:** Deterministic media analysis first; AI-assisted interpretation second.

---

# 1. Mission

Build an internal Deepdub media QC system that:

1. Accepts a final media deliverable.
2. Loads the correct client-specific QC preset.
3. Extracts technical media measurements.
4. Runs deterministic QC checks.
5. Produces normalized findings.
6. Assigns `PASS`, `WARNING`, `FAIL`, or `ERROR` statuses.
7. Generates polished JSON, HTML, and PDF reports.
8. Preserves raw detector output and evidence.
9. Can later run as a backend service invoked from Composer.
10. Can later allow the Deepdub AI Assistant to explain reports, recommend remediation, and create Composer QC markers.

The first version must run locally from the command line. It must not depend on Composer infrastructure.

---

# 2. Core Product Principle

Do not build this as an LLM that "watches" a media file and decides whether it is acceptable.

Use the following separation:

```text
Media detector produces measurements
                ↓
Rule engine evaluates measurements
                ↓
Report engine renders findings
                ↓
AI layer explains findings
```

The AI layer must never invent, override, or silently alter raw detector measurements.

---

# 3. Initial Scope

## 3.1 MVP scope

The first production-quality local MVP must support:

- One media file per QC job.
- Local filesystem input.
- YAML client presets.
- FFprobe metadata extraction.
- FFmpeg-based audio and video checks.
- Deterministic rule evaluation.
- Versioned result schemas.
- JSON report generation.
- HTML report generation.
- PDF report generation.
- Machine-readable exit codes.
- Evidence files for timestamped failures.
- Structured logs.
- Automated tests.
- Docker-based execution.

## 3.2 Not required for MVP

Do not initially implement:

- Composer UI.
- Cloud deployment.
- Distributed workers.
- User authentication.
- Automatic remediation.
- Full Vidchecker feature parity.
- Subjective audio quality scoring.
- Fully automated translation approval.
- Fully automated pronunciation approval.
- Automatic client delivery approval.
- Multi-tenant permissions.

---

# 4. Primary User Workflows

## 4.1 Local CLI workflow

```bash
deepdub-qc analyze \
  --input /path/to/final_delivery.mov \
  --preset presets/alphorn/workout_v1.yaml \
  --output reports/job_001
```

Expected output:

```text
reports/job_001/
├── report.json
├── report.html
├── report.pdf
├── evidence/
│   ├── thumbnails/
│   ├── waveforms/
│   └── clips/
├── raw/
│   ├── ffprobe.json
│   ├── mediainfo.json
│   ├── loudness.json
│   ├── blackdetect.log
│   ├── freezedetect.log
│   └── silencedetect.log
└── logs/
    └── qc.log
```

## 4.2 Report review workflow

A reviewer must be able to determine:

- What file was analyzed?
- Which preset and preset version were used?
- Did the file pass overall?
- Which checks failed?
- What was expected?
- What was measured?
- Where did the problem occur?
- How severe is the problem?
- Is evidence available?
- What action is recommended?
- Which detector version generated the finding?

## 4.3 Future Composer workflow

```text
User clicks Run QC in Composer
        ↓
Composer creates QC job
        ↓
QC service selects preset
        ↓
Worker analyzes exported media
        ↓
Structured report is stored
        ↓
Composer displays results
        ↓
User seeks directly to issue timestamp
        ↓
User optionally creates QC marker
```

---

# 5. Recommended Technology Stack

## 5.1 Local MVP

- Python 3.12 or 3.13
- FFmpeg
- FFprobe
- Pydantic v2
- Typer
- Jinja2
- Playwright or WeasyPrint for PDF rendering
- SQLite
- SQLAlchemy 2.x
- PyYAML or `ruamel.yaml`
- pytest
- Ruff
- mypy
- Docker
- GitHub Actions

## 5.2 Optional supporting tools

- MediaInfo for metadata cross-checking
- OpenCV for custom visual detectors
- `pysubs2` for subtitle parsing
- `libvmaf` for future reference-based video comparison
- Bento4 or GPAC for future MP4 structure analysis

## 5.3 Future service stack

- FastAPI
- PostgreSQL
- S3-compatible object storage
- Existing Deepdub queue and worker infrastructure where possible
- Existing Deepdub authentication and authorization infrastructure
- Existing Composer frontend stack

Do not introduce Celery, Redis, RabbitMQ, or a new orchestration system without first checking the current Deepdub backend architecture.

---

# 6. Repository Structure

Create the project using this structure:

```text
deepdub-media-qc/
├── README.md
├── CLAUDE.md
├── pyproject.toml
├── uv.lock
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── docs/
│   ├── architecture.md
│   ├── parameter-catalogue.md
│   ├── detector-development.md
│   ├── preset-authoring.md
│   ├── report-contract.md
│   ├── testing-strategy.md
│   ├── composer-integration.md
│   └── adr/
│       ├── 0001-deterministic-core.md
│       ├── 0002-json-source-of-truth.md
│       └── 0003-versioned-presets.md
├── presets/
│   ├── schema/
│   │   └── qc-preset.schema.json
│   ├── examples/
│   │   └── generic_broadcast_v1.yaml
│   └── clients/
│       └── alphorn/
│           └── workout_v1.yaml
├── schemas/
│   ├── qc-result.schema.json
│   ├── qc-finding.schema.json
│   ├── qc-measurement.schema.json
│   └── qc-job.schema.json
├── src/
│   └── deepdub_qc/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── constants.py
│       ├── exceptions.py
│       ├── logging.py
│       ├── models/
│       │   ├── enums.py
│       │   ├── job.py
│       │   ├── asset.py
│       │   ├── preset.py
│       │   ├── rule.py
│       │   ├── measurement.py
│       │   ├── finding.py
│       │   └── report.py
│       ├── detectors/
│       │   ├── base.py
│       │   ├── registry.py
│       │   ├── metadata/
│       │   │   ├── ffprobe_detector.py
│       │   │   └── mediainfo_detector.py
│       │   ├── audio/
│       │   │   ├── loudness.py
│       │   │   ├── silence.py
│       │   │   ├── clipping.py
│       │   │   ├── stream_layout.py
│       │   │   └── duration_sync.py
│       │   ├── video/
│       │   │   ├── black_frames.py
│       │   │   ├── freeze_frames.py
│       │   │   ├── signal_stats.py
│       │   │   ├── resolution.py
│       │   │   └── frame_rate.py
│       │   ├── subtitles/
│       │   │   ├── presence.py
│       │   │   ├── timing.py
│       │   │   └── formatting.py
│       │   └── deepdub/
│       │       ├── composer_duration.py
│       │       ├── segment_coverage.py
│       │       ├── unresolved_markers.py
│       │       └── export_version.py
│       ├── rules/
│       │   ├── engine.py
│       │   ├── evaluators.py
│       │   ├── registry.py
│       │   └── validators.py
│       ├── presets/
│       │   ├── loader.py
│       │   ├── resolver.py
│       │   ├── validator.py
│       │   └── versioning.py
│       ├── reports/
│       │   ├── builder.py
│       │   ├── json_renderer.py
│       │   ├── html_renderer.py
│       │   ├── pdf_renderer.py
│       │   ├── summary.py
│       │   └── templates/
│       │       ├── report.html.j2
│       │       └── report.css
│       ├── evidence/
│       │   ├── thumbnails.py
│       │   ├── waveforms.py
│       │   └── paths.py
│       ├── storage/
│       │   ├── database.py
│       │   ├── repositories.py
│       │   └── migrations/
│       ├── orchestration/
│       │   ├── pipeline.py
│       │   ├── job_runner.py
│       │   └── context.py
│       └── utils/
│           ├── subprocess.py
│           ├── timecode.py
│           ├── hashing.py
│           └── files.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   ├── fixtures/
│   │   ├── media/
│   │   ├── presets/
│   │   ├── expected/
│   │   └── raw_detector_output/
│   └── golden/
├── scripts/
│   ├── generate_test_media.py
│   ├── validate_presets.py
│   ├── compare_vidchecker.py
│   └── build_docs.py
└── .github/
    └── workflows/
        ├── ci.yml
        └── docker.yml
```

---

# 7. Domain Model

Keep these concepts separate.

## 7.1 Measurement

An objective value produced by a detector.

Examples:

- Integrated loudness is `-19.7 LUFS`.
- Width is `1920`.
- Frame rate is `23.976`.
- Audio stream count is `4`.
- Black frame detected from `00:04:12.000` to `00:04:15.400`.

## 7.2 Rule

A preset-defined expectation.

Examples:

- Integrated loudness must be between `-24` and `-22 LUFS`.
- Width must equal `1920`.
- Audio stream count must equal `4`.

## 7.3 Finding

The result of evaluating a measurement against a rule.

Examples:

- `FAIL`: integrated loudness too high.
- `PASS`: resolution is correct.
- `WARNING`: head silence exceeds preferred duration but does not block delivery.

## 7.4 Evidence

A supporting artifact tied to a finding.

Examples:

- Thumbnail at a black-frame timestamp.
- Waveform around a clipping event.
- Short audio clip around a dropout.
- Raw FFmpeg output.

## 7.5 Report

A versioned presentation of job metadata, measurements, findings, evidence, and summary.

---

# 8. Required Enums

```python
from enum import StrEnum


class QCStatus(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class Category(StrEnum):
    FILE = "file"
    CONTAINER = "container"
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"
    METADATA = "metadata"
    DEEPDUB = "deepdub"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

---

# 9. QC Measurement Schema

Implement as Pydantic models and publish a JSON Schema.

```json
{
  "schema_version": "1.0.0",
  "measurement_id": "uuid",
  "job_id": "uuid",
  "detector_id": "audio.loudness.ebur128",
  "detector_version": "1.0.0",
  "parameter_id": "audio.integrated_loudness",
  "category": "audio",
  "value": -19.7,
  "unit": "LUFS",
  "stream_index": 1,
  "start_seconds": null,
  "end_seconds": null,
  "start_timecode": null,
  "end_timecode": null,
  "confidence": 1.0,
  "metadata": {},
  "raw_artifact_path": "raw/loudness.json",
  "created_at": "2026-07-22T10:00:00Z"
}
```

Requirements:

- `value` must support string, integer, float, boolean, list, and object values.
- Timestamped measurements must support start and end seconds.
- Stream-specific measurements must include stream index.
- Every measurement must identify detector and detector version.
- Raw output path should be optional.

---

# 10. QC Finding Schema

```json
{
  "schema_version": "1.0.0",
  "finding_id": "uuid",
  "job_id": "uuid",
  "check_id": "audio.integrated_loudness",
  "category": "audio",
  "display_name": "Integrated Loudness",
  "status": "FAIL",
  "severity": "error",
  "expected": {
    "min": -24.0,
    "max": -22.0,
    "unit": "LUFS"
  },
  "actual": {
    "value": -19.7,
    "unit": "LUFS"
  },
  "message": "Integrated loudness exceeds the permitted range.",
  "start_seconds": null,
  "end_seconds": null,
  "start_timecode": null,
  "end_timecode": null,
  "stream_index": 1,
  "measurement_ids": ["uuid"],
  "evidence": [],
  "suggested_action": "Normalize the final mix to the client target.",
  "blocking": true,
  "rule_version": "1.0.0",
  "created_at": "2026-07-22T10:00:01Z"
}
```

Requirements:

- Findings must be reproducible from measurement plus rule.
- Findings must not contain fabricated measurements.
- Blocking status must come from the preset/rule.
- Human-readable message templates should be deterministic by default.
- AI-generated explanations must be stored separately from canonical findings.

---

# 11. QC Job Result Schema

```json
{
  "schema_version": "1.0.0",
  "job": {
    "job_id": "uuid",
    "status": "completed",
    "started_at": "2026-07-22T10:00:00Z",
    "completed_at": "2026-07-22T10:04:12Z",
    "duration_seconds": 252.0,
    "tool_version": "0.1.0"
  },
  "asset": {
    "input_path": "/media/final_delivery.mov",
    "filename": "final_delivery.mov",
    "file_size_bytes": 123456789,
    "sha256": "...",
    "duration_seconds": 1452.2
  },
  "preset": {
    "preset_id": "alphorn_workout_delivery",
    "preset_version": "1.0.0",
    "client": "alphorn",
    "content_type": "workout"
  },
  "summary": {
    "overall_status": "FAIL",
    "total_checks": 24,
    "passed": 20,
    "warnings": 2,
    "failed": 2,
    "errors": 0,
    "blocking_failures": 2
  },
  "media_summary": {},
  "measurements": [],
  "findings": [],
  "artifacts": {
    "html_report": "report.html",
    "pdf_report": "report.pdf",
    "evidence_directory": "evidence/",
    "raw_directory": "raw/"
  }
}
```

---

# 12. Preset Schema

Client presets must be data, not application logic.

## 12.1 Example preset

```yaml
schema_version: 1.0.0

preset:
  id: alphorn_workout_delivery
  version: 1.0.0
  client: alphorn
  content_type: workout
  title: Alphorn Workout Final Delivery
  description: Final dubbed workout delivery preset.
  owner: media-operations
  status: draft
  effective_date: 2026-07-22
  supersedes: null

defaults:
  blocking: true
  severity: error

rules:
  - check_id: container.format
    enabled: true
    operator: in
    expected:
      values: [mov]
    severity: error
    blocking: true

  - check_id: video.codec
    enabled: true
    operator: in
    expected:
      values: [prores]
    severity: error
    blocking: true

  - check_id: video.width
    enabled: true
    operator: equals
    expected:
      value: 1920
    severity: error
    blocking: true

  - check_id: video.height
    enabled: true
    operator: equals
    expected:
      value: 1080
    severity: error
    blocking: true

  - check_id: video.frame_rate
    enabled: true
    operator: approximately_equals
    expected:
      value: 23.976
      tolerance: 0.001
    severity: error
    blocking: true

  - check_id: audio.stream_count
    enabled: true
    operator: equals
    expected:
      value: 4
    severity: critical
    blocking: true

  - check_id: audio.sample_rate
    enabled: true
    operator: equals
    expected:
      value: 48000
      unit: Hz
    severity: error
    blocking: true

  - check_id: audio.integrated_loudness
    enabled: true
    operator: between
    expected:
      min: -24.0
      max: -22.0
      unit: LUFS
    severity: error
    blocking: true

  - check_id: audio.true_peak
    enabled: true
    operator: less_than_or_equal
    expected:
      value: -2.0
      unit: dBTP
    severity: error
    blocking: true

  - check_id: filename.pattern
    enabled: true
    operator: regex
    expected:
      pattern: "^[A-Za-z0-9_\\-]+\\.mov$"
    severity: warning
    blocking: false

report:
  include_passed_checks: true
  include_raw_measurements: false
  include_evidence: true
  include_suggested_actions: true
```

## 12.2 Preset requirements

Every preset must include:

- Preset ID
- Semantic version
- Client
- Content type
- Title
- Description
- Owner
- Status: `draft`, `approved`, `deprecated`
- Effective date
- Rules
- Severity
- Blocking behavior
- Report configuration
- Change history
- Test fixtures

## 12.3 Versioning rules

Use semantic versioning:

- Patch: wording, metadata, or non-behavioral fixes.
- Minor: new non-breaking rule or optional field.
- Major: changed threshold, changed blocking behavior, removed rule, or incompatible schema change.

Never modify an approved preset version in place. Create a new version.

---

# 13. Rule Engine

Implement a generic rule engine.

Required operators:

- `equals`
- `not_equals`
- `in`
- `not_in`
- `greater_than`
- `greater_than_or_equal`
- `less_than`
- `less_than_or_equal`
- `between`
- `approximately_equals`
- `contains`
- `contains_all`
- `regex`
- `exists`
- `not_exists`
- `count_equals`
- `count_at_least`
- `count_at_most`

Rule evaluation must be:

- Deterministic
- Pure where possible
- Unit tested
- Independent of report rendering
- Independent of AI APIs
- Able to return `SKIPPED` when required measurement is unavailable
- Able to return `ERROR` when detector execution fails

Do not hardcode client names in the rule engine.

Bad:

```python
if client == "alphorn":
    required_streams = 4
```

Correct:

```python
required_streams = preset.rules["audio.stream_count"].expected.value
```

---

# 14. Detector Interface

All detectors must implement a common interface.

```python
from abc import ABC, abstractmethod


class Detector(ABC):
    detector_id: str
    detector_version: str
    parameters: tuple[str, ...]

    @abstractmethod
    def is_applicable(self, context: "QCContext") -> bool:
        ...

    @abstractmethod
    def run(self, context: "QCContext") -> list["Measurement"]:
        ...
```

Detector requirements:

- Never evaluate client pass/fail thresholds.
- Produce normalized measurements only.
- Preserve raw command output.
- Use safe subprocess execution.
- Set explicit timeouts.
- Capture exit code, stdout, and stderr.
- Raise typed exceptions.
- Be independently testable.
- Declare detector version.
- Avoid shell interpolation.
- Never use `shell=True` for user-controlled paths.

---

# 15. Initial Parameter Catalogue

Create `docs/parameter-catalogue.md` and a machine-readable registry.

Each parameter must define:

- Parameter ID
- Display name
- Category
- Description
- Data type
- Unit
- Detector
- Timestamp support
- Stream support
- MVP status
- Validation status
- Known limitations

## 15.1 File and container

- `file.readable`
- `file.extension`
- `file.size_bytes`
- `file.sha256`
- `filename.pattern`
- `container.format`
- `container.duration`
- `container.overall_bitrate`
- `container.start_time`
- `container.timecode_present`
- `container.timecode_start`
- `container.truncated`

## 15.2 Video

- `video.stream_count`
- `video.codec`
- `video.profile`
- `video.level`
- `video.width`
- `video.height`
- `video.frame_rate`
- `video.frame_rate_mode`
- `video.pixel_format`
- `video.bit_depth`
- `video.display_aspect_ratio`
- `video.sample_aspect_ratio`
- `video.scan_type`
- `video.field_order`
- `video.color_primaries`
- `video.transfer_characteristics`
- `video.color_space`
- `video.hdr_metadata_present`
- `video.bitrate`
- `video.black_frame_event`
- `video.freeze_frame_event`
- `video.signal_range_event`
- `video.letterbox_detected`
- `video.corrupt_frame_event`

## 15.3 Audio

- `audio.stream_count`
- `audio.codec`
- `audio.sample_rate`
- `audio.bit_depth`
- `audio.channel_count`
- `audio.channel_layout`
- `audio.language`
- `audio.integrated_loudness`
- `audio.loudness_range`
- `audio.true_peak`
- `audio.max_momentary_loudness`
- `audio.max_short_term_loudness`
- `audio.head_silence_duration`
- `audio.tail_silence_duration`
- `audio.internal_silence_event`
- `audio.clipping_event`
- `audio.dc_offset`
- `audio.phase_correlation`
- `audio.duration`
- `audio.video_duration_delta`
- `audio.duplicate_channel_risk`

## 15.4 Subtitle and caption

- `subtitle.stream_count`
- `subtitle.codec`
- `subtitle.language`
- `subtitle.default_flag`
- `subtitle.forced_flag`
- `subtitle.cue_count`
- `subtitle.overlap_event`
- `subtitle.zero_duration_event`
- `subtitle.out_of_bounds_event`
- `subtitle.characters_per_second`
- `subtitle.characters_per_line`
- `subtitle.line_count`
- `subtitle.invalid_markup_event`
- `subtitle.encoding_error_event`

## 15.5 Deepdub-specific future parameters

- `deepdub.expected_episode_duration`
- `deepdub.export_duration_delta`
- `deepdub.missing_generated_segments`
- `deepdub.missing_mix_segments`
- `deepdub.unresolved_qc_markers`
- `deepdub.dialogue_outside_segment_event`
- `deepdub.segment_overlap_event`
- `deepdub.required_language_missing`
- `deepdub.required_stem_missing`
- `deepdub.export_version_mismatch`
- `deepdub.workspace_metadata_mismatch`

---

# 16. MVP Checks

Implement these checks first.

## Tier 1: Metadata and structure

1. File readable
2. Container format
3. Duration
4. Video stream count
5. Video codec
6. Resolution
7. Frame rate
8. Pixel format
9. Audio stream count
10. Audio codec
11. Audio sample rate
12. Audio channel count/layout
13. Stream language metadata
14. Subtitle stream presence
15. Filename pattern

## Tier 2: Audio QC

16. Integrated loudness
17. Loudness range
18. True peak
19. Head silence
20. Tail silence
21. Internal silence
22. Duration mismatch
23. Clipping indicators

## Tier 3: Video incidents

24. Black frames
25. Freeze frames
26. Basic signal statistics
27. Letterboxing/pillarboxing heuristic

Complete Tier 1 and report generation before adding Tier 2 or Tier 3.

---

# 17. Report Requirements

The JSON result is the source of truth.

HTML and PDF are renderings of the JSON result.

## 17.1 Report sections

1. Report header
2. Overall status
3. Asset identity
4. Client and preset
5. Summary counts
6. Blocking failures
7. Warnings
8. Media technical specification
9. Timestamped incidents
10. Audio stream map
11. Video stream map
12. Subtitle stream map
13. Passed checks
14. Evidence
15. Suggested remediation
16. Tool, detector, and schema versions
17. Execution metadata

## 17.2 Report quality requirements

- Must be readable by a non-engineer.
- Must clearly separate expected and actual values.
- Must show timecodes for timestamped failures.
- Must show stream index for stream-specific findings.
- Must display blocking versus non-blocking findings.
- Must not hide detector errors.
- Must include preset version.
- Must include tool version.
- Must include media hash.
- Must include generation timestamp.
- Must be printable.
- Must work without JavaScript after generation.

## 17.3 Summary status logic

Recommended logic:

```text
ERROR if job cannot complete or required detector fails
FAIL if any blocking finding has FAIL status
WARNING if no blocking failures and at least one warning exists
PASS if all enabled checks pass or are non-applicable
```

---

# 18. Exit Codes

The CLI must use stable exit codes:

```text
0 = QC completed and overall status PASS
1 = QC completed with WARNING
2 = QC completed with FAIL
3 = QC execution ERROR
4 = Invalid preset or configuration
5 = Invalid input or unreadable media
6 = Internal application error
```

Document exit codes in `README.md`.

---

# 19. Logging and Observability

Use structured JSON logs where possible.

Every log event should include:

- Job ID
- Asset path or asset ID
- Preset ID
- Preset version
- Detector ID
- Stage
- Duration
- Status
- Error type

Never log:

- Secrets
- API tokens
- Signed URLs
- Full environment variables
- Sensitive client metadata beyond what is required

---

# 20. Security Requirements

- Treat input file paths as untrusted.
- Never execute user-provided strings through a shell.
- Use subprocess argument arrays.
- Validate paths.
- Prevent path traversal in report output.
- Sanitize filenames in generated artifacts.
- Set subprocess timeouts.
- Enforce configurable maximum file size.
- Enforce configurable maximum job duration.
- Do not upload media externally.
- AI integration must be disabled by default in the local MVP.
- Do not send media, transcripts, filenames, or client metadata to an external LLM without explicit configuration and approval.

---

# 21. Testing Strategy

## 21.1 Test categories

- Unit tests
- Detector parser tests
- Rule engine tests
- Preset validation tests
- Report contract tests
- CLI integration tests
- Golden-file tests
- Docker smoke tests
- Regression tests

## 21.2 Golden media corpus

Build synthetic or approved test media containing:

- Valid reference file
- Wrong codec
- Wrong resolution
- Wrong frame rate
- Missing audio stream
- Wrong sample rate
- Wrong channel layout
- Excessive loudness
- Excessive true peak
- Head silence
- Tail silence
- Internal silence
- Black frame event
- Freeze frame event
- Missing subtitle stream
- Incorrect language metadata
- Duration mismatch
- Corrupted/truncated media

Each fixture must have an expected result file.

Example:

```yaml
fixture: loud_audio.mov
preset: generic_broadcast_v1.yaml
expected:
  overall_status: FAIL
  findings:
    - check_id: audio.integrated_loudness
      status: FAIL
    - check_id: video.frame_rate
      status: PASS
```

## 21.3 Validation metrics

Track:

- True positives
- False positives
- False negatives
- Detector failures
- Runtime
- CPU use
- Memory use
- Result stability
- Differences compared with Vidchecker
- Human reviewer decision

The goal is not immediate full Vidchecker parity.

The goal is high-confidence parity on the checks that most often block Deepdub deliveries.

---

# 22. Development Phases

## Phase 0: Discovery

Deliverables:

- Collect existing Vidchecker reports.
- Collect client specifications.
- Collect manual QC checklists.
- Collect examples of passing and failing files.
- Build a Vidchecker comparison matrix.
- Identify the top 10 delivery-blocking QC failures.
- Select the first client preset.

Exit criteria:

- One client specification is approved as the MVP target.
- Ten to fifteen initial parameters are agreed.
- Report stakeholders approve the proposed report sections.

## Phase 1: Project foundation

Deliverables:

- Repository scaffold
- Python package
- CLI skeleton
- Configuration management
- Logging
- Pydantic domain models
- JSON schemas
- Preset loader and validator
- CI
- Dockerfile

Exit criteria:

- `deepdub-qc --help` works.
- Sample preset validates.
- Unit tests run in CI.
- Docker image builds.

## Phase 2: Report-first prototype

Deliverables:

- Mock QC result
- JSON renderer
- HTML renderer
- PDF renderer
- Sample report
- Report contract tests

Exit criteria:

- Stakeholders can review a realistic report before detectors are complete.
- JSON, HTML, and PDF contain consistent information.

## Phase 3: Metadata MVP

Deliverables:

- FFprobe detector
- Metadata normalization
- Tier 1 checks
- Rule engine
- End-to-end local CLI

Exit criteria:

- One file can be analyzed against one preset.
- 10 to 15 deterministic checks run.
- Reports are generated.
- Exit code matches result.

## Phase 4: Audio QC

Deliverables:

- Loudness detector
- Silence detector
- Peak/clipping detector
- Audio duration checks
- Evidence generation where useful

Exit criteria:

- Golden audio fixtures produce expected findings.
- Loudness results are reproducible.

## Phase 5: Video incident QC

Deliverables:

- Black frame detector
- Freeze frame detector
- Signal statistics detector
- Thumbnail evidence

Exit criteria:

- Timestamped findings include timecodes and evidence.

## Phase 6: Preset management

Deliverables:

- Multiple client presets
- Versioning rules
- Approval status
- Validation command
- Preset test fixtures

Exit criteria:

- Presets can be added without changing Python code.
- Approved versions are immutable.

## Phase 7: Service extraction

Deliverables:

- FastAPI wrapper
- Job persistence
- Object storage abstraction
- Worker abstraction
- Idempotent job execution

Exit criteria:

- Local CLI and API use the same core pipeline.
- Repeated job requests can be safely deduplicated.

## Phase 8: Composer integration

Deliverables:

- Composer job submission
- Preset resolution
- Progress display
- QC results panel
- Timestamp navigation
- Evidence preview
- Create QC marker action
- Download JSON/PDF

Exit criteria:

- User can run QC and inspect results without leaving Composer.

## Phase 9: AI assistance

Deliverables:

- Explain finding
- Summarize report
- Suggest remediation
- Draft preset from client specification
- Compare report versions
- Create QC markers from selected findings

Exit criteria:

- AI output is clearly separated from canonical findings.
- AI cannot modify raw measurements.
- AI usage is auditable.

---

# 23. Composer Integration Contract

Design the core so it can later support these API operations.

## Create QC job

```http
POST /api/v1/qc/jobs
```

```json
{
  "asset_uri": "s3://bucket/path/final_delivery.mov",
  "preset_id": "alphorn_workout_delivery",
  "preset_version": "1.0.0",
  "workspace_id": "workspace-id",
  "episode_id": "episode-id",
  "requested_by": "user-id"
}
```

## Get QC job

```http
GET /api/v1/qc/jobs/{job_id}
```

## Get report

```http
GET /api/v1/qc/jobs/{job_id}/report
```

## Get evidence

```http
GET /api/v1/qc/jobs/{job_id}/evidence/{evidence_id}
```

## Retry job

```http
POST /api/v1/qc/jobs/{job_id}/retry
```

## Cancel job

```http
POST /api/v1/qc/jobs/{job_id}/cancel
```

Do not implement these endpoints until the local core is stable, but keep the domain model compatible with them.

---

# 24. Future Database Model

Suggested tables:

```text
qc_jobs
qc_assets
qc_presets
qc_preset_versions
qc_rules
qc_measurements
qc_findings
qc_evidence
qc_reports
qc_job_events
```

Important design rule:

Measurements must be stored independently from findings.

This makes it possible to re-evaluate an existing measurement set against a new preset without rerunning expensive detectors.

---

# 25. AI Layer Requirements

The AI layer may:

- Summarize the report.
- Explain technical terminology.
- Explain why a finding failed.
- Suggest remediation.
- Group related findings.
- Draft a client preset from a specification.
- Compare two report versions.
- Create a reviewer-facing executive summary.

The AI layer may not:

- Invent measurements.
- Override findings silently.
- Change preset thresholds without creating a new version.
- Convert ambiguous results into a pass.
- Approve final delivery by itself.
- Hide detector errors.

Store AI content separately:

```json
{
  "ai_summary": {
    "provider": "anthropic",
    "model": "model-name",
    "prompt_version": "1.0.0",
    "generated_at": "...",
    "content": "..."
  }
}
```

---

# 26. Claude Code Operating Instructions

Create a root-level `CLAUDE.md` with these rules.

## Development behavior

- Read this handoff before making architectural changes.
- Work in small, reviewable commits.
- Do not add new dependencies without documenting why.
- Prefer standard library and well-maintained libraries.
- Preserve strict separation between detection, evaluation, and reporting.
- Add or update tests for every behavior change.
- Do not hardcode client-specific behavior.
- Do not silently relax failing tests.
- Do not bypass schema validation.
- Do not remove type hints.
- Keep public functions documented.
- Run formatting, linting, typing, and tests before completing a task.

## Required validation commands

```bash
ruff format --check .
ruff check .
mypy src
pytest
```

## Completion requirements

Before marking a milestone complete, Claude Code must:

1. Run the relevant tests.
2. Report any failing tests.
3. Update documentation.
4. Summarize changed files.
5. List remaining risks.
6. Avoid claiming success for untested behavior.

---

# 27. Initial Backlog

## Epic 1: Foundation

- [ ] Create repository scaffold.
- [ ] Configure `pyproject.toml`.
- [ ] Add Typer CLI.
- [ ] Add structured logging.
- [ ] Add Pydantic models.
- [ ] Publish JSON schemas.
- [ ] Add Dockerfile.
- [ ] Add CI workflow.

## Epic 2: Presets

- [ ] Define preset schema.
- [ ] Build YAML loader.
- [ ] Build schema validation.
- [ ] Build semantic-version validation.
- [ ] Create generic example preset.
- [ ] Create first client preset.
- [ ] Add `deepdub-qc presets validate`.

## Epic 3: Reporting

- [ ] Create mocked QC result.
- [ ] Build JSON report renderer.
- [ ] Build HTML template.
- [ ] Build PDF renderer.
- [ ] Add status summary.
- [ ] Add findings table.
- [ ] Add media summary.
- [ ] Add evidence section.
- [ ] Add contract tests.

## Epic 4: Metadata detection

- [ ] Build safe FFprobe runner.
- [ ] Parse container metadata.
- [ ] Parse video streams.
- [ ] Parse audio streams.
- [ ] Parse subtitle streams.
- [ ] Normalize rational frame rates.
- [ ] Normalize channel layouts.
- [ ] Preserve raw FFprobe output.

## Epic 5: Rule engine

- [ ] Implement operators.
- [ ] Implement rule registry.
- [ ] Implement missing-measurement behavior.
- [ ] Implement status aggregation.
- [ ] Add unit tests for every operator.

## Epic 6: End-to-end CLI

- [ ] Implement `analyze` command.
- [ ] Create job output directory.
- [ ] Run detectors.
- [ ] Evaluate rules.
- [ ] Generate reports.
- [ ] Return stable exit code.
- [ ] Add integration test.

## Epic 7: Audio QC

- [ ] Integrated loudness.
- [ ] Loudness range.
- [ ] True peak.
- [ ] Silence detection.
- [ ] Clipping detection.
- [ ] Duration mismatch.

## Epic 8: Video QC

- [ ] Black frame detection.
- [ ] Freeze frame detection.
- [ ] Signal statistics.
- [ ] Thumbnail evidence.

---

# 28. First Milestone Definition of Done

The first milestone is complete when:

- The repository installs locally.
- The CLI runs.
- One YAML preset validates.
- FFprobe metadata is extracted.
- At least 10 deterministic rules execute.
- A JSON report is generated.
- An HTML report is generated.
- A PDF report is generated.
- The report contains expected and actual values.
- The report clearly identifies blocking failures.
- The CLI returns documented exit codes.
- Unit and integration tests pass.
- Docker execution works.
- The same input and preset produce identical canonical findings.
- Another team member can run the tool using the README.

---

# 29. Non-Functional Requirements

## Reliability

- Detector failures must be visible.
- Partial results must not be presented as a full pass.
- Canonical output must be deterministic.
- Jobs must be traceable by ID.

## Performance

For MVP, record runtime rather than enforce aggressive targets.

Initial measurement targets:

- Metadata checks should complete in seconds.
- Full-file audio/video analysis may run slower than real time initially.
- The architecture must later allow detectors to run in parallel where safe.

## Maintainability

- Presets are data-driven.
- Detectors are independently replaceable.
- Rules are generic.
- Reports consume normalized schemas.
- Core logic is not coupled to CLI or API.

## Auditability

Every result must identify:

- Input hash
- Preset version
- Tool version
- Detector versions
- Schema version
- Execution timestamp
- Raw artifacts

---

# 30. Decisions That Require Human Approval

Claude Code must not decide these independently:

- The first client preset.
- Final loudness thresholds.
- Required channel mappings.
- Blocking versus warning severity.
- Whether files may be sent to an external AI provider.
- Composer authentication architecture.
- Production queue technology.
- Production storage bucket layout.
- Data-retention policy.
- Whether reports contain client-identifying information.
- Final UI design.

Use visible placeholders or configuration defaults until approved.

---

# 31. Recommended First Claude Code Prompt

Use the following prompt after placing this document in the project root:

```text
Read DEEPDUB_QC_CLAUDE_CODE_HANDOFF.md in full.

Create the Phase 1 project foundation for the Deepdub Automated Media QC tool.

Scope for this task:
1. Scaffold the repository exactly as specified where relevant to Phase 1.
2. Configure Python 3.12+, uv, Pydantic v2, Typer, pytest, Ruff, and mypy.
3. Create the initial domain models for jobs, assets, presets, measurements, findings, and reports.
4. Create and export the first JSON schemas.
5. Implement a preset YAML loader and schema validator.
6. Add a minimal CLI with these commands:
   - deepdub-qc --help
   - deepdub-qc presets validate <path>
   - deepdub-qc version
7. Add structured logging.
8. Add unit tests.
9. Add a Dockerfile and GitHub Actions CI workflow.
10. Create README.md and CLAUDE.md.

Do not implement FFmpeg detectors yet.
Do not implement the API yet.
Do not add client-specific logic in Python.

Before finishing:
- Run Ruff formatting and linting.
- Run mypy.
- Run pytest.
- Report the test results.
- Summarize created files.
- List unresolved decisions and risks.
```

---

# 32. Recommended Second Claude Code Prompt

```text
Read DEEPDUB_QC_CLAUDE_CODE_HANDOFF.md and inspect the current repository.

Implement Phase 2: report-first prototype.

Requirements:
1. Create a realistic mocked QC result fixture.
2. Implement canonical JSON report output.
3. Implement an HTML report using Jinja2.
4. Implement a PDF renderer from the HTML report.
5. Include report header, overall status, asset information, preset information, summary counts, blocking failures, warnings, media summary, timestamped findings, passed checks, evidence placeholders, and version metadata.
6. Ensure HTML and PDF are generated from the same canonical report model.
7. Add report contract tests and golden-file tests.
8. Add a CLI command that renders the mocked report to an output directory.

Do not implement media detectors yet.
Do not use an LLM to generate canonical report content.

Run formatting, linting, typing, and tests before finishing.
```

---

# 33. Recommended Third Claude Code Prompt

```text
Read DEEPDUB_QC_CLAUDE_CODE_HANDOFF.md and inspect the current repository.

Implement Phase 3: metadata MVP.

Requirements:
1. Implement a safe FFprobe subprocess wrapper.
2. Save raw FFprobe JSON.
3. Normalize container, video, audio, and subtitle metadata into Measurement models.
4. Implement the generic rule engine and required operators.
5. Implement at least these checks:
   - file.readable
   - container.format
   - container.duration
   - video.stream_count
   - video.codec
   - video.width
   - video.height
   - video.frame_rate
   - video.pixel_format
   - audio.stream_count
   - audio.codec
   - audio.sample_rate
   - audio.channel_count
   - audio.channel_layout
   - subtitle.stream_count
   - filename.pattern
6. Implement the end-to-end analyze CLI.
7. Generate JSON, HTML, and PDF reports.
8. Return the documented exit codes.
9. Add unit, parser, rule-engine, and integration tests.
10. Include at least one generated test-media fixture.

Do not implement client-specific Python conditionals.
Do not implement FastAPI yet.
Do not use Claude or any external AI API.

Run formatting, linting, typing, tests, and a Docker smoke test before finishing.
```

---

# 34. Final Product Direction

The local MVP is not the final product.

The intended evolution is:

```text
Local deterministic QC CLI
          ↓
Internal QC service
          ↓
Client preset management
          ↓
Composer Run QC feature
          ↓
Timestamped QC review panel
          ↓
AI-assisted explanation and remediation
          ↓
Deepdub-specific export and localization QC
```

The system should eventually become more valuable than a generic Vidchecker replacement by combining:

- Technical file QC
- Audio and video incident detection
- Composer project-state QC
- Segment and mix validation
- Client-specific delivery rules
- AI-assisted report interpretation

The immediate success criterion is narrower:

> Reliably analyze one exported media file against one versioned client preset and generate a report that allows an operator to make a confident delivery decision.
