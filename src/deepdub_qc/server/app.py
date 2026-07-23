"""FastAPI application: JSON API + server-rendered operator GUI (ADR-014).

Invariants (docs/server-gui-spec.md section 1): zero QC logic here; canonical
artifacts are served as static files from the job directory, never
re-rendered; every artifact path is containment-checked against the job
directory after resolution (security section 9).

The API routes mirror the future Composer contract (handoff section 23) so
Phase 7 extraction changes deployment, not shape.
"""

from __future__ import annotations

import contextlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Form, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from deepdub_qc import __version__
from deepdub_qc.server.catalog import PresetInfo, build_catalog
from deepdub_qc.server.config import LoadedConfig
from deepdub_qc.server.sessions import SessionTracker
from deepdub_qc.server.store import JobRecord, JobStore, QueueFullError, UnknownJobError
from deepdub_qc.server.validation import validate_submission

logger = logging.getLogger(__name__)

_HERE = Path(__file__).parent
SESSION_COOKIE = "qc_session"

#: GUI artifacts an operator opens from the job detail page.
_ARTIFACT_FILES = {
    "report": ("report.json", "application/json"),
    "report.html": ("report.html", "text/html"),
    "report.pdf": ("report.pdf", "application/pdf"),
}


@dataclass
class AppState:
    """Shared application state (dependency-injected via app.state)."""

    loaded: LoadedConfig
    store: JobStore
    catalog: list[PresetInfo]
    sessions: SessionTracker


def _job_payload(store: JobStore, job: JobRecord) -> dict[str, Any]:
    position = store.queue_position(job.job_id)
    return {
        "job_id": job.job_id,
        "status": job.status.value,
        "queue_position": position[0] if position else None,
        "queue_total": position[1] if position else None,
        "input_path": job.input_path,
        "output_dir": job.output_dir,
        "filename": Path(job.input_path).name,
        "input_size_bytes": job.input_size_bytes,
        "preset_id": job.preset_id,
        "preset_version": job.preset_version,
        "requested_by": job.requested_by,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "qc_status": job.qc_status,
        "summary": job.summary,
        "error_reason": job.error_reason,
        "error_message": job.error_message,
        "progress": job.progress,
        "cancel_requested": job.cancel_requested,
        "resubmit_of": job.resubmit_of,
        "cancelled_by": job.cancelled_by,
    }


def _contained_file(job_dir: Path, relative: str) -> Path | None:
    """Resolve a job artifact path; None unless it stays inside the job dir."""
    try:
        resolved = (job_dir / relative).resolve()
        root = job_dir.resolve()
    except OSError:
        return None
    if not resolved.is_relative_to(root) or not resolved.is_file():
        return None
    return resolved


