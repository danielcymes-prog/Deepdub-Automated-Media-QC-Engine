"""Phase 3.5 local server: FastAPI app, job queue, worker, operator GUI.

The server is a thin shell over the orchestration pipeline (ADR-014): it
contains zero QC logic, never modifies canonical artifacts, and a job
submitted here is byte-identical (volatile fields excluded) to the same
job run via `deepdub-qc analyze`.
"""
