"""FastAPI application: job lifecycle, artifacts, and health endpoints."""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..config import Settings, load_settings
from ..db import JobStore
from ..errors import AIDevOpsError, UnsafeInputError
from ..execution import all_tools, is_docker_available
from ..generator import render_preview
from ..logging_config import configure_logging, get_logger, request_id_var
from ..models import JobRecord, JobState
from ..services import (
    analyze_and_plan,
    create_job_from_archive,
    create_job_from_path,
    execute_job,
    generate_and_validate,
    run_pipeline,
)

log = get_logger("aidevops.api")


# --------------------------------------------------------------------------- #
# Request / response schemas
# --------------------------------------------------------------------------- #
class CreateJobRequest(BaseModel):
    source_path: str = Field(..., description="Local path to the repository to analyze")


class ExecuteRequest(BaseModel):
    approved: bool = Field(
        default=False,
        description="Explicit human approval; execution is refused without it",
    )


class JobSummary(BaseModel):
    id: str
    state: JobState
    project_name: str | None
    created_at: str
    updated_at: str


class HealthResponse(BaseModel):
    status: str
    version: str
    llm_mode: str
    exec_backend: str
    docker_available: bool
    tool_count: int


class ToolCatalogItem(BaseModel):
    name: str
    description: str
    kind: str
    requires_approval: bool
    limits: dict


# --------------------------------------------------------------------------- #
# App factory
# --------------------------------------------------------------------------- #
def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    settings.ensure_dirs()
    configure_logging()

    app = FastAPI(
        title="Autonomous AI DevOps Engineer",
        version=__version__,
        description=(
            "Analyzes a repository, plans a deployment, generates DevOps artifacts, "
            "validates them, and runs a narrow set of allowlisted checks."
        ),
    )
    app.state.settings = settings
    app.state.store = JobStore(settings.db_path)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # ------------------------------------------------------------- middleware
    @app.middleware("http")
    async def _request_id(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["x-request-id"] = rid
        return response

    # ------------------------------------------------------ exception handling
    @app.exception_handler(AIDevOpsError)
    async def _app_error(_: Request, exc: AIDevOpsError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": "validation_error", "message": "invalid request", "detail": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.warning("unhandled error", extra={"event": "unhandled", "tool": type(exc).__name__})
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": type(exc).__name__},
        )

    # ------------------------------------------------------------- dependencies
    def get_settings() -> Settings:
        return app.state.settings

    def get_store() -> JobStore:
        return app.state.store

    # ---------------------------------------------------------------- endpoints
    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "service": "Autonomous AI DevOps Engineer",
            "version": __version__,
            "docs": "/docs",
            "health": "/health",
            "jobs": "/api/jobs",
            "ui": "streamlit run aidevops/ui/streamlit_app.py",
        }

    @app.get("/health", response_model=HealthResponse)
    def health(cfg: Settings = Depends(get_settings)) -> HealthResponse:
        return HealthResponse(
            status="ok",
            version=__version__,
            llm_mode=cfg.llm_mode,
            exec_backend=cfg.exec_backend,
            docker_available=is_docker_available(),
            tool_count=len(all_tools()),
        )

    @app.get("/api/tools", response_model=list[ToolCatalogItem])
    def tools() -> list[ToolCatalogItem]:
        return [
            ToolCatalogItem(
                name=t.name,
                description=t.description,
                kind=t.kind,
                requires_approval=t.requires_approval,
                limits=t.limits,
            )
            for t in all_tools()
        ]

    @app.post("/api/jobs", response_model=JobRecord, status_code=201)
    def create_job(
        body: CreateJobRequest,
        cfg: Settings = Depends(get_settings),
        store: JobStore = Depends(get_store),
    ) -> JobRecord:
        return create_job_from_path(store, cfg, body.source_path)

    @app.post("/api/jobs/upload", response_model=JobRecord, status_code=201)
    async def create_job_upload(
        file: UploadFile = File(...),
        cfg: Settings = Depends(get_settings),
        store: JobStore = Depends(get_store),
    ) -> JobRecord:
        data = await file.read(cfg.max_upload_bytes + 1)
        if len(data) > cfg.max_upload_bytes:
            raise UnsafeInputError(f"upload exceeds {cfg.max_upload_bytes} bytes")
        return create_job_from_archive(store, cfg, data, file.filename or "archive.zip")

    @app.get("/api/jobs", response_model=list[JobSummary])
    def list_jobs(store: JobStore = Depends(get_store)) -> list[JobSummary]:
        return [
            JobSummary(
                id=j.id,
                state=j.state,
                project_name=j.project_name,
                created_at=j.created_at.isoformat(),
                updated_at=j.updated_at.isoformat(),
            )
            for j in store.list()
        ]

    @app.get("/api/jobs/{job_id}", response_model=JobRecord)
    def get_job(job_id: str, store: JobStore = Depends(get_store)) -> JobRecord:
        return store.get(job_id)

    @app.post("/api/jobs/{job_id}/analyze", response_model=JobRecord)
    def analyze(
        job_id: str,
        cfg: Settings = Depends(get_settings),
        store: JobStore = Depends(get_store),
    ) -> JobRecord:
        return analyze_and_plan(store, cfg, job_id)

    @app.post("/api/jobs/{job_id}/generate", response_model=JobRecord)
    def generate(
        job_id: str,
        cfg: Settings = Depends(get_settings),
        store: JobStore = Depends(get_store),
    ) -> JobRecord:
        return generate_and_validate(store, cfg, job_id)

    @app.post("/api/jobs/{job_id}/run", response_model=JobRecord)
    def run(
        job_id: str,
        cfg: Settings = Depends(get_settings),
        store: JobStore = Depends(get_store),
    ) -> JobRecord:
        return run_pipeline(store, cfg, job_id)

    @app.post("/api/jobs/{job_id}/execute", response_model=JobRecord)
    def execute(
        job_id: str,
        body: ExecuteRequest,
        cfg: Settings = Depends(get_settings),
        store: JobStore = Depends(get_store),
    ) -> JobRecord:
        return execute_job(store, cfg, job_id, approved=body.approved)

    @app.post("/api/jobs/{job_id}/cancel", response_model=JobRecord)
    def cancel(job_id: str, store: JobStore = Depends(get_store)) -> JobRecord:
        return store.cancel(job_id)

    @app.get("/api/jobs/{job_id}/artifacts")
    def artifacts(job_id: str, store: JobStore = Depends(get_store)) -> dict:
        job = store.get(job_id)
        return {
            "job_id": job.id,
            "state": job.state.value,
            "preview": render_preview(job.artifacts),
            "artifacts": [a.model_dump() for a in job.artifacts],
            "validation": [v.model_dump() for v in job.validation],
        }

    return app


app = create_app()
