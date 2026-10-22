"""Deployment planning.

The planner produces a schema-validated :class:`DeploymentPlan`. It never
executes anything: the plan's ``command`` fields are advisory text for the
operator and are not run by the executor. When no provider key is configured —
or the provider fails — a deterministic mock plan is returned, always labelled
with ``source="mock"`` and an explicit assumption explaining why.
"""

from __future__ import annotations

import json

from ..config import Settings
from ..logging_config import get_logger
from ..models import (
    ArtifactSpec,
    DeploymentPlan,
    PlanStep,
    ProjectProfile,
    ProjectType,
)
from .provider import build_provider

log = get_logger("aidevops.planner")

SYSTEM_PROMPT = (
    "You are a senior DevOps engineer. Given a static analysis of a repository, "
    "produce a minimal, safe deployment plan as a JSON object that matches the "
    "provided schema exactly. Rules: never include real credentials, account IDs "
    "or secrets; use placeholders; prefer least privilege and non-root containers; "
    "never claim anything has been executed or deployed. Only reference evidence "
    "that was provided. If a value is unknown, use null and list it under "
    "assumptions."
)

RUNTIME_DEFAULTS = {
    ProjectType.PYTHON: ("python:3.12-slim", "pip install -r requirements.txt", "python -m pytest"),
    ProjectType.NODE: ("node:20-slim", "npm ci", "npm test"),
    ProjectType.JAVA_MAVEN: ("eclipse-temurin:21-jre", "mvn -B package", "mvn -B test"),
    ProjectType.JAVA_GRADLE: ("eclipse-temurin:21-jre", "./gradlew build", "./gradlew test"),
    ProjectType.GO: ("gcr.io/distroless/static-debian12", "go build ./...", "go test ./..."),
    ProjectType.RUST: ("debian:bookworm-slim", "cargo build --release", "cargo test"),
    ProjectType.UNKNOWN: (None, None, None),
}


def _schema_hint() -> str:
    return json.dumps(DeploymentPlan.model_json_schema(), indent=2)


def _profile_digest(profile: ProjectProfile) -> str:
    return json.dumps(
        {
            "project_type": profile.project_type.value,
            "language": profile.language,
            "framework": profile.framework,
            "confidence": profile.confidence,
            "dependency_manifests": profile.dependency_manifests,
            "dependencies": profile.dependencies[:40],
            "entry_points": profile.entry_points,
            "test_locations": profile.test_locations[:20],
            "declared_ports": profile.declared_ports,
            "existing_dockerfiles": profile.existing_dockerfiles,
            "existing_ci_files": profile.existing_ci_files,
            "warnings": profile.warnings,
        },
        indent=2,
    )


