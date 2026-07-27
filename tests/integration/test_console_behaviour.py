"""Runs the jsdom behavioural suite for the console's client-side polling.

Why this exists as a separate layer: ``tests/unit/test_server_interaction_contract``
asserts the *shape* of app.js — no inline handlers, rows keyed by ``data-job-id``,
visibility gating present. Those assertions are cheap, dependency-free and run
everywhere, but none of them can prove the property that actually matters:

    a focused control must survive a poll.

Before the fix, ``region.innerHTML = fresh.innerHTML`` moved focus to ``<body>``
every two seconds, so the Cancel button on a running job could never be
activated from the keyboard. Only executing the script against a DOM
demonstrates that, and demonstrating it is what stops the bug coming back.

The suite needs Node plus jsdom, which this otherwise Python-only project does
not require (ADR-023). On a developer machine without them it SKIPS with an
actionable hint. In a gate job (``DEEPDUB_QC_REQUIRE_TOOLCHAIN=1``) it FAILS
instead, mirroring the ``weasyprint_native`` contract in ``tests/conftest.py``:
the one suite that proves the focus property must never silently stop running
in a job whose purpose is to prove it (ADR-022).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

JS_TESTS = Path(__file__).resolve().parent.parent / "js"
ENTRYPOINT = JS_TESTS / "console.test.mjs"

#: Same contract as REQUIRE_TOOLCHAIN_ENV in tests/conftest.py (kept literal:
#: `tests` is not an importable package).
REQUIRE_TOOLCHAIN_ENV = "DEEPDUB_QC_REQUIRE_TOOLCHAIN"

#: Generous enough for a cold Node start on a loaded CI box, short enough that a
#: hang fails the build rather than stalling it.
TIMEOUT_SECONDS = 120

pytestmark = pytest.mark.integration


def _node() -> str | None:
    return shutil.which("node")


def _install_hint() -> str:
    return (
        f"install Node 18+ and run `npm install --prefix {JS_TESTS}` "
        "(or `make js-tests`) to enable the console behaviour suite"
    )


def _skip_or_fail_in_gate(reason: str) -> None:
    """Skip locally; fail loudly in a job that forbids silent skips."""
    if os.environ.get(REQUIRE_TOOLCHAIN_ENV) == "1":
        pytest.fail(
            f"{REQUIRE_TOOLCHAIN_ENV}=1 but {reason}. The console behaviour "
            "suite would go unexercised, which ADR-022 forbids in a "
            f"verification job — {_install_hint()}."
        )
    pytest.skip(f"{reason} — {_install_hint()}")


@pytest.fixture(scope="module")
def node_with_jsdom() -> str:
    """Path to a node binary that can import jsdom, or skip/fail with a hint."""
    node = _node()
    if node is None:
        _skip_or_fail_in_gate("node is not on PATH")
    if not (JS_TESTS / "node_modules" / "jsdom").exists():
        _skip_or_fail_in_gate("jsdom is not installed")
    assert node is not None  # _skip_or_fail_in_gate never returns
    return node


def test_js_suite_is_declared_correctly() -> None:
    """Guards the wiring itself, and runs even without Node installed.

    A silently-renamed entrypoint would turn the suite below into a permanent
    skip, which reads as green. This test fails instead.
    """
    assert ENTRYPOINT.is_file(), f"{ENTRYPOINT.name} is missing"
    manifest = json.loads((JS_TESTS / "package.json").read_text(encoding="utf-8"))
    assert manifest["scripts"]["test"].endswith(ENTRYPOINT.name), (
        "package.json test script does not point at the suite entrypoint"
    )
    assert "jsdom" in manifest["devDependencies"]
    # The suite reads app.js by relative path; if the tree moves, it must be updated.
    app_js = JS_TESTS.parent.parent / "src" / "deepdub_qc" / "server" / "static" / "app.js"
    assert app_js.is_file(), "app.js is not where the JS suite expects it"


def test_console_polling_preserves_focus_and_pauses_when_hidden(node_with_jsdom: str) -> None:
    """Execute the jsdom suite; surface its output verbatim on failure."""
    result = subprocess.run(
        [node_with_jsdom, str(ENTRYPOINT)],
        cwd=JS_TESTS,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
        check=False,
    )
    output = f"{result.stdout}\n{result.stderr}".strip()
    assert result.returncode == 0, f"console behaviour suite failed:\n{output}"
    # Guard against a suite that exits 0 having asserted nothing at all.
    assert "0 failed" in result.stdout, f"unexpected suite output:\n{output}"
    assert " passed," in result.stdout
