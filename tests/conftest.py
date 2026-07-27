"""Shared test configuration.

Why this exists: the integration suite is guarded by
`skipif(shutil.which("ffmpeg") is None)` so that contributors without FFmpeg
can still run the unit tests. That guard was also silently disarming CI —
FFmpeg was not installed there, so every integration test skipped while
`pytest -q` reported green (ADR-022).

The fix is not to remove the guard but to make it impossible to satisfy
accidentally in a job that is supposed to be the verification gate. Setting
`DEEPDUB_QC_REQUIRE_TOOLCHAIN=1` turns "tool missing, skip" into a hard
collection-time failure.
"""

from __future__ import annotations

import functools
import os
import shutil

import pytest

#: Tools the integration suite needs. The `requires_toolchain` marker below is
#: derived from this tuple, so the CI guard in `pytest_configure` and the
#: local skip conditions share one declaration and cannot drift apart. (They
#: did drift when each module hand-rolled its own `shutil.which` guard.)
REQUIRED_TOOLS = ("ffmpeg", "ffprobe")

REQUIRE_TOOLCHAIN_ENV = "DEEPDUB_QC_REQUIRE_TOOLCHAIN"


@functools.cache
def weasyprint_unavailable_reason() -> str | None:
    """Why WeasyPrint cannot render here, or None if it can.

    Why this is not `pytest.importorskip("weasyprint")`: the Python package is a
    declared dependency and imports fine, but it binds Pango/Cairo through cffi
    at *render* time. On a host without those native libraries the failure is an
    `OSError` from `dlopen`, not an `ImportError`, so `importorskip` does not
    catch it and the test fails with a wall of cffi output instead of skipping.
    That is what happened on macOS, where Pango is not present by default
    (ADR-014 makes WeasyPrint the Docker/Linux backend; Windows uses Playwright).

    The probe renders a trivial document, because merely importing the module is
    not sufficient evidence that the native stack resolves. Cached, so the cost
    is paid once per session.

    Returns: a human-readable reason, or None when rendering works.
    """
    try:
        # Deliberately local: importing weasyprint at module scope would drag its
        # native stack into every collection, including runs that never touch PDF.
        import weasyprint  # noqa: PLC0415
    except ImportError as exc:  # not installed at all
        return f"weasyprint is not installed ({exc})"
    except OSError as exc:  # native libraries missing at import time
        return f"WeasyPrint's native libraries are unavailable ({exc})"

    try:
        weasyprint.HTML(string="<p>probe</p>").write_pdf()
    except OSError as exc:
        return f"WeasyPrint's native libraries are unavailable ({exc})"
    return None


@pytest.fixture(scope="session")
def weasyprint_native() -> None:
    """Require a working WeasyPrint, or skip — but never skip in a gate job.

    Mirrors the `REQUIRE_TOOLCHAIN_ENV` contract in `pytest_configure`: a
    developer on macOS gets an actionable skip, while the CI verification job
    (which sets the variable) fails loudly rather than reporting green on a
    backend it never exercised. ADR-022 forbids the silent-skip case.
    """
    reason = weasyprint_unavailable_reason()
    if reason is None:
        return

    if os.environ.get(REQUIRE_TOOLCHAIN_ENV) == "1":
        pytest.fail(
            f"{REQUIRE_TOOLCHAIN_ENV}=1 but {reason}. The PDF backend would go "
            "untested, which ADR-022 forbids in a verification job. Install the "
            "native stack (Debian: libpango-1.0-0 libpangoft2-1.0-0; "
            "macOS: brew install pango) or unset the variable."
        )
    pytest.skip(f"{reason} — macOS: `brew install pango`; Debian: `libpango-1.0-0`")


def pytest_configure(config: pytest.Config) -> None:
    """Fail fast when a gate job lacks the toolchain it is meant to exercise.

    Side effect: raises `pytest.UsageError`, which aborts the session before
    collection, so the failure names the missing tool instead of surfacing as
    a wall of skips.
    """
    if os.environ.get(REQUIRE_TOOLCHAIN_ENV) != "1":
        return

    missing = [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]
    if missing:
        raise pytest.UsageError(
            f"{REQUIRE_TOOLCHAIN_ENV}=1 but these tools are not on PATH: "
            f"{', '.join(missing)}. The integration suite would skip silently, "
            "which is exactly what ADR-022 forbids in a verification job. "
            "Install FFmpeg or unset the variable."
        )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip `requires_toolchain`-marked tests locally when FFmpeg is missing.

    One mechanism, derived from REQUIRED_TOOLS: modules declare
    `pytest.mark.requires_toolchain` instead of hand-rolling `shutil.which`
    guards (which drifted from this list, and which the gate above never saw).
    In a gate job the missing tool already aborted the session in
    `pytest_configure`, so this only ever runs for local developers.
    """
    missing = [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]
    if not missing:
        return
    skip = pytest.mark.skip(reason=f"requires {', '.join(missing)} on PATH")
    for item in items:
        if item.get_closest_marker("requires_toolchain"):
            item.add_marker(skip)
