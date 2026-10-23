"""Job orchestration.

This module wires the layers together and owns every state transition. Each
public function loads a job, moves it through the state machine, performs the
work, persists the outcome, and converts unexpected errors into a FAILED job
with a recorded reason (never a silent crash).
"""

from __future__ import annotations

from pathlib import Path

from ..analyzer import analyze_path, extract_archive
from ..config import Settings
from ..db import JobStore
from ..errors import AIDevOpsError, UnsafeInputError, ValidationError
from ..execution import ExecutionContext, run_tool
from ..generator import generate_artifacts, job_workspace
from ..logging_config import get_logger
from ..models import JobRecord, JobState, new_id
from ..planner import build_plan

log = get_logger("aidevops.pipeline")


# --------------------------------------------------------------------------- #
# Job creation
# --------------------------------------------------------------------------- #
def create_job_from_path(store: JobStore, settings: Settings, source_path: str) -> JobRecord:
    if not settings.allow_local_paths:
        raise ValidationError(
            "local path analysis is disabled",
            detail="set AIDEVOPS_ALLOW_LOCAL_PATHS=true, or upload an archive instead",
        )
    root = Path(source_path).expanduser()
    if not root.is_dir():
        raise ValidationError(f"source path is not a directory: {source_path}")
    job = JobRecord(source_path=str(root.resolve()), project_name=root.name or "project")
    return store.create(job)


def create_job_from_archive(
    store: JobStore, settings: Settings, archive_bytes: bytes, filename: str
) -> JobRecord:
    if len(archive_bytes) > settings.max_upload_bytes:
        raise UnsafeInputError(f"upload exceeds {settings.max_upload_bytes} bytes")

    job = JobRecord(project_name="")
    upload_dir = settings.data_dir / "uploads" / job.id
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename or "archive.zip").name
    archive_path = upload_dir / safe_name
    archive_path.write_bytes(archive_bytes)

    extract_dir = settings.data_dir / "projects" / job.id
    project_root = extract_archive(
        archive_path,
        extract_dir,
        max_files=settings.max_extract_files,
        max_total_bytes=settings.max_upload_bytes * 4,
    )
    job.source_path = str(project_root)
    job.project_name = project_root.name or "project"
    return store.create(job)


# --------------------------------------------------------------------------- #
# Pipeline steps
# --------------------------------------------------------------------------- #
def _fail(store: JobStore, job_id: str, exc: Exception) -> JobRecord:
    job = store.get(job_id)
    if job.state not in {JobState.FAILED, JobState.CANCELLED}:
        job.error = f"{type(exc).__name__}: {exc}"
        store.save(job)
        try:
            job = store.transition(job_id, JobState.FAILED, reason=job.error)
        except AIDevOpsError:
            job = store.save(job)
    log.warning("job failed", extra={"event": "job_failed", "job_id": job_id})
    return job


def analyze_and_plan(store: JobStore, settings: Settings, job_id: str) -> JobRecord:
    """PENDING -> ANALYZING -> PLANNED (analysis + planning)."""

    store.transition(job_id, JobState.ANALYZING, reason="analysis started")
    try:
        job = store.get(job_id)
        if not job.source_path:
            raise ValidationError("job has no source path")
        profile = analyze_path(job.source_path, settings)
        job.profile = profile
        job.source_path = profile.root
        job.project_name = job.project_name or Path(profile.root).name
        store.save(job)

        if profile.project_type.value == "unknown" and "Dockerfile" not in profile.existing_dockerfiles:
            raise ValidationError("Could not identify a runnable application. Select the app's source folder containing its package manifest or entry point, or provide a reviewed Dockerfile.")
        plan = build_plan(profile, settings)
        job.plan = plan
        store.save(job)
        return store.transition(
            job_id, JobState.PLANNED, reason=f"plan produced ({plan.source})"
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(store, job_id, exc)


def generate_and_validate(store: JobStore, settings: Settings, job_id: str) -> JobRecord:
    """PLANNED -> GENERATING -> VALIDATING -> AWAITING_APPROVAL | FAILED."""

    store.transition(job_id, JobState.GENERATING, reason="artifact generation started")
    try:
        job = store.get(job_id)
        if job.profile is None or job.plan is None:
            raise ValidationError("job must be analyzed and planned before generation")
        workspace = job_workspace(settings.generated_dir, job.id)
        artifacts, reports = generate_artifacts(job.profile, job.plan, workspace, settings)
        job.artifacts = artifacts
        job.validation = reports
        store.save(job)
        store.transition(job_id, JobState.VALIDATING, reason="artifacts generated")

        errors = [i for report in reports for i in report.errors]
        if errors:
            job = store.get(job_id)
            job.error = f"{len(errors)} validation error(s): {errors[0].code} {errors[0].message}"
            store.save(job)
            return store.transition(job_id, JobState.FAILED, reason=job.error)

        return store.transition(
            job_id,
            JobState.AWAITING_APPROVAL,
            reason="artifacts validated; awaiting approval to execute",
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(store, job_id, exc)


def run_pipeline(store: JobStore, settings: Settings, job_id: str) -> JobRecord:
    """Convenience: run analysis, planning, and generation in one call."""

    job = analyze_and_plan(store, settings, job_id)
    if job.state != JobState.PLANNED:
        return job
    return generate_and_validate(store, settings, job_id)


def execute_job(
    store: JobStore, settings: Settings, job_id: str, *, approved: bool
) -> JobRecord:
    """AWAITING_APPROVAL -> EXECUTING -> VERIFYING -> SUCCEEDED | FAILED."""

    if not approved:
        raise ValidationError(
            "execution requires explicit approval",
            detail="re-submit with approved=true after reviewing the generated artifacts",
        )

    store.transition(job_id, JobState.EXECUTING, reason="operator approved execution")
    try:
        job = store.get(job_id)
        workspace = job_workspace(settings.generated_dir, job.id)
        ctx = ExecutionContext(workspace, settings, job.profile, source_path=job.source_path)

        planned_tools = [("list_workspace", {}), ("dockerfile_lint", {"path": "Dockerfile"})]
        if job.profile is not None and job.profile.test_locations:
            planned_tools.append(("container_test", {}))

        for tool_name, args in planned_tools:
            if store.get(job_id).state == JobState.CANCELLED:
                return store.get(job_id)
            record = run_tool(tool_name, args, ctx, approved=approved)
            job = store.get(job_id)
            job.executions.append(record)
            store.save(job)

        store.transition(job_id, JobState.VERIFYING, reason="execution finished; verifying")
        job = store.get(job_id)

        unsuccessful = [e for e in job.executions if e.status.value != "ok"]
        if unsuccessful:
            job.error = "verification incomplete: " + ", ".join(
                f"{e.tool} ({e.status.value})" for e in unsuccessful
            )
            store.save(job)
            return store.transition(job_id, JobState.FAILED, reason=job.error)

        return store.transition(job_id, JobState.SUCCEEDED, reason="verification passed")
    except Exception as exc:  # noqa: BLE001
        return _fail(store, job_id, exc)
