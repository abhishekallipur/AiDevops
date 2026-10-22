"""Pydantic domain models shared across the analyzer, planner, generator, and API.

These models are the single source of truth for the job lifecycle and for every
structured payload the system exchanges. The LLM planner output is validated
against :class:`DeploymentPlan`, so a malformed model response cannot corrupt a
job.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str = "job") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# --------------------------------------------------------------------------- #
# Job lifecycle
# --------------------------------------------------------------------------- #
class JobState(str, Enum):
    PENDING = "PENDING"
    ANALYZING = "ANALYZING"
    PLANNED = "PLANNED"
    GENERATING = "GENERATING"
    VALIDATING = "VALIDATING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


#: Legal state transitions. Terminal states have no outgoing edges.
ALLOWED_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.PENDING: frozenset({JobState.ANALYZING, JobState.FAILED, JobState.CANCELLED}),
    JobState.ANALYZING: frozenset({JobState.PLANNED, JobState.FAILED, JobState.CANCELLED}),
    JobState.PLANNED: frozenset({JobState.GENERATING, JobState.FAILED, JobState.CANCELLED}),
    JobState.GENERATING: frozenset({JobState.VALIDATING, JobState.FAILED, JobState.CANCELLED}),
    JobState.VALIDATING: frozenset(
        {JobState.AWAITING_APPROVAL, JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}
    ),
    JobState.AWAITING_APPROVAL: frozenset(
        {JobState.EXECUTING, JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}
    ),
    JobState.EXECUTING: frozenset({JobState.VERIFYING, JobState.FAILED, JobState.CANCELLED}),
    JobState.VERIFYING: frozenset({JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}),
    JobState.SUCCEEDED: frozenset(),
    JobState.FAILED: frozenset(),
    JobState.CANCELLED: frozenset(),
}

TERMINAL_STATES = frozenset({JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED})


def can_transition(src: JobState, dst: JobState) -> bool:
    return dst in ALLOWED_TRANSITIONS.get(src, frozenset())


class StateTransition(BaseModel):
    from_state: JobState
    to_state: JobState
    at: datetime = Field(default_factory=utcnow)
    reason: str | None = None


# --------------------------------------------------------------------------- #
# Repository analysis
# --------------------------------------------------------------------------- #
class ProjectType(str, Enum):
    PYTHON = "python"
    NODE = "node"
    JAVA_MAVEN = "java_maven"
    JAVA_GRADLE = "java_gradle"
    GO = "go"
    RUST = "rust"
    UNKNOWN = "unknown"


class Evidence(BaseModel):
    path: str
    reason: str


class ProjectProfile(BaseModel):
    root: str
    project_type: ProjectType = ProjectType.UNKNOWN
    language: str | None = None
    framework: str | None = None
    confidence: float = 0.0
    dependency_manifests: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    entry_points: list[str] = Field(default_factory=list)
    test_locations: list[str] = Field(default_factory=list)
    declared_ports: list[int] = Field(default_factory=list)
    existing_dockerfiles: list[str] = Field(default_factory=list)
    existing_ci_files: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    files_scanned: int = 0
    truncated: bool = False

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, value: float) -> float:
        return max(0.0, min(1.0, value))


# --------------------------------------------------------------------------- #
# Deployment plan (LLM or mock)
# --------------------------------------------------------------------------- #
class PlanStep(BaseModel):
    id: str
    title: str
    description: str = ""
    command: str | None = None  # advisory only; never executed verbatim
    requires_approval: bool = False


class ArtifactSpec(BaseModel):
    kind: Literal["Dockerfile", ".dockerignore", "docker-compose.yml", "ci_workflow"]
    rationale: str = ""


class DeploymentPlan(BaseModel):
    summary: str
    runtime: str | None = None
    build_command: str | None = None
    test_command: str | None = None
    run_command: str | None = None
    exposed_port: int | None = None
    base_image: str | None = None
    steps: list[PlanStep] = Field(default_factory=list)
    artifacts: list[ArtifactSpec] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    source: Literal["llm", "mock"] = "mock"


# --------------------------------------------------------------------------- #
# Generated artifacts and validation
# --------------------------------------------------------------------------- #
class GeneratedArtifact(BaseModel):
    path: str  # relative path inside the job's generated workspace
    kind: str
    content: str
    verified: bool = False
    notes: list[str] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    severity: Literal["error", "warning", "info"]
    code: str
    message: str


class ValidationReport(BaseModel):
    artifact_path: str
    passed: bool
    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]


# --------------------------------------------------------------------------- #
# Controlled execution
# --------------------------------------------------------------------------- #
class ExecutionStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    BLOCKED = "blocked"


class ExecutionRecord(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    status: ExecutionStatus
    exit_code: int | None = None
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    output: str = ""
    truncated: bool = False
    reason: str | None = None
    container: bool = False


# --------------------------------------------------------------------------- #
# Job record
# --------------------------------------------------------------------------- #
class JobRecord(BaseModel):
    id: str = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    state: JobState = JobState.PENDING
    source_path: str | None = None
    project_name: str | None = None
    profile: ProjectProfile | None = None
    plan: DeploymentPlan | None = None
    artifacts: list[GeneratedArtifact] = Field(default_factory=list)
    validation: list[ValidationReport] = Field(default_factory=list)
    executions: list[ExecutionRecord] = Field(default_factory=list)
    error: str | None = None
    history: list[StateTransition] = Field(default_factory=list)

    def find_artifact(self, path: str) -> GeneratedArtifact | None:
        for art in self.artifacts:
            if art.path == path:
                return art
        return None
