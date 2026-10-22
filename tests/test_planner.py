from dataclasses import replace

from aidevops.config import Settings
from aidevops.errors import ProviderError
from aidevops.models import ProjectProfile
from aidevops.planner import build_plan, mock_plan


def test_mock_plan_when_no_key_configured(python_profile: ProjectProfile, settings: Settings):
    plan = build_plan(python_profile, settings)
    assert plan.source == "mock"
    assert plan.assumptions
    assert "no LLM provider key" in plan.assumptions[0] or "Mock plan" in plan.assumptions[0]
    assert any(a.kind == "Dockerfile" for a in plan.artifacts)
    assert plan.exposed_port == 8000


def test_valid_llm_output_is_used(python_profile: ProjectProfile, settings: Settings, monkeypatch):
    configured = replace(settings, openai_api_key="test-key")

    class FakeProvider:
        name = "fake"

        def complete_json(self, system: str, user: str):
            return {
                "summary": "LLM-generated plan",
                "artifacts": [{"kind": "Dockerfile", "rationale": "containerize"}],
                "steps": [{"id": "s1", "title": "build"}],
            }

    monkeypatch.setattr("aidevops.planner.planner.build_provider", lambda s: FakeProvider())
    plan = build_plan(python_profile, configured)

    assert plan.source == "llm"
    assert plan.summary == "LLM-generated plan"


def test_provider_failure_falls_back_to_labelled_mock(
    python_profile: ProjectProfile, settings: Settings, monkeypatch
):
    configured = replace(settings, openai_api_key="test-key")

    class Boom:
        name = "boom"

        def complete_json(self, system: str, user: str):
            raise ProviderError("network down")

    monkeypatch.setattr("aidevops.planner.planner.build_provider", lambda s: Boom())
    plan = build_plan(python_profile, configured)

    assert plan.source == "mock"
    assert any("failed" in a.lower() for a in plan.assumptions)


def test_malformed_llm_output_falls_back(python_profile: ProjectProfile, settings: Settings, monkeypatch):
    configured = replace(settings, openai_api_key="test-key")

    class BadJson:
        name = "bad"

        def complete_json(self, system: str, user: str):
            return {"summary": 123, "steps": "not-a-list"}  # fails schema validation

    monkeypatch.setattr("aidevops.planner.planner.build_provider", lambda s: BadJson())
    plan = build_plan(python_profile, configured)
    assert plan.source == "mock"


def test_llm_plan_missing_port_falls_back_to_detected_port(
    python_profile: ProjectProfile, settings: Settings, monkeypatch
):
    """LLM plans often omit the port; the analyzer already knows it, so reconcile."""

    configured = replace(settings, openai_api_key="test-key")

    class FakeProvider:
        name = "fake"

        def complete_json(self, system: str, user: str):
            return {"summary": "no port here", "artifacts": [{"kind": "Dockerfile"}]}

    monkeypatch.setattr("aidevops.planner.planner.build_provider", lambda s: FakeProvider())
    plan = build_plan(python_profile, configured)

    assert plan.source == "llm"
    assert plan.exposed_port == python_profile.declared_ports[0]
    assert any("detected port" in a for a in plan.assumptions)


def test_unknown_project_mock_plan_has_no_copied_details(settings: Settings):
    profile = ProjectProfile(root="x")
    plan = mock_plan(profile, "no key")
    assert "Project type could not be determined from evidence." in plan.assumptions
    assert plan.run_command is None
