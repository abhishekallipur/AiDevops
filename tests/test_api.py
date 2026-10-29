from dataclasses import replace
from pathlib import Path


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["llm_mode"] == "mock"
    assert body["tool_count"] >= 4
    assert "x-request-id" in response.headers


def test_assistant_chat_requires_provider_configuration(client):
    response = client.post(
        "/api/assistant/chat",
        json={"messages": [{"role": "user", "content": "How do I run my app?"}]},
    )

    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_assistant_chat_surfaces_provider_errors(client, monkeypatch):
    from aidevops.errors import ProviderError
    from aidevops.planner.provider import OpenAIProvider

    client.app.state.settings = replace(
        client.app.state.settings,
        openai_api_key="test-openai-key",
    )

    def fail_chat(self, system, messages):
        raise ProviderError("assistant provider request failed", detail="APIConnectionError")

    monkeypatch.setattr(OpenAIProvider, "complete_chat", fail_chat)
    response = client.post(
        "/api/assistant/chat",
        json={"messages": [{"role": "user", "content": "What is the weather?"}]},
    )

    assert response.status_code == 502
    assert response.json()["error"] == "provider_error"
    assert response.json()["message"] == "assistant provider request failed"


def test_assistant_chat_uses_configured_provider_without_exposing_key(
    client, monkeypatch
):
    from aidevops.planner.provider import OpenAIProvider

    client.app.state.settings = replace(
        client.app.state.settings,
        openai_api_key="test-openai-key",
    )
    calls = []

    def complete_chat(self, system, messages):
        calls.append((system, messages))
        return "Use the project preview to verify the application."

    monkeypatch.setattr(OpenAIProvider, "complete_chat", complete_chat)
    response = client.post(
        "/api/assistant/chat",
        json={"messages": [{"role": "user", "content": "How do I preview my app?"}]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "reply": "Use the project preview to verify the application."
    }
    assert "test-openai-key" not in response.text
    assert calls[0][1] == [
        {"role": "user", "content": "How do I preview my app?"}
    ]


def test_assistant_chat_rejects_invalid_message_order(client):
    response = client.post(
        "/api/assistant/chat",
        json={"messages": [{"role": "assistant", "content": "Hello"}]},
    )

    assert response.status_code == 422


def test_tools_catalog(client):
    response = client.get("/api/tools")
    assert response.status_code == 200
    names = {t["name"] for t in response.json()}
    assert {"dockerfile_lint", "container_test", "container_build_image", "list_workspace"} <= names


def test_full_pipeline_then_approved_execution(client, python_repo: Path):
    created = client.post("/api/jobs", json={"source_path": str(python_repo)})
    assert created.status_code == 201
    job_id = created.json()["id"]

    planned = client.post(f"/api/jobs/{job_id}/run")
    assert planned.status_code == 200
    job = planned.json()
    assert job["state"] == "AWAITING_APPROVAL"
    assert job["plan"]["source"] == "mock"
    assert job["profile"]["project_type"] == "python"

    artifacts = client.get(f"/api/jobs/{job_id}/artifacts").json()
    assert any(a["path"] == "Dockerfile" for a in artifacts["artifacts"])
    assert artifacts["preview"]

    refused = client.post(f"/api/jobs/{job_id}/execute", json={"approved": False})
    assert refused.status_code == 400
    assert refused.json()["error"] == "validation_error"

    executed = client.post(f"/api/jobs/{job_id}/execute", json={"approved": True})
    assert executed.status_code == 200
    assert executed.json()["state"] == "FAILED"
    assert "container_test (blocked)" in executed.json()["error"]


def test_generate_before_analyze_is_a_conflict(client, python_repo: Path):
    job_id = client.post("/api/jobs", json={"source_path": str(python_repo)}).json()["id"]
    response = client.post(f"/api/jobs/{job_id}/generate")
    assert response.status_code == 409
    assert response.json()["error"] == "invalid_transition"


def test_create_job_with_bad_path(client, tmp_path: Path):
    response = client.post("/api/jobs", json={"source_path": str(tmp_path / "does-not-exist")})
    assert response.status_code == 400
    assert response.json()["error"] == "validation_error"


def test_unknown_job_returns_404(client):
    assert client.get("/api/jobs/job_missing").status_code == 404


def test_job_list_and_detail(client, python_repo: Path):
    job_id = client.post("/api/jobs", json={"source_path": str(python_repo)}).json()["id"]
    listed = client.get("/api/jobs").json()
    assert any(j["id"] == job_id for j in listed)
    assert client.get(f"/api/jobs/{job_id}").json()["state"] == "PENDING"
