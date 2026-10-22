import os
from pathlib import Path

import pytest

from aidevops.analyzer import analyze_path
from aidevops.config import Settings
from aidevops.models import ProjectType


def test_detects_python_project_with_evidence(python_repo: Path, settings: Settings):
    profile = analyze_path(python_repo, settings)

    assert profile.project_type == ProjectType.PYTHON
    assert profile.language == "Python"
    assert profile.framework == "FastAPI"
    assert "requirements.txt" in profile.dependency_manifests
    assert any(e.path == "requirements.txt" for e in profile.evidence)
    assert 8000 in profile.declared_ports
    assert any(p.endswith("test_app.py") for p in profile.test_locations)
    assert profile.confidence > 0.5


def test_detects_node_project(node_repo: Path, settings: Settings):
    profile = analyze_path(node_repo, settings)
    assert profile.project_type == ProjectType.NODE
    assert profile.framework == "Express"
    assert 3000 in profile.declared_ports


def test_unknown_project_is_reported_not_invented(unknown_repo: Path, settings: Settings):
    profile = analyze_path(unknown_repo, settings)
    assert profile.project_type == ProjectType.UNKNOWN
    assert profile.confidence <= 0.2
    assert any("manifest" in w for w in profile.warnings)


def test_sensitive_files_are_skipped(python_repo: Path, settings: Settings):
    (python_repo / ".env").write_text("API_KEY=super-secret-value\n", encoding="utf-8")
    (python_repo / "id_rsa").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n", encoding="utf-8")

    profile = analyze_path(python_repo, settings)

    assert any("sensitive" in w for w in profile.warnings)
    assert all(Path(e.path).name not in {".env", "id_rsa"} for e in profile.evidence)
    blob = " ".join(profile.dependencies) + " " + " ".join(e.path for e in profile.evidence)
    assert "super-secret-value" not in blob


@pytest.mark.skipif(
    not hasattr(os, "symlink") or os.name == "nt",
    reason="symlink creation requires privileges on Windows",
)
def test_symlink_is_not_followed(python_repo: Path, settings: Settings, tmp_path: Path):
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("do-not-read", encoding="utf-8")
    link = python_repo / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("cannot create symlink in this environment")

    profile = analyze_path(python_repo, settings)
    assert any("symlink" in w for w in profile.warnings)
    assert all(e.path != "link.txt" for e in profile.evidence)
