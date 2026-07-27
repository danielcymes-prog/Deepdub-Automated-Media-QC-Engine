"""Meta-tests: optional-toolchain guards live in one place and honour the gate.

`tests/conftest.py` centralises toolchain availability so that "the CI guard and
the skip conditions cannot drift apart" (its words). Drift had already happened:
two test modules each probed WeasyPrint independently, and one did it with a bare
`pytest.skip` that could not honour `DEEPDUB_QC_REQUIRE_TOOLCHAIN`. That job is
supposed to fail loudly when a backend is missing (ADR-022); instead it would
have skipped the PDF path and reported green.

A comment asking future contributors not to re-add a local guard would not hold.
These tests make it mechanical.

Detection is AST-based rather than textual, so a docstring that *discusses*
`importorskip("weasyprint")` — as tests/unit/test_report_renderers.py does — is
not mistaken for one.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent.parent
CONFTEST = TESTS_ROOT / "conftest.py"

#: Modules whose availability is host-dependent and therefore must be probed
#: centrally, never per test module.
GATED_MODULES = frozenset({"weasyprint", "playwright"})

TEST_MODULES = sorted(
    path
    for path in TESTS_ROOT.rglob("test_*.py")
    if "node_modules" not in path.parts and "__pycache__" not in path.parts
)


def _imported_names(tree: ast.AST) -> set[str]:
    """Top-level package names imported anywhere in the module, including
    function-local imports (which is exactly where the old guards hid)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_there_are_test_modules_to_check() -> None:
    """Guards the guard: a bad glob would make everything below vacuous."""
    assert len(TEST_MODULES) > 10, f"only found {len(TEST_MODULES)} test modules"


def test_no_test_module_imports_a_gated_backend_directly() -> None:
    """Only conftest.py may touch a host-dependent backend.

    Importing it in a test module is how a local availability check starts, and a
    local check silently defeats the DEEPDUB_QC_REQUIRE_TOOLCHAIN gate.

    Reports every offender at once rather than parametrising per module: this is
    one invariant over the whole tree, and 36 near-identical test IDs would drown
    the suite for no extra signal.
    """
    offenders: list[str] = []
    for module in TEST_MODULES:
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        found = _imported_names(tree) & GATED_MODULES
        if found:
            offenders.append(f"{module.relative_to(TESTS_ROOT)}: {', '.join(sorted(found))}")

    assert not offenders, (
        "these test modules import a host-dependent backend directly:\n  "
        + "\n  ".join(offenders)
        + "\nDepend on the shared fixture in tests/conftest.py instead "
        "(e.g. @pytest.mark.usefixtures('weasyprint_native')), so the "
        "DEEPDUB_QC_REQUIRE_TOOLCHAIN gate still applies."
    )


def test_no_test_module_uses_importorskip_on_a_gated_backend() -> None:
    """`importorskip` only catches ImportError.

    WeasyPrint imports cleanly and then fails at render time with an OSError from
    cffi's dlopen, so `importorskip("weasyprint")` does not skip — it lets the
    test fail with a wall of native-linker output.
    """
    offenders: list[str] = []
    for module in TEST_MODULES:
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "importorskip"):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and arg.value in GATED_MODULES:
                    offenders.append(
                        f"{module.relative_to(TESTS_ROOT)}:{node.lineno} "
                        f"importorskip({arg.value!r})"
                    )

    assert not offenders, (
        "importorskip only catches ImportError, so these do not skip when the "
        "native stack is missing — they fail:\n  " + "\n  ".join(offenders) + "\n"
        "Use the shared fixture in tests/conftest.py, which probes an actual render."
    )


def test_conftest_gate_is_wired_to_the_environment_variable() -> None:
    """The shared fixture must be able to fail, not only skip.

    If it could only skip, centralising the probe would buy nothing: the CI
    verification job would still report green on an unexercised backend.
    """
    source = CONFTEST.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(CONFTEST))

    fixtures = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "weasyprint_native"
    }
    assert fixtures, "conftest.py no longer defines the weasyprint_native fixture"

    fixture_source = ast.get_source_segment(
        source,
        next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "weasyprint_native"
        ),
    )
    assert fixture_source is not None
    assert "REQUIRE_TOOLCHAIN_ENV" in fixture_source, (
        "weasyprint_native must consult REQUIRE_TOOLCHAIN_ENV so a gate job fails "
        "instead of skipping"
    )
    assert "pytest.fail" in fixture_source, "weasyprint_native must be able to fail, not only skip"
    assert "pytest.skip" in fixture_source, (
        "weasyprint_native must still skip for developers without the native stack"
    )
