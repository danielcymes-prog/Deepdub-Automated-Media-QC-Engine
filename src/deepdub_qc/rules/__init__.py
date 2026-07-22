"""Rule engine: evaluates measurements against preset rules (ADR-001, ADR-009).

Measurements are facts. Rules compare facts. Findings are the result.
This package never imports detectors and never sees client names.
"""

from deepdub_qc.rules.engine import aggregate_status, build_summary, evaluate

__all__ = ["aggregate_status", "build_summary", "evaluate"]