def mock_plan(profile: ProjectProfile, reason: str) -> DeploymentPlan:
    """Deterministic, evidence-derived plan used when the LLM is unavailable."""

    base_image, build_cmd, test_cmd = RUNTIME_DEFAULTS[profile.project_type]
    port = profile.declared_ports[0] if profile.declared_ports else None
    run_command = None
    if profile.project_type == ProjectType.PYTHON and profile.entry_points:
        main = profile.entry_points[0]
        if main.endswith(".py"):
            module = main[:-3].replace("/", ".")
            run_command = f"python -m {module}"
        else:
            run_command = f"python {main}"
    elif profile.project_type == ProjectType.NODE:
        run_command = "node index.js"

    steps = [
        PlanStep(
            id="install",
            title="Install dependencies",
            description=f"Use the detected manifest(s): {', '.join(profile.dependency_manifests) or 'none found'}.",
            command=build_cmd,
        ),
        PlanStep(
            id="test",
            title="Run test suite",
            description=(
                f"Run tests found in {len(profile.test_locations)} location(s)."
                if profile.test_locations
                else "No tests detected; add a test command before relying on this plan."
            ),
            command=test_cmd,
        ),
        PlanStep(
            id="build-image",
            title="Build container image",
            description="Build using the generated Dockerfile in an isolated workspace.",
            command="docker build -t app:local .",
            requires_approval=True,
        ),
        PlanStep(
            id="deploy",
            title="Deploy (not implemented in this milestone)",
            description="AWS/Terraform deployment is a planned extension point; nothing is applied here.",
            command=None,
            requires_approval=True,
        ),
    ]

    artifacts = [
        ArtifactSpec(kind="Dockerfile", rationale="Containerize the detected runtime."),
        ArtifactSpec(kind=".dockerignore", rationale="Keep the build context small and secret-free."),
    ]
    if port is not None:
        artifacts.append(
            ArtifactSpec(kind="docker-compose.yml", rationale=f"Expose detected port {port} locally.")
        )
    if profile.test_locations and not profile.existing_ci_files:
        artifacts.append(
            ArtifactSpec(kind="ci_workflow", rationale="No existing CI detected; add a test workflow.")
        )

    assumptions = [reason]
    if profile.project_type == ProjectType.UNKNOWN:
        assumptions.append("Project type could not be determined from evidence.")
    if not profile.dependency_manifests:
        assumptions.append("No dependency manifest was found; the build command is a guess.")
    if port is None:
        assumptions.append("No port was detected in the repository.")

    risks = []
    if not profile.test_locations:
        risks.append("No tests detected, so validation confidence is low.")
    if profile.existing_dockerfiles:
        risks.append(
            f"Repository already contains container files: {', '.join(profile.existing_dockerfiles)}"
        )
    risks.append("Generated artifacts are unverified until the validation checks pass.")

    return DeploymentPlan(
        summary=(
            f"Mock plan ({profile.project_type.value}) derived from static evidence. "
            "Not produced by an LLM."
        ),
        runtime=profile.framework or profile.language,
        build_command=build_cmd,
        test_command=test_cmd,
        run_command=run_command,
        exposed_port=port,
        base_image=base_image,
        steps=steps,
        artifacts=artifacts,
        risks=risks,
        assumptions=assumptions,
        source="mock",
    )


def _cross_check(plan: DeploymentPlan, profile: ProjectProfile) -> DeploymentPlan:
    """Reconcile the plan against observed evidence.

    LLM plans frequently omit fields the analyzer already knows (such as the
    port). Filling those from *detected evidence* is a reconciliation, not an
    invention, and it is recorded in the assumptions so a human can audit it.
    """

    if plan.exposed_port is None and profile.declared_ports:
        plan.exposed_port = profile.declared_ports[0]
        plan.assumptions.append(
            f"Plan did not specify a port; using detected port {plan.exposed_port} "
            f"from {profile.declared_ports}."
        )
    elif (
        plan.exposed_port is not None
        and profile.declared_ports
        and plan.exposed_port not in profile.declared_ports
    ):
        plan.assumptions.append(
            f"Plan exposes port {plan.exposed_port}, which was not in the detected ports "
            f"{profile.declared_ports}."
        )
    if not plan.artifacts:
        plan.artifacts = [
            ArtifactSpec(kind="Dockerfile", rationale="Plan omitted artifacts; defaulting to Dockerfile."),
            ArtifactSpec(kind=".dockerignore", rationale="Plan omitted artifacts."),
        ]
    return plan


def build_plan(profile: ProjectProfile, settings: Settings) -> DeploymentPlan:
    """Return a validated plan, falling back to a labelled mock on any failure."""

    provider = build_provider(settings)
    if provider is None:
        log.info("no provider configured; returning mock plan", extra={"event": "plan_mock"})
        return mock_plan(
            profile,
            reason="Mock plan because no LLM provider key is configured (AIDEVOPS_LLM=off).",
        )

    user_prompt = (
        "Repository analysis (evidence only, do not assume more):\n"
        f"{_profile_digest(profile)}\n\n"
        "Return a JSON object matching this schema exactly:\n"
        f"{_schema_hint()}\n"
    )
    try:
        raw = provider.complete_json(SYSTEM_PROMPT, user_prompt)
        raw["source"] = "llm"
        plan = DeploymentPlan.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - fall back on any provider/validation error
        log.warning(
            "planning failed; falling back to mock",
            extra={"event": "plan_fallback", "tool": type(exc).__name__},
        )
        return mock_plan(
            profile,
            reason=f"Mock plan because the LLM provider failed ({type(exc).__name__}).",
        )
    return _cross_check(plan, profile)
