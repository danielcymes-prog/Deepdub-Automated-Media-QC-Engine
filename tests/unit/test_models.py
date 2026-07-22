"""Domain model round-trips and invariants."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from deepdub_qc.models import (
    Asset,
    Category,
    Environment,
    JobStatus,
    Measurement,
    PresetRef,
    QCJob,
    QCResult,
    QCStatus,
    Summary,
)
from deepdub_qc.models.report import VOLATILE_FIELDS
from deepdub_qc.utils.ids import measurement_id


def make_measurement() -> Measurement:
    return Measurement(
        measurement_id=measurement_id(
            "metadata.ffprobe", "1.0.0", "video.width", 0, None, None, 1920
        ),
        job_id=uuid4(),
        detector_id="metadata.ffprobe",
        detector_version="1.0.0",
        parameter_id="video.width",
        category=Category.VIDEO,
        value=1920,
        stream_index=0,
    )


def make_result() -> QCResult:
    job_id = uuid4()
    return QCResult(
        job=QCJob(job_id=job_id, status=JobStatus.COMPLETED, tool_version="0.1.0"),
        asset=Asset(
            input_path="/media/final.mov",
            filename="final.mov",
            file_size_bytes=1024,
            sha256="a" * 64,
        ),
        preset=PresetRef(
            preset_id="generic_broadcast",
            preset_version="1.0.0",
            client="generic",
            content_type="broadcast",
            sha256="b" * 64,
        ),
        environment=Environment(python_version="3.13.0", platform="linux/amd64"),
        summary=Summary(
            overall_status=QCStatus.PASS,
            total_checks=1,
            passed=1,
            warnings=0,
            failed=0,
            errors=0,
            skipped=0,
            not_applicable=0,
            blocking_failures=0,
        ),
    )


class TestMeasurement:
    def test_round_trip_via_json(self) -> None:
        m = make_measurement()
        restored = Measurement.model_validate_json(m.model_dump_json())
        assert restored == m

    def test_confidence_bounds_enforced(self) -> None:
        base = make_measurement().model_dump()
        base["confidence"] = 1.5
        with pytest.raises(ValidationError):
            Measurement.model_validate(base)

    def test_polymorphic_values_accepted(self) -> None:
        base = make_measurement().model_dump()
        for value in ["prores", 23.976, True, [1, 2], {"num": 24000, "den": 1001}, None]:
            base["value"] = value
            assert Measurement.model_validate(base).value == value

    def test_measurement_is_immutable(self) -> None:
        m = make_measurement()
        with pytest.raises(ValidationError):
            m.value = 1080  # type: ignore[misc]


class TestQCResult:
    def test_round_trip_via_json(self) -> None:
        result = make_result()
        restored = QCResult.model_validate_json(result.model_dump_json())
        assert restored == result

    def test_created_at_is_utc(self) -> None:
        m = make_measurement()
        assert m.created_at.tzinfo is not None
        assert m.created_at.astimezone(UTC).utcoffset().total_seconds() == 0  # type: ignore[union-attr]

    def test_volatile_fields_declared(self) -> None:
        """The determinism contract must at minimum cover ids and timestamps."""
        assert "job.job_id" in VOLATILE_FIELDS
        assert "measurements[].created_at" in VOLATILE_FIELDS
        assert "findings[].created_at" in VOLATILE_FIELDS

    def test_ai_summary_defaults_to_none(self) -> None:
        assert make_result().ai_summary is None


class TestModelsAreFrozen:
    def test_result_rejects_mutation(self) -> None:
        result = make_result()
        with pytest.raises(ValidationError):
            result.summary = result.summary  # type: ignore[misc]

    def test_datetime_now_returns_aware(self) -> None:
        assert datetime.now(UTC).tzinfo is UTC
