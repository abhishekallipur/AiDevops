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

from aidevops.ui import aws_setup, docker_dashboard  # noqa: E402
from aidevops.ui.docker_dashboard import _docker_api  # noqa: E402
from aidevops.ui.aws_dashboard import _aws_api, _aws_error_guidance  # noqa: E402

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
    assert any(b.label == "Open the example project" for b in app.button)
    assert any(b.label == "Review this upload" for b in app.button)
    assert any("Build and deploy your app" in m.value for m in app.title)


def test_docker_sidebar_section_requires_login(app):
    app.radio[0].set_value("Docker monitoring").run()

    assert not app.exception
    assert any("Docker overview" in title.value for title in app.title)
    assert any("Sign in with the configured administrator" in item.value for item in app.error)


def test_aws_sidebar_section_requires_login(app):
    app.radio[0].set_value("AWS monitoring").run()

    assert not app.exception
    assert any("AWS monitoring" in title.value for title in app.title)
    assert any("configured administrator" in item.value for item in app.error)
    assert any("same hostname" in item.value for item in app.info)


def test_aws_management_section_renders_without_admin_access(app):
    app.radio[0].set_value("AWS management").run()

    assert not app.exception
    assert any("AWS management" in title.value for title in app.title)
    assert any("administrator" in item.value for item in app.info)


def test_aws_setup_page_guides_real_credentials_without_collecting_keys(app):
    app.radio[0].set_value("AWS setup").run()

    assert not app.exception
    assert any("Set up real AWS" in title.value for title in app.title)
    assert any("never asks for or stores AWS access keys" in item.value for item in app.info)
    assert any(button.label == "Check AWS connection" for button in app.button)


def test_aws_setup_connection_check_reports_the_backend_identity(monkeypatch):
    monkeypatch.setattr(
        aws_setup,
        "_aws_api",
        lambda *_args, **_kwargs: (
            {
                "available": True,
                "mode": "aws",
                "account_id": "123456789012",
                "region": "us-east-1",
            },
            None,
        ),
    )
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    at.radio[0].set_value("AWS setup").run()
    next(button for button in at.button if button.label == "Check AWS connection").click().run()

    assert not at.exception
    assert any("Connected to AWS account 123456789012" in item.value for item in at.success)


def test_ai_assistant_has_a_dedicated_workspace_section(app):
    app.radio[0].set_value("AI assistant").run()

    assert not app.exception
    assert any("Aidevops assistant" in item.value for item in app.title)
    assert any("live Docker and AWS status" in item.value for item in app.caption)
    assert "assistant_messages" in app.session_state


def test_ai_assistant_submits_chat_and_displays_reply(monkeypatch):
    calls = []

    def request(method, url, **kwargs):
        if urlparse(url).path == "/api/assistant/chat":
            calls.append((method, kwargs))
            return httpx.Response(200, json={"reply": "Here is the answer."})
        return fake_request(method, url, **kwargs)

    monkeypatch.setattr(httpx, "request", request)
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    at.radio[0].set_value("AI assistant").run()
    at.chat_input[0].set_value("Explain my project workflow").run()

    assert not at.exception
    assert calls[0][0] == "POST"
    assert calls[0][1]["json"]["messages"][-1] == {
        "role": "user",
        "content": "Explain my project workflow",
    }
    assert at.session_state["assistant_messages"][-1] == {
        "role": "assistant",
        "content": "Here is the answer.",
    }


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("Not Found", "older version"),
        ("Could not connect to LocalStack", "/_localstack/health"),
    ],
)
def test_aws_error_guidance_identifies_route_and_localstack_issues(error, expected):
    assert expected in _aws_error_guidance(error)


def test_aws_api_forwards_only_the_session_cookie():
    calls = []

    def fake_api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"available": True}, None

    result, error = _aws_api(
        fake_api,
        "b" * 32,
        "GET",
        "/api/aws/status",
        headers={"X-Test": "kept"},
    )

    assert result == {"available": True}
    assert error is None
    assert calls[0][2]["headers"] == {
        "X-Test": "kept",
        "Cookie": "aidevops_session=" + "b" * 32,
    }


def test_docker_api_forwards_only_the_session_cookie():
    calls = []

    def fake_api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"ok": True}, None

    result, error = _docker_api(
        fake_api,
        "a" * 32,
        "GET",
        "/api/docker/containers",
        headers={"X-Test": "kept"},
    )

    assert result == {"ok": True}
    assert error is None
    assert calls[0][2]["headers"] == {
        "X-Test": "kept",
        "Cookie": "aidevops_session=" + "a" * 32,
    }


