"""Automated tests for the Streamlit UI using Streamlit's headless AppTest.

The backend is faked by patching ``httpx.request``, so these tests need no
running server and no network. This closes the "UI is only verified by
inspection" gap recorded in docs/TESTING.md.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest

pytest.importorskip("streamlit")
pytest.importorskip("streamlit.testing.v1")

from streamlit.testing.v1 import AppTest  # noqa: E402

APP_PATH = str(Path(__file__).resolve().parents[1] / "aidevops" / "ui" / "streamlit_app.py")

JOB_ID = "job_test123456"

PROFILE = {
    "root": "/tmp/demo",
    "project_type": "python",
    "language": "Python",
    "framework": "FastAPI",
    "confidence": 0.93,
    "dependency_manifests": ["requirements.txt"],
    "dependencies": ["fastapi"],
    "entry_points": ["app.py"],
    "test_locations": ["tests/test_app.py"],
    "declared_ports": [8080],
    "existing_dockerfiles": [],
    "existing_ci_files": [],
    "evidence": [{"path": "requirements.txt", "reason": "python dependency manifest"}],
    "warnings": [],
    "files_scanned": 4,
    "truncated": False,
}

PLAN = {
    "summary": "Containerize the FastAPI app.",
    "runtime": "FastAPI",
    "build_command": "pip install -r requirements.txt",
    "test_command": "python -m pytest",
    "run_command": "python -m app",
    "exposed_port": 8080,
    "base_image": "python:3.12-slim",
    "steps": [{"id": "install", "title": "Install", "description": "deps", "command": None,
               "requires_approval": False}],
    "artifacts": [{"kind": "Dockerfile", "rationale": "containerize"}],
    "risks": ["unverified until checks pass"],
    "assumptions": ["mock plan"],
    "source": "llm",
}

ARTIFACTS = [
    {"path": "Dockerfile", "kind": "Dockerfile", "content": "FROM python:3.12-slim\nUSER 10001\n",
     "verified": True, "notes": []},
    {"path": ".dockerignore", "kind": ".dockerignore", "content": ".git\n.env\n",
     "verified": True, "notes": []},
]

VALIDATION = [
    {"artifact_path": "Dockerfile", "passed": True, "issues": []},
    {"artifact_path": ".dockerignore", "passed": True, "issues": []},
]


def _job(state: str) -> dict:
    return {
        "id": JOB_ID,
        "created_at": "2026-10-21T00:00:00+00:00",
        "updated_at": "2026-10-21T00:00:00+00:00",
        "state": state,
        "source_path": "/tmp/demo",
        "project_name": "demo",
        "profile": PROFILE,
        "plan": PLAN,
        "artifacts": ARTIFACTS,
        "validation": VALIDATION,
        "executions": [],
        "error": None,
        "history": [],
    }


HEALTH = {
    "status": "ok",
    "version": "0.1.0",
    "llm_mode": "mock",
    "exec_backend": "auto",
    "docker_available": False,
    "tool_count": 4,
}


def fake_request(method: str, url: str, **kwargs):
    path = urlparse(url).path
    if path == "/health":
        return httpx.Response(200, json=HEALTH)
    if path == "/api/jobs" and method == "GET":
        return httpx.Response(200, json=[_job("AWAITING_APPROVAL")])
    if path == "/api/jobs" and method == "POST":
        return httpx.Response(201, json=_job("PENDING"))
    if path.endswith("/run"):
        return httpx.Response(200, json=_job("AWAITING_APPROVAL"))
    if path.endswith("/artifacts"):
        return httpx.Response(200, json={"job_id": JOB_ID, "state": "AWAITING_APPROVAL",
                                        "preview": "…", "artifacts": ARTIFACTS,
                                        "validation": VALIDATION})
    if path.endswith("/execute"):
        return httpx.Response(200, json=_job("SUCCEEDED"))
    if path.endswith("/cancel"):
        return httpx.Response(200, json=_job("CANCELLED"))
    if path == f"/api/jobs/{JOB_ID}":
        return httpx.Response(200, json=_job("AWAITING_APPROVAL"))
    return httpx.Response(404, json={"error": "not_found", "message": path})


@pytest.fixture
def app(monkeypatch) -> AppTest:
    monkeypatch.setattr(httpx, "request", fake_request)
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    return at


def open_review(app):
    app.session_state["job_id"] = JOB_ID
    app.session_state["new_project"] = False
    return app.run()


def test_ui_renders_without_exception(app):
    assert not app.exception
    assert any(b.label == "Try an example project" for b in app.button)
    assert any(t.label == "Upload a project" for t in app.tabs)
    assert any("Your project." in m.value for m in app.markdown)


def test_ui_shows_plan_and_collapsed_files(app):
    open_review(app)
    assert not app.exception
    assert any("AI-generated suggestion" in m.value for m in app.markdown)
    assert any("Dockerfile" in e.label for e in app.expander)
    assert any("full plan" in e.label for e in app.expander)
    assert any(b.label == "Download all setup files" for b in app.get("download_button"))


def test_ui_create_and_run_example_sets_job(app):
    next(b for b in app.button if b.label == "Try an example project").click().run()
    assert not app.exception
    assert app.session_state["job_id"] == JOB_ID
    assert any("Ready for your review" in m.value for m in app.markdown)


def test_new_job_is_not_overridden_by_recent_selection(monkeypatch):
    new_id = "job_new123456"
    def request(method, url, **kwargs):
        path = urlparse(url).path
        if (path == "/api/jobs" and method == "POST") or new_id in path:
            if path.endswith("/artifacts"):
                return fake_request(method, url, **kwargs)
            return httpx.Response(200, json={**_job("AWAITING_APPROVAL"), "id": new_id})
        return fake_request(method, url, **kwargs)
    monkeypatch.setattr(httpx, "request", request)
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    next(b for b in at.button if b.label == "Try an example project").click().run()
    assert not at.exception
    assert at.session_state["job_id"] == new_id
    at.run()
    assert at.session_state["job_id"] == new_id


def test_blank_folder_shows_useful_error(app):
    next(b for b in app.button if b.label == "Review this folder").click().run()
    assert any("folder location" in e.value for e in app.error)
    assert not app.exception


def test_approval_requires_consent_and_available_test_environment(app):
    open_review(app)
    button = next(b for b in app.button if b.label == "Approve & run checks")
    assert button.disabled
    next(c for c in app.checkbox if c.label.startswith("I have reviewed")).check().run()
    assert next(b for b in app.button if b.label == "Approve & run checks").disabled
    assert any("Project tests are unavailable" in w.value for w in app.warning)


def test_approve_sends_explicit_permission_when_docker_ready(monkeypatch):
    requests = []
    def request(method, url, **kwargs):
        if urlparse(url).path == "/health":
            return httpx.Response(200, json={**HEALTH, "docker_available": True})
        if urlparse(url).path.endswith("/execute"):
            requests.append(kwargs.get("json"))
        return fake_request(method, url, **kwargs)
    monkeypatch.setattr(httpx, "request", request)
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    open_review(at)
    assert next(b for b in at.button if b.label == "Approve & run checks").disabled
    next(c for c in at.checkbox if c.label.startswith("I have reviewed")).check().run()
    next(b for b in at.button if b.label == "Approve & run checks").click().run()
    assert requests == [{"approved": True}]
    assert not at.exception


def test_new_project_returns_to_onboarding(app):
    open_review(app)
    next(b for b in app.button if b.label == "＋ New project").click().run()
    assert not app.exception
    assert any(b.label == "Try an example project" for b in app.button)
    assert not any(c.label.startswith("I have reviewed") for c in app.checkbox)


def test_mock_plan_is_clearly_labelled(monkeypatch):
    def request(method, url, **kwargs):
        if urlparse(url).path == f"/api/jobs/{JOB_ID}":
            return httpx.Response(200, json={**_job("AWAITING_APPROVAL"), "plan": {**PLAN, "source": "mock"}})
        return fake_request(method, url, **kwargs)
    monkeypatch.setattr(httpx, "request", request)
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    open_review(at)
    assert any("Example plan · not AI-generated" in m.value for m in at.markdown)


def test_offline_service_has_reconnect_and_setup_help(monkeypatch):
    def offline(*args, **kwargs):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(httpx, "request", offline)
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    assert not at.exception
    assert any(b.label == "Try connecting again" for b in at.button)
    assert any("Setup help" in e.label for e in at.expander)


def test_failed_review_is_not_displayed_as_completed(monkeypatch):
    def request(method, url, **kwargs):
        if urlparse(url).path == f"/api/jobs/{JOB_ID}":
            return httpx.Response(200, json={**_job("FAILED"), "error": "test failed"})
        return fake_request(method, url, **kwargs)
    monkeypatch.setattr(httpx, "request", request)
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    open_review(at)
    assert not at.exception
    assert any("needs attention" in m.value for m in at.markdown)
    assert not any(c.label.startswith("I have reviewed") for c in at.checkbox)


def test_recent_review_can_be_opened(app):
    app.selectbox[0].select(JOB_ID).run()
    assert not app.exception
    assert app.session_state["job_id"] == JOB_ID
    assert any("Ready for your review" in m.value for m in app.markdown)


def test_preview_build_consent_and_request(monkeypatch):
    calls = []
    record = {"id": "preview_test", "state": "AWAITING_BUILD_APPROVAL", "file_count": 3,
              "digest": "a" * 64, "image_id": None, "log": "", "error": None}
    def request(method, url, **kwargs):
        path = urlparse(url).path
        if path.endswith("/previews"):
            return httpx.Response(200, json=[record])
        if path.endswith("/build"):
            calls.append(kwargs["json"])
            return httpx.Response(202, json=record)
        return fake_request(method, url, **kwargs)
    monkeypatch.setattr(httpx, "request", request)
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    open_review(at)
    assert not at.exception
    assert next(b for b in at.button if b.label == "Build my app").disabled
    next(c for c in at.checkbox if "approve building" in c.label).check().run()
    next(b for b in at.button if b.label == "Build my app").click().run()
    assert calls == [{"approved": True, "digest": "a" * 64}]


def test_preview_start_consent_can_enable_form(monkeypatch):
    record = {"id": "preview_test", "state": "BUILT", "file_count": 3,
              "digest": "a" * 64, "image_id": "sha256:" + "a" * 64, "log": "", "error": None}
    calls = []
    def request(method, url, **kwargs):
        path = urlparse(url).path
        if path.endswith("/previews"):
            return httpx.Response(200, json=[record])
        if path.endswith("/start"):
            calls.append(kwargs["json"])
            return httpx.Response(202, json=record)
        return fake_request(method, url, **kwargs)
    monkeypatch.setattr(httpx, "request", request)
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    open_review(at)
    assert not at.exception
    assert next(b for b in at.button if b.label == "Start local preview").disabled
    next(c for c in at.checkbox if "approve starting" in c.label).check().run()
    assert not next(b for b in at.button if b.label == "Start local preview").disabled
    next(b for b in at.button if b.label == "Start local preview").click().run()
    assert calls == [{"approved": True, "port": 8080, "health_path": "/health",
                      "ttl_minutes": 30, "environment": {}}]
    assert any(e.label == "Advanced preview settings" for e in at.expander)
    assert not at.exception


def test_workspace_puts_build_before_supporting_details(app):
    open_review(app)
    assert [tab.label for tab in app.tabs] == [
        "Build & preview", "Project overview", "Setup files", "Checks & results"
    ]
    assert any(b.label == "Prepare build snapshot" for b in app.tabs[0].button)
    assert any(b.label == "Download all setup files" for b in app.tabs[2].get("download_button"))
    assert not app.exception
