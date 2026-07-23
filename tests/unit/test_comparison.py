"""Comparison harness: Vidchecker XML parsing and parity diff (backlog #32).

The XML fixture mirrors the structure of real Vidchecker 8.2.2 exports used
for the first parity validation (docs/VALIDATION.md).
"""

from pathlib import Path

import pytest

from deepdub_qc.comparison import (
    IdentityMismatchError,
    RowStatus,
    Tolerances,
    VidcheckerParseError,
    compare_reports,
    parse_vidchecker_report,
)

XML_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<Report xmlns="http://www.vidcheck.com/services">
  <ReportDate>2026-07-23T10:43:36+00:00</ReportDate>
  <ProductName>Vidchecker</ProductName>
  <ProductVersion>8.2.2</ProductVersion>
  <ArrayOfTask>
    <Task>
      <Id>34286</Id>
      <Filename>D:\\marimba\\Delivery\\EPISODE_FRA.wav</Filename>
      <FileSize>{file_size}</FileSize>
      <Template>Deliver-Audio</Template>
      <CheckResult>Warning</CheckResult>
      <StreamInfo>
        <Duration><TotalSeconds>2946.24</TotalSeconds></Duration>
      </StreamInfo>
      <TaskAlerts>
        <TaskAlert>
          <Id>34293</Id>
          <Type>Audio Loudness Info</Type>
          <AlertTypeId>1001</AlertTypeId>
          <Level>AlInfo</Level>
          <StreamIndex>1</StreamIndex>
          <ChannelMaskStr>1-2</ChannelMaskStr>
          <Detail>Measured value (integrated loudness) across stream duration:
            {loudness} LKFS/LUFS.</Detail>
          <DetailParams><LoudnessDb>{loudness}</LoudnessDb></DetailParams>
        </TaskAlert>
        <TaskAlert>
          <Id>34298</Id>
          <Type>Minimum Audio Level</Type>
          <AlertTypeId>1120</AlertTypeId>
          <Level>AlWarning</Level>
          <StreamIndex>1</StreamIndex>
          <ChannelMaskStr>1-2</ChannelMaskStr>
          <Detail>Measured audio level on channel 1 was below threshold level of
            -95.00dB RMS for 178.3 seconds.</Detail>
          <BeginTime><TotalSeconds>2767</TotalSeconds></BeginTime>
          <EndTime><TotalSeconds>2946</TotalSeconds></EndTime>
        </TaskAlert>
        <TaskAlert>
          <Id>34419</Id>
          <Type>Audio Clipping</Type>
          <AlertTypeId>1140</AlertTypeId>
          <Level>AlWarning</Level>
          <StreamIndex>1</StreamIndex>
          <Detail>Some channels configured in this test are not present in the
            input file. This test will not be run.</Detail>
        </TaskAlert>
      </TaskAlerts>
    </Task>
  </ArrayOfTask>
</Report>
"""

FILE_SIZE = 848_530_934


def write_xml(tmp_path: Path, loudness: float = -25.35, file_size: int = FILE_SIZE) -> Path:
    path = tmp_path / "vidchecker.xml"
    path.write_text(XML_TEMPLATE.format(loudness=loudness, file_size=file_size), encoding="utf-8")
    return path


def make_report(loudness: float = -25.4, file_size: int = FILE_SIZE) -> dict:
    def measurement(parameter_id: str, value, start=None, end=None) -> dict:
        return {
            "parameter_id": parameter_id,
            "stream_index": 0,
            "value": value,
            "start_seconds": start,
            "end_seconds": end,
        }

    return {
        "asset": {
            "filename": "EPISODE_FRA.wav",
            "input_path": "D:\\marimba\\Delivery\\EPISODE_FRA.wav",
            "file_size_bytes": file_size,
        },
        "summary": {"overall_status": "WARNING"},
        "measurements": [
            measurement("audio.integrated_loudness", loudness),
            measurement("audio.tail_silence_duration", 178.496, start=2767.744, end=2946.24),
            measurement("audio.flat_factor", 0.0),
        ],
    }


class TestVidcheckerParser:
    def test_parses_task_and_alerts(self, tmp_path: Path) -> None:
        task = parse_vidchecker_report(write_xml(tmp_path))
        assert task.file_size == FILE_SIZE
        assert task.template == "Deliver-Audio"
        assert task.verdict == "Warning"
        assert task.product_version == "8.2.2"
        assert task.duration_seconds == pytest.approx(2946.24)
        assert len(task.alerts) == 3

        loudness = task.alerts[0]
        assert loudness.alert_type_id == 1001
        assert loudness.loudness_db == pytest.approx(-25.35)
        assert not loudness.not_run

        min_level = task.alerts[1]
        assert min_level.begin_seconds == pytest.approx(2767.0)
        assert min_level.end_seconds == pytest.approx(2946.0)

        assert task.alerts[2].not_run  # "This test will not be run."

    def test_rejects_non_vidchecker_xml(self, tmp_path: Path) -> None:
        path = tmp_path / "other.xml"
        path.write_text("<Other/>", encoding="utf-8")
        with pytest.raises(VidcheckerParseError):
            parse_vidchecker_report(path)


class TestCompareReports:
    def test_agreement_produces_matches(self, tmp_path: Path) -> None:
        task = parse_vidchecker_report(write_xml(tmp_path))
        result = compare_reports(make_report(), task)
        by_check = {row.check: row for row in result.rows}
        assert by_check["Integrated loudness"].status is RowStatus.MATCH
        assert by_check["Min level / silence span"].status is RowStatus.MATCH
        assert by_check["Overall verdict"].status is RowStatus.INFO
        assert result.mismatches == 0
        assert result.not_run == 1  # the clipping test Vidchecker skipped

    def test_loudness_beyond_tolerance_mismatches(self, tmp_path: Path) -> None:
        task = parse_vidchecker_report(write_xml(tmp_path, loudness=-23.0))
        result = compare_reports(make_report(loudness=-25.4), task)
        loudness = next(r for r in result.rows if r.check == "Integrated loudness")
        assert loudness.status is RowStatus.MISMATCH
        assert result.mismatches >= 1

    def test_tolerance_is_configurable(self, tmp_path: Path) -> None:
        task = parse_vidchecker_report(write_xml(tmp_path, loudness=-25.0))
        result = compare_reports(make_report(loudness=-25.4), task, Tolerances(loudness_lu=0.5))
        loudness = next(r for r in result.rows if r.check == "Integrated loudness")
        assert loudness.status is RowStatus.MATCH

    def test_different_bytes_refused(self, tmp_path: Path) -> None:
        task = parse_vidchecker_report(write_xml(tmp_path, file_size=FILE_SIZE + 1))
        with pytest.raises(IdentityMismatchError):
            compare_reports(make_report(), task)

    def test_missing_silence_span_mismatches(self, tmp_path: Path) -> None:
        task = parse_vidchecker_report(write_xml(tmp_path))
        report = make_report()
        report["measurements"] = [
            m for m in report["measurements"] if m["parameter_id"] != "audio.tail_silence_duration"
        ]
        result = compare_reports(report, task)
        span = next(r for r in result.rows if r.check == "Min level / silence span")
        assert span.status is RowStatus.MISMATCH

    def test_markdown_output(self, tmp_path: Path) -> None:
        task = parse_vidchecker_report(write_xml(tmp_path))
        markdown = compare_reports(make_report(), task).to_markdown()
        assert "| Integrated loudness |" in markdown
        assert "848,530,934 bytes" in markdown
