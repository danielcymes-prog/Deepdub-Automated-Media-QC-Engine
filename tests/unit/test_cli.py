"""CLI behavior and exit-code contract (handoff section 18)."""

from pathlib import Path

from typer.testing import CliRunner

from deepdub_qc import __version__
from deepdub_qc.cli import app
from deepdub_qc.exit_codes import ExitCode

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLE_PRESET = REPO_ROOT / "presets" / "examples" / "generic_broadcast_v1.yaml"

runner = CliRunner()


class TestVersion:
    def test_version_prints_tool_version(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert __version__ in result.output


class TestPresetsValidate:
    def test_valid_preset_exits_zero(self) -> None:
        result = runner.invoke(app, ["presets", "validate", str(EXAMPLE_PRESET)])
        assert result.exit_code == 0
        assert "generic_broadcast" in result.output

    def test_missing_preset_exits_invalid_configuration(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["presets", "validate", str(tmp_path / "nope.yaml")])
        assert result.exit_code == ExitCode.INVALID_CONFIGURATION

    def test_invalid_preset_exits_invalid_configuration(self, tmp_path: Path) -> None:
        path = tmp_path / "invalid.yaml"
        path.write_text("schema_version: 1.0.0\n", encoding="utf-8")
        result = runner.invoke(app, ["presets", "validate", str(path)])
        assert result.exit_code == ExitCode.INVALID_CONFIGURATION


class TestExitCodeContract:
    def test_exit_codes_are_stable(self) -> None:
        """These values are a public contract. Never renumber."""
        assert ExitCode.QC_PASS == 0
        assert ExitCode.QC_WARNING == 1
        assert ExitCode.QC_FAIL == 2
        assert ExitCode.QC_EXECUTION_ERROR == 3
        assert ExitCode.INVALID_CONFIGURATION == 4
        assert ExitCode.INVALID_INPUT == 5
        assert ExitCode.INTERNAL_ERROR == 6
