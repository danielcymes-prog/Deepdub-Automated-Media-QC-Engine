"""EBU Tech 3341/3342 loudness conformance suite (risk R2).

Runs the toolchain (ffmpeg ebur128 + our parser) over the official EBU
Loudness test set and asserts every measurement against the specification
targets and tolerances recorded in tests/fixtures/ebu_manifest.yaml.

The WAV fixtures are licensed for technical testing only and are not
committed; the suite skips when they are absent (see fixtures/ebu/README.md).
"""

import shutil
from pathlib import Path

import pytest
import yaml

from deepdub_qc.detectors.audio.loudness import parse_ebur128
from deepdub_qc.utils.subprocess import run_tool

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EBU_DIR = REPO_ROOT / "tests" / "fixtures" / "ebu"
MANIFEST = REPO_ROOT / "tests" / "fixtures" / "ebu_manifest.yaml"

#: manifest metric name -> parse_ebur128 key
_METRIC_KEYS = {
    "integrated": "integrated_loudness",
    "loudness_range": "loudness_range",
    "true_peak": "true_peak",
    "max_momentary": "max_momentary",
    "max_short_term": "max_short_term",
}

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not available"),
]


def _load_vectors() -> list[dict]:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["vectors"]


def _measure(path: Path) -> dict[str, float]:
    result = run_tool(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-filter:a",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ],
        timeout=300.0,
    )
    return parse_ebur128(result.stderr)


@pytest.mark.parametrize("vector", _load_vectors(), ids=lambda v: v["file"])
def test_ebu_vector_conformance(vector: dict) -> None:
    path = EBU_DIR / vector["file"]
    if not path.is_file():
        pytest.skip("EBU test set not present (see tests/fixtures/ebu/README.md)")

    measured = _measure(path)
    problems = []
    for metric, spec in vector.items():
        if metric == "file":
            continue
        key = _METRIC_KEYS[metric]
        value = measured.get(key)
        if value is None:
            problems.append(f"{metric}: no measurement produced")
            continue
        low = spec["target"] - spec["tol_minus"]
        high = spec["target"] + spec["tol_plus"]
        if not (low <= value <= high):
            problems.append(
                f"{metric}: measured {value}, spec {spec['target']} "
                f"(+{spec['tol_plus']}/-{spec['tol_minus']})"
            )
    assert not problems, f"{vector['file']}: {problems}"