def _api_router(state: AppState) -> APIRouter:  # noqa: PLR0915 - route table
    router = APIRouter(prefix="/api/v1")
    store, config = state.store, state.loaded.config

    @router.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "queue_depth": store.queue_depth(),
            "active_gui_sessions": state.sessions.active_count(),
        }

    @router.get("/presets")
    def presets() -> list[dict[str, Any]]:
        return [
            {
                "preset_id": p.preset_id,
                "version": p.version,
                "client": p.client,
                "content_type": p.content_type,
                "status": p.status,
                "title": p.title,
                "description": p.description,
                "effective_date": p.effective_date,
            }
            for p in state.catalog
        ]

    @router.post("/qc/jobs", status_code=201)
    def submit_job(payload: dict[str, Any]) -> JSONResponse:
        result = validate_submission(
            raw_path=str(payload.get("input_path", "")),
            preset_id=str(payload.get("preset_id", "")),
            preset_version=str(payload.get("preset_version", "")),
            requested_by=str(payload.get("requested_by", "")),
            config=config,
            store=store,
            catalog=state.catalog,
            duplicate_override=bool(payload.get("duplicate_override", False)),
            resubmit_of=payload.get("resubmit_of"),
        )
        if result.errors:
            return JSONResponse(
                status_code=422,
                content={"errors": [e.__dict__ for e in result.errors]},
            )
        if result.duplicate is not None:
            return JSONResponse(
                status_code=409,
                content={
                    "duplicate_of": result.duplicate.job_id,
                    "state": result.duplicate.status.value,
                    "message": "This exact file and preset are already in flight. "
                    "Set duplicate_override=true to submit anyway.",
                },
            )
        assert result.submission is not None
        try:
            record = store.enqueue(
                result.submission,
                jobs_root=config.paths.jobs_root,
                max_queue_length=config.jobs.max_queue_length,
            )
        except QueueFullError as exc:
            return JSONResponse(status_code=429, content={"error": str(exc)})
        return JSONResponse(status_code=201, content=_job_payload(store, record))

    @router.get("/qc/jobs")
    def list_jobs(
        offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)
    ) -> dict[str, Any]:
        return {
            "total": store.count_jobs(),
            "offset": offset,
            "limit": limit,
            "jobs": [_job_payload(store, j) for j in store.list_jobs(offset, limit)],
        }

    @router.get("/qc/jobs/{job_id}")
    def job_detail(job_id: str) -> JSONResponse:
        try:
            job = store.get(job_id)
        except UnknownJobError:
            return JSONResponse(status_code=404, content={"error": "unknown job"})
        return JSONResponse(content=_job_payload(store, job))

    @router.post("/qc/jobs/{job_id}/cancel")
    def cancel(job_id: str, payload: dict[str, Any] | None = None) -> JSONResponse:
        try:
            outcome = store.request_cancel(job_id, (payload or {}).get("cancelled_by"))
        except UnknownJobError:
            return JSONResponse(status_code=404, content={"error": "unknown job"})
        return JSONResponse(content={"result": outcome})

    @router.get("/qc/jobs/{job_id}/{artifact}", response_model=None)
    def artifact(job_id: str, artifact: str) -> JSONResponse | FileResponse:
        if artifact not in _ARTIFACT_FILES:
            return JSONResponse(status_code=404, content={"error": "unknown artifact"})
        try:
            job = store.get(job_id)
        except UnknownJobError:
            return JSONResponse(status_code=404, content={"error": "unknown job"})
        filename, media_type = _ARTIFACT_FILES[artifact]
        target = _contained_file(Path(job.output_dir), filename)
        if target is None:
            return JSONResponse(status_code=404, content={"error": "artifact not available"})
        return FileResponse(target, media_type=media_type)

    @router.get("/qc/jobs/{job_id}/files/{file_path:path}", response_model=None)
    def job_file(job_id: str, file_path: str) -> JSONResponse | FileResponse:
        """Evidence and raw artifacts; containment-checked (security 9.3)."""
        try:
            job = store.get(job_id)
        except UnknownJobError:
            return JSONResponse(status_code=404, content={"error": "unknown job"})
        target = _contained_file(Path(job.output_dir), file_path)
        if target is None:
            return JSONResponse(status_code=404, content={"error": "not found"})
        return FileResponse(target)

    @router.get("/browse")
    def browse(path: str = Query("")) -> JSONResponse:
        """Path-browser listing, restricted to media_roots (spec 3.1)."""
        roots = config.paths.media_roots
        if not path:
            return JSONResponse(
                content={
                    "path": "",
                    "entries": [{"name": str(r), "path": str(r), "kind": "root"} for r in roots],
                }
            )
        try:
            resolved = Path(path).resolve(strict=True)
        except OSError:
            return JSONResponse(status_code=404, content={"error": "not found"})
        if not any(resolved.is_relative_to(r.resolve()) for r in roots if r.is_dir()):
            return JSONResponse(status_code=403, content={"error": "outside media roots"})
        if not resolved.is_dir():
            return JSONResponse(status_code=400, content={"error": "not a directory"})
        entries: list[dict[str, Any]] = []
        for child in sorted(resolved.iterdir(), key=lambda c: (c.is_file(), c.name.lower())):
            if child.name.startswith("."):
                continue
            if child.is_dir():
                entries.append({"name": child.name, "path": str(child), "kind": "dir"})
            else:
                entries.append(
                    {
                        "name": child.name,
                        "path": str(child),
                        "kind": "file",
                        "size_bytes": child.stat().st_size,
                    }
                )
        return JSONResponse(content={"path": str(resolved), "entries": entries})

    @router.get("/validate-path")
    def validate_path(path: str = Query(...)) -> JSONResponse:
        """Submit-form blur check: found / readable / size (E1-E3 preview)."""
        result = validate_submission(
            raw_path=path,
            preset_id="__none__",
            preset_version="0",
            requested_by="__probe__",
            config=config,
            store=store,
            catalog=state.catalog,
        )
        path_errors = [e for e in result.errors if e.field == "input_path"]
        if path_errors:
            return JSONResponse(
                content={
                    "ok": False,
                    "code": path_errors[0].code,
                    "message": path_errors[0].message,
                }
            )
        size = Path(path).stat().st_size
        return JSONResponse(content={"ok": True, "size_bytes": size})

    return router


