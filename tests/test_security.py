import io
import zipfile
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from aidevops.analyzer import analyze_path
from aidevops.api.main import create_app
from aidevops.config import Settings


def _zip(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_upload_zip_slip_is_rejected(client):
    response = client.post(
        "/api/jobs/upload",
        files={"file": ("evil.zip", _zip({"../../evil.txt": "x"}), "application/zip")},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "unsafe_input"


def test_upload_unsupported_archive_type_is_rejected(client):
    response = client.post(
        "/api/jobs/upload",
        files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "unsafe_input"


def test_local_paths_can_be_disabled(settings: Settings, python_repo: Path):
    locked = TestClient(create_app(replace(settings, allow_local_paths=False)))
    response = locked.post("/api/jobs", json={"source_path": str(python_repo)})
    assert response.status_code == 400


def test_secret_values_never_appear_in_profile(python_repo: Path, settings: Settings):
    (python_repo / ".env").write_text("TOKEN=leak-me-please\n", encoding="utf-8")
    profile = analyze_path(python_repo, settings)
    assert "leak-me-please" not in profile.model_dump_json()


def test_uploaded_archive_is_analyzed(client):
    archive = _zip(
        {
            "proj/requirements.txt": "fastapi\n",
            "proj/app.py": "from fastapi import FastAPI\napp = FastAPI()\n",
        }
    )
    created = client.post("/api/jobs/upload", files={"file": ("proj.zip", archive, "application/zip")})
    assert created.status_code == 201
    job_id = created.json()["id"]

    planned = client.post(f"/api/jobs/{job_id}/run")
    assert planned.status_code == 200
    assert planned.json()["profile"]["project_type"] == "python"
