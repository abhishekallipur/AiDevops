"""FastAPI application: job lifecycle, artifacts, and health endpoints."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

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
from ..services.preview import PreviewService
from ..planner.planner import prompt_preview
from ..errors import ValidationError
from ..privacy import redact

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


class BuildApproval(BaseModel):
    approved: bool = False
    digest: str = Field(min_length=64, max_length=64)


class StartApproval(BaseModel):
    approved: bool = False
    port: int = Field(ge=1, le=65535)
    health_path: str = Field(default="/", max_length=256)
    ttl_minutes: int = Field(default=30, ge=1, le=120)
    environment: dict[str, str] = Field(default_factory=dict, max_length=30)


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

    @asynccontextmanager
    async def lifespan(application):
        application.state.previews = PreviewService(settings, application.state.store)
        try:
            yield
        finally:
            application.state.previews.close()

    app = FastAPI(
        lifespan=lifespan,
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
            content={"error": "validation_error", "message": "invalid request", "detail": [
                {"loc": e["loc"], "type": e["type"], "msg": e["msg"]} for e in exc.errors()]},
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

    @app.get("/api/jobs/{job_id}/ai-prompt")
    def ai_prompt(job_id: str):
        job = app.state.store.get(job_id)
        if not job.profile:
            raise ValidationError("Analyze the project before viewing its AI summary")
        return {"local_only": settings.local_only, **{
            key: redact(value, [settings.openai_api_key]) for key, value in prompt_preview(job.profile).items()}}

    @app.get("/api/jobs/{job_id}/previews")
    def previews(job_id: str):
        app.state.store.get(job_id)
        return [r for r in app.state.previews.all() if r["job_id"] == job_id]

    @app.post("/api/jobs/{job_id}/previews", status_code=201)
    def snapshot(job_id: str):
        return app.state.previews.snapshot(job_id)

    @app.get("/api/previews/{identity}")
    def preview(identity: str):
        return app.state.previews.get(identity)

    @app.post("/api/previews/{identity}/build", status_code=202)
    def build_preview(identity: str, body: BuildApproval):
        return app.state.previews.approve_build(identity, body.digest, body.approved)

    @app.post("/api/previews/{identity}/start", status_code=202)
    def start_preview(identity: str, body: StartApproval):
        return app.state.previews.approve_start(identity, body.approved, body.port,
            body.health_path, body.ttl_minutes, body.environment)

    @app.post("/api/previews/{identity}/stop")
    def stop_preview(identity: str):
        return app.state.previews.stop(identity)

    @app.post("/api/previews/{identity}/cleanup")
    def cleanup_preview(identity: str):
        return app.state.previews.cleanup(identity)

    @app.get("/api/previews/{identity}/logs")
    def preview_logs(identity: str):
        return app.state.previews.logs(identity)

    return app


app = create_app()
