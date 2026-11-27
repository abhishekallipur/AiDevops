from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import threading
import time

from fastapi.testclient import TestClient
import pytest

from aidevops.api.main import create_app
from aidevops.errors import InvalidTransitionError, PolicyError, ValidationError
from aidevops.privacy import redact, validate_destination
from aidevops.services.preview import LABEL, PreviewService

IMAGE = "sha256:" + "a" * 64


@pytest.fixture
def preview_client(settings):
    with TestClient(create_app(replace(settings, exec_backend="auto"))) as client:
        yield client


def prepared(client, source):
    job = client.post("/api/jobs", json={"source_path": str(source)}).json()
    assert client.post(f"/api/jobs/{job['id']}/run").json()["state"] == "AWAITING_APPROVAL"
    response = client.post(f"/api/jobs/{job['id']}/previews")
    assert response.status_code == 201, response.text
    return response.json()


def wait(service, identity, target):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        record = service.get(identity)
        if record["state"] in target:
            return record
        time.sleep(0.01)
    pytest.fail(str(service.get(identity)))


def fake_docker(service, monkeypatch, identity, *, fail_build=False, exit_app=False):
    calls = []
    running = {"value": False}
    def command(argv, **kwargs):
        calls.append(argv)
        if argv[1] == "build":
            if fail_build:
                return 1, "build failed", False, None
            from pathlib import Path
            Path(argv[argv.index("--iidfile") + 1]).write_text(IMAGE)
            return 0, "built", False, None
        if argv[1:3] == ["image", "inspect"]:
            return 0, json.dumps([{"Id": IMAGE, "Config": {"Labels": {LABEL: identity}}}]), False, None
        if argv[1] == "run":
            running["value"] = True
            return 0, "container-id", False, None
        if argv[1:3] == ["container", "inspect"]:
            if not running["value"]:
                return 1, "No such container", False, None
            return 0, json.dumps([{"Id": "container-id", "Config": {"Labels": {LABEL: identity}},
                "State": {"Running": not exit_app}, "NetworkSettings": {"Ports": {
                "8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "45678"}]}}}]), False, None
        if argv[1] == "rm":
            running["value"] = False
        return 0, "", False, None
    monkeypatch.setattr(service, "command", command)
    return calls


def test_snapshot_excludes_env_and_binds_content(preview_client, python_repo):
    (python_repo / ".env").write_text("SECRET=should-never-be-copied")
    record = prepared(preview_client, python_repo)
    service = preview_client.app.state.previews
    folder = service.root / record["id"] / "context"
    assert not (folder / ".env").exists()
    assert (folder / "app.py").exists() and (folder / "Dockerfile").exists()
    assert service.digest(folder) == record["digest"]
    (folder / "app.py").write_text("changed")
    response = preview_client.post(f"/api/previews/{record['id']}/build", json={"approved": True, "digest": record["digest"]})
    assert response.status_code == 403


def test_secret_in_source_blocks_snapshot(preview_client, python_repo):
    (python_repo / "settings.py").write_text('password="fake-sensitive-password"')
    job = preview_client.post("/api/jobs", json={"source_path": str(python_repo)}).json()
    preview_client.post(f"/api/jobs/{job['id']}/run")
    result = preview_client.post(f"/api/jobs/{job['id']}/previews")
    assert result.status_code == 403
    assert "settings.py" in result.json()["message"]
    assert "fake-sensitive" not in result.text


@pytest.mark.parametrize("fail_build", [False, True])
def test_background_build_and_approval(preview_client, python_repo, monkeypatch, fail_build):
    record = prepared(preview_client, python_repo)
    service, identity = preview_client.app.state.previews, record["id"]
    fake_docker(service, monkeypatch, identity, fail_build=fail_build)
    body = {"approved": False, "digest": record["digest"]}
    assert preview_client.post(f"/api/previews/{identity}/build", json=body).status_code == 403
    body["approved"] = True
    assert preview_client.post(f"/api/previews/{identity}/build", json=body).status_code == 202
    result = wait(service, identity, {"BUILT", "BUILD_FAILED"})
    assert result["state"] == ("BUILD_FAILED" if fail_build else "BUILT")
    assert result["image_id"] == (None if fail_build else IMAGE)


def test_start_stop_expiry_and_cleanup(preview_client, python_repo, monkeypatch):
    import httpx
    record = prepared(preview_client, python_repo)
    service, identity = preview_client.app.state.previews, record["id"]
    calls = fake_docker(service, monkeypatch, identity)
    service.update(identity, state="BUILT", image_id=IMAGE)
    class FakeHTTP:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def stream(self, *args, **kwargs): return self
        status_code = 200
    monkeypatch.setattr("aidevops.services.preview.httpx.Client", FakeHTTP)
    service.approve_start(identity, True, 8000, "/health", 15, {"TEST_SETTING": "fake-secret-value"})
    result = wait(service, identity, {"READY", "START_FAILED"})
    assert result["state"] == "READY", result
    assert result["url"] == "http://127.0.0.1:45678"
    assert "fake-secret-value" not in json.dumps(result)
    assert not list((service.root / identity).glob("runtime-*.env"))
    argv = next(a for a in calls if a[1] == "run")
    assert "127.0.0.1::8000" in argv and "--privileged" not in argv and "-v" not in argv
    service.update(identity, expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
    service.sweep()
    assert service.get(identity)["state"] == "EXPIRED"
    service.cleanup(identity)
    assert service.get(identity)["state"] == "REMOVED"


def test_fastapi_preview_uses_api_docs_if_root_returns_not_found(preview_client):
    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class FakeHTTP:
        def stream(self, _method, url, **_kwargs):
            return FakeResponse(200 if url.endswith("/docs") else 404)

    assert PreviewService._resolve_open_url(
        FakeHTTP(), "http://127.0.0.1:45678", "FastAPI", "/health"
    ) == "http://127.0.0.1:45678/docs"


def test_failed_start_removes_container(preview_client, python_repo, monkeypatch):
    record = prepared(preview_client, python_repo)
    service, identity = preview_client.app.state.previews, record["id"]
    calls = fake_docker(service, monkeypatch, identity, exit_app=True)
    service.update(identity, state="BUILT", image_id=IMAGE)
    service.approve_start(identity, True, 8000, "/", 15, {})
    assert wait(service, identity, {"START_FAILED"})["url"] is None
    assert any(a[1] == "rm" for a in calls)


def test_cancel_build_and_duplicate_claim(preview_client, python_repo, monkeypatch):
    record = prepared(preview_client, python_repo)
    service, identity = preview_client.app.state.previews, record["id"]
    entered = threading.Event()
    def blocked(argv, **kwargs):
        entered.set()
        kwargs["cancel"].wait(3)
        return None, "cancelled", False, "cancelled"
    monkeypatch.setattr(service, "command", blocked)
    service.approve_build(identity, record["digest"], True)
    assert entered.wait(2)
    with pytest.raises(InvalidTransitionError):
        service.approve_build(identity, record["digest"], True)
    service.stop(identity)
    assert wait(service, identity, {"CANCELLED"})["state"] == "CANCELLED"


def test_reconcile_does_not_replay_work(preview_client, python_repo, monkeypatch):
    record = prepared(preview_client, python_repo)
    service, identity = preview_client.app.state.previews, record["id"]
    service.update(identity, state="BUILDING")
    calls = fake_docker(service, monkeypatch, identity)
    service.reconcile()
    assert service.get(identity)["state"] == "INTERRUPTED"
    assert not any(a[1] in {"build", "run"} for a in calls)


def test_environment_validation_and_consent(preview_client, python_repo):
    record = prepared(preview_client, python_repo)
    service, identity = preview_client.app.state.previews, record["id"]
    with pytest.raises(PolicyError):
        service.approve_start(identity, False, 8000, "/", 15, {})
    with pytest.raises(ValidationError):
        service.approve_start(identity, True, 8000, "//external", 15, {})
    with pytest.raises(ValidationError):
        service.approve_start(identity, True, 8000, "/", 15, {"BAD-NAME": "abc"})


def test_privacy_redacts_credentials_and_paths():
    text = 'https://name:fake-password@private.example/wheel /home/user/private.py C:\\Users\\Name\\file.py'
    result = redact(text)
    assert "fake-password" not in result and "/home/user" not in result and "Name" not in result
    assert "fake-key" not in redact("fake-key", ["fake-key"])
    with pytest.raises(PolicyError):
        validate_destination("https://untrusted.example/v1", ("api.openai.com",))
    with pytest.raises(PolicyError):
        validate_destination("http://api.openai.com/v1", ("api.openai.com",))


def test_final_provider_boundary_redacts_and_local_only_blocks(settings, monkeypatch):
    from aidevops.planner.provider import OpenAIProvider
    seen = []
    provider = OpenAIProvider(replace(settings, openai_api_key="fake-provider-key"))
    monkeypatch.setattr(provider, "_client", lambda: object())
    monkeypatch.setattr(provider, "_chat", lambda client, system, user, **kw: (seen.append((system, user)) or '{"ok": true}'))
    provider.complete_json("system", 'password="example-sensitive" https://u:p@host fake-provider-key')
    assert all(value not in str(seen) for value in ["example-sensitive", "u:p@", "fake-provider-key"])
    provider = OpenAIProvider(replace(settings, openai_api_key="key", local_only=True))
    with pytest.raises(Exception, match="local-only"):
        provider.complete_json("system", "user")


def test_disabled_backend_cannot_snapshot(client, python_repo):
    job = client.post("/api/jobs", json={"source_path": str(python_repo)}).json()
    client.post(f"/api/jobs/{job['id']}/run")
    assert client.post(f"/api/jobs/{job['id']}/previews").status_code == 403


def test_environment_lookup_in_source_is_not_a_secret(preview_client, python_repo):
    (python_repo / "settings.py").write_text('import os\napi_key = os.getenv("OPENAI_API_KEY")\n')
    assert prepared(preview_client, python_repo)["state"] == "AWAITING_BUILD_APPROVAL"


def test_single_worker_lock(preview_client):
    service = preview_client.app.state.previews
    with pytest.raises(PolicyError, match="one backend"):
        PreviewService(service.settings, service.jobs)


def test_cleanup_refuses_foreign_container(preview_client, python_repo, monkeypatch):
    record = prepared(preview_client, python_repo)
    service = preview_client.app.state.previews
    calls = []
    def command(argv, **kw):
        calls.append(argv)
        return 0, json.dumps([{"Config": {"Labels": {LABEL: "another-preview"}}}]), False, None
    monkeypatch.setattr(service, "command", command)
    with pytest.raises(PolicyError, match="ownership"):
        service.cleanup(record["id"])
    assert not any(argv[1] == "rm" for argv in calls)


def test_request_error_never_echoes_environment_values(preview_client):
    response = preview_client.post("/api/previews/unknown/start", json={"port": 0,
        "environment": {"PASSWORD": {"bad": "fake-sensitive-value"}}})
    assert response.status_code == 422
    assert "fake-sensitive-value" not in response.text


def test_no_docker_cleanup_does_not_report_stopped(preview_client, python_repo, monkeypatch):
    record = prepared(preview_client, python_repo)
    service = preview_client.app.state.previews
    monkeypatch.setattr(service, "command", lambda *a, **kw: (None, "", False, "daemon unavailable"))
    with pytest.raises(ValidationError):
        service.stop(record["id"])
    assert service.get(record["id"])["state"] != "STOPPED"