def _format_size(size: int | None) -> str:
    if size is None:
        return "—"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def _gui_router(state: AppState, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()
    store, config = state.store, state.loaded.config

    def render(request: Request, template: str, **context: Any) -> HTMLResponse:
        context.setdefault("version", __version__)
        context.setdefault("poll_interval", config.server.queue_poll_interval_seconds)
        return templates.TemplateResponse(request, template, context)

    @router.get("/", response_class=HTMLResponse)
    def submit_page(request: Request) -> HTMLResponse:
        return render(
            request,
            "submit.html.j2",
            catalog=state.catalog,
            errors={},
            form={},
            duplicate=None,
            jobs_root=str(config.paths.jobs_root),
        )

    @router.post("/submit")
    def submit(  # noqa: PLR0913 - one parameter per form field
        request: Request,
        input_path: str = Form(""),
        preset: str = Form(""),
        requested_by: str = Form(""),
        duplicate_override: bool = Form(False),
        resubmit_of: str = Form(""),
    ) -> Any:
        preset_id, _, preset_version = preset.partition("@")
        result = validate_submission(
            raw_path=input_path,
            preset_id=preset_id,
            preset_version=preset_version,
            requested_by=requested_by,
            config=config,
            store=store,
            catalog=state.catalog,
            duplicate_override=duplicate_override,
            resubmit_of=resubmit_of or None,
        )
        form = {
            "input_path": input_path,
            "preset": preset,
            "requested_by": requested_by,
        }
        if result.errors:
            errors = {e.field: e.message for e in result.errors}
            return render(
                request,
                "submit.html.j2",
                catalog=state.catalog,
                errors=errors,
                form=form,
                duplicate=None,
                jobs_root=str(config.paths.jobs_root),
            )
        if result.duplicate is not None:
            return render(
                request,
                "submit.html.j2",
                catalog=state.catalog,
                errors={},
                form=form,
                duplicate=result.duplicate,
                jobs_root=str(config.paths.jobs_root),
            )
        assert result.submission is not None
        try:
            record = store.enqueue(
                result.submission,
                jobs_root=config.paths.jobs_root,
                max_queue_length=config.jobs.max_queue_length,
            )
        except QueueFullError as exc:
            return render(
                request,
                "error.html.j2",
                title="Queue is full",
                message=str(exc),
                advice="Wait for a pending job to finish, then try again.",
            )
        return RedirectResponse(url=f"/jobs/{record.job_id}", status_code=303)

    @router.get("/jobs", response_class=HTMLResponse)
    def jobs_page(request: Request, page: int = Query(1, ge=1)) -> HTMLResponse:
        limit = 50
        jobs = [_job_payload(store, j) for j in store.list_jobs((page - 1) * limit, limit)]
        total = store.count_jobs()
        return render(
            request,
            "jobs.html.j2",
            jobs=jobs,
            page=page,
            pages=max(1, -(-total // limit)),
            total=total,
            format_size=_format_size,
        )

    @router.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_page(request: Request, job_id: str) -> HTMLResponse:
        try:
            job = store.get(job_id)
        except UnknownJobError:
            return render(
                request,
                "error.html.j2",
                title="Unknown job",
                message=f"No job {job_id[:8]} exists on this server.",
                advice="It may predate the last database reset. Check the Jobs list.",
            )
        payload = _job_payload(store, job)
        # Completed: read the summary from the CANONICAL report.json (ADR-002),
        # not the store snapshot; blocking failures come from the same file.
        blocking: list[dict[str, Any]] = []
        summary: dict[str, Any] | None = payload["summary"]
        report_path = _contained_file(Path(job.output_dir), "report.json")
        if job.status.value == "completed" and report_path is not None:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            summary = report.get("summary", summary)
            blocking = [
                f
                for f in report.get("findings", [])
                if f.get("blocking") and f.get("status") in ("FAIL", "ERROR")
            ]
        return render(
            request,
            "job_detail.html.j2",
            job=payload,
            summary=summary,
            blocking=blocking[:5],
            blocking_more=max(0, len(blocking) - 5),
            has_pdf=_contained_file(Path(job.output_dir), "report.pdf") is not None,
            format_size=_format_size,
        )

    @router.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, cancelled_by: str = Form("")) -> RedirectResponse:
        with contextlib.suppress(UnknownJobError):
            store.request_cancel(job_id, cancelled_by or None)
        return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)

    @router.get("/presets", response_class=HTMLResponse)
    def presets_page(request: Request) -> HTMLResponse:
        return render(request, "presets.html.j2", catalog=state.catalog)

    return router


def create_app(loaded: LoadedConfig, store: JobStore | None = None) -> FastAPI:
    """Build the application; the worker is started by the serve command."""
    config = loaded.config
    state = AppState(
        loaded=loaded,
        store=store if store is not None else JobStore(config.paths.database),
        catalog=build_catalog(config.paths.presets_root),
        sessions=SessionTracker(
            config.server.max_gui_sessions, config.server.gui_session_ttl_minutes
        ),
    )
    app = FastAPI(title="Deepdub QC", version=__version__, docs_url="/api/docs")
    app.state.qc = state

    templates = Jinja2Templates(directory=_HERE / "templates")
    app.mount("/static", StaticFiles(directory=_HERE / "static"), name="static")
    app.include_router(_api_router(state))
    app.include_router(_gui_router(state, templates))

    @app.middleware("http")
    async def session_cap(request: Request, call_next: Any) -> Any:
        """GUI session cap (spec section 7). API and static paths are exempt."""
        path = request.url.path
        if path.startswith(("/api/", "/static/")):
            return await call_next(request)
        session_id = state.sessions.touch(request.cookies.get(SESSION_COOKIE))
        if session_id is None:
            html = templates.get_template("cap.html.j2").render(
                ttl_minutes=config.server.gui_session_ttl_minutes,
                max_sessions=config.server.max_gui_sessions,
                version=__version__,
            )
            return HTMLResponse(html, status_code=503)
        response = await call_next(request)
        response.set_cookie(SESSION_COOKIE, session_id, httponly=True, samesite="lax")
        return response

    return app