def test_docker_api_does_not_send_a_missing_session_cookie():
    called = False

    def fake_api(*args, **kwargs):
        nonlocal called
        called = True

    result, error = _docker_api(fake_api, None, "GET", "/api/docker/containers")

    assert result is None
    assert "administrator" in error
    assert called is False


def test_docker_dashboard_uses_controlled_live_refresh_and_hides_logs(monkeypatch):
    container_id = "a" * 64
    calls = []

    def fake_docker_api(api, cookie, method, path, **kwargs):
        calls.append(path)
        if path == "/api/docker/containers":
            return [
                {
                    "id": container_id,
                    "name": "web",
                    "image": "web:latest",
                    "status": "running",
                    "health_status": "healthy",
                }
            ], None
        if path == f"/api/docker/containers/{container_id}":
            return {
                "id": container_id,
                "name": "web",
                "image": "web:latest",
                "status": "running",
                "health_status": "healthy",
                "created_at": "2026-01-01T00:00:00+00:00",
                "uptime_seconds": 300,
                "ports": ["127.0.0.1:8080->80/tcp"],
            }, None
        if path.endswith("/stats"):
            return {
                "cpu_percent": 12.5,
                "memory_usage_bytes": 1000,
                "memory_limit_bytes": 2000,
                "memory_percent": 50,
                "network_rx_bytes": 1024,
                "network_tx_bytes": 2048,
                "block_read_bytes": 4096,
                "block_write_bytes": 8192,
            }, None
        return {"logs": "not requested"}, None

    monkeypatch.setattr(docker_dashboard, "_docker_api", fake_docker_api)
    app = AppTest.from_file(APP_PATH, default_timeout=30).run()
    app.radio[0].set_value("Docker monitoring").run()

    assert not app.exception
    assert any("Docker overview" in item.value for item in app.title)
    assert any(item.label == "Live refresh" and item.value == 5 for item in app.selectbox)
    assert any(item.label == "Container information" for item in app.expander)
    assert any(item.label == "Recent logs" for item in app.expander)
    assert any(item.label == "More actions" for item in app.expander)
    assert any(path.endswith("/stats") for path in calls)
    assert not any(path.endswith("/logs") for path in calls)


def test_ui_uses_native_theme_settings(app):
    assert not any(r.label == "Choose app theme" for r in app.radio)
    assert any("background: #f7f8fa;" in m.value for m in app.markdown)


def test_ui_shows_plan_and_collapsed_files(app):
    open_review(app)
    assert not app.exception
    assert any("AI-generated suggestion" in m.value for m in app.markdown)
    assert any("Dockerfile" in e.label for e in app.expander)
    assert any("full plan" in e.label for e in app.expander)
    assert any(b.label == "Download all setup files" for b in app.get("download_button"))


def test_ui_create_and_run_example_sets_job(app):
    next(b for b in app.button if b.label == "Open the example project").click().run()
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
    next(b for b in at.button if b.label == "Open the example project").click().run()
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
    assert any(b.label == "Open the example project" for b in app.button)
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


def test_fastapi_preview_offers_docs_when_saved_root_url_is_unavailable(monkeypatch):
    record = {
        "id": "preview_test",
        "state": "READY",
        "url": "http://127.0.0.1:45678",
        "expires_at": "2026-11-25T15:00:00+00:00",
        "file_count": 3,
        "digest": "a" * 64,
        "image_id": "sha256:" + "a" * 64,
        "log": "",
        "error": None,
    }

    def request(method, url, **kwargs):
        if urlparse(url).path.endswith("/previews"):
            return httpx.Response(200, json=[record])
        return fake_request(method, url, **kwargs)

    monkeypatch.setattr(httpx, "request", request)
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    open_review(at)

    links = at.get("link_button")
    assert any(
        item.label == "Open API docs"
        and item.url == "http://127.0.0.1:45678/docs"
        for item in links
    )
    assert any(
        item.label == "Open service root"
        and item.url == "http://127.0.0.1:45678"
        for item in links
    )
    assert not at.exception


def test_workspace_puts_build_before_supporting_details(app):
    open_review(app)
    assert not app.tabs
    assert any(b.label == "Prepare build snapshot" for b in app.button)
    assert any(e.label == "Project overview" for e in app.expander)
    assert any(e.label == "Setup files" for e in app.expander)
    assert any(b.label == "Download all setup files" for b in app.get("download_button"))
    assert not app.exception
