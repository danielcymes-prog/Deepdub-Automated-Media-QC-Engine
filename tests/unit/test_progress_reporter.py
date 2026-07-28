"""Stage-weighted progress fractions for the console wheel (display only, ADR-001)."""

from deepdub_qc.orchestration.pipeline import _ProgressReporter


def make_reporter() -> tuple[_ProgressReporter, list[tuple[str, float]]]:
    events: list[tuple[str, float]] = []
    reporter = _ProgressReporter(lambda message, fraction: events.append((message, fraction)))
    return reporter, events


class TestProgressReporter:
    def test_fractions_walk_detectors_then_fixed_stages(self) -> None:
        reporter, events = make_reporter()
        reporter.plan(2)  # 2 detectors + 4 fixed stages = 6 units
        reporter.announce("[1/2] Running a")
        reporter.finish_stage("    a done")
        reporter.announce("[2/2] Running b")
        reporter.finish_stage("    b done")
        reporter.announce("Evaluating rules")
        reporter.finish_stage()
        reporter.announce("Generating evidence")
        reporter.finish_stage()
        reporter.announce("Hashing asset")
        reporter.finish_stage()
        reporter.announce("Rendering reports")
        fractions = [fraction for _, fraction in events]
        assert fractions == [
            0.0,
            round(1 / 6, 4),
            round(1 / 6, 4),
            round(2 / 6, 4),
            round(2 / 6, 4),
            round(3 / 6, 4),
            round(4 / 6, 4),
            round(5 / 6, 4),
        ]
        assert fractions == sorted(fractions)

    def test_skipped_stage_advances_without_a_message(self) -> None:
        reporter, events = make_reporter()
        reporter.plan(0)  # 4 fixed stages only
        reporter.announce("Evaluating rules")
        reporter.finish_stage()
        reporter.finish_stage()  # evidence skipped: counts, emits nothing
        reporter.announce("Hashing asset")
        assert events == [("Evaluating rules", 0.0), ("Hashing asset", 0.5)]

    def test_failed_detector_still_counts_as_a_finished_stage(self) -> None:
        reporter, events = make_reporter()
        reporter.plan(1)
        reporter.announce("[1/1] Running a")
        reporter.finish_stage("    a FAILED: boom")
        assert events[-1] == ("    a FAILED: boom", 0.2)

    def test_no_callback_is_safe(self) -> None:
        reporter = _ProgressReporter(None)
        reporter.plan(3)
        reporter.announce("anything")
        reporter.finish_stage("done")  # must not raise
