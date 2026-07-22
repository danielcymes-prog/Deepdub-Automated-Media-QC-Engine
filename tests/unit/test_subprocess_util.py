"""Safe subprocess wrapper."""

import pytest

from deepdub_qc.utils.subprocess import (
    ToolExecutionError,
    ToolNotFoundError,
    ToolTimeoutError,
    run_tool,
)


class TestRunTool:
    def test_captures_stdout_and_exit_code(self) -> None:
        result = run_tool(["echo", "hello"])
        assert result.exit_code == 0
        assert result.stdout.strip() == "hello"
        assert result.duration_seconds >= 0

    def test_missing_executable_raises_typed_error(self) -> None:
        with pytest.raises(ToolNotFoundError):
            run_tool(["definitely-not-a-real-tool-xyz"])

    def test_nonzero_exit_raises_with_stderr(self) -> None:
        with pytest.raises(ToolExecutionError) as excinfo:
            run_tool(["ls", "/definitely/not/a/path/xyz"])
        assert excinfo.value.exit_code != 0
        assert excinfo.value.stderr

    def test_check_false_returns_result(self) -> None:
        result = run_tool(["ls", "/definitely/not/a/path/xyz"], check=False)
        assert result.exit_code != 0

    def test_timeout_kills_process(self) -> None:
        with pytest.raises(ToolTimeoutError):
            run_tool(["sleep", "5"], timeout=0.2)

    def test_empty_args_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            run_tool([])
