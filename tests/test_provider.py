from dataclasses import replace
from types import SimpleNamespace

import pytest

from aidevops.config import Settings
from aidevops.errors import ProviderError
from aidevops.planner.provider import OpenAIProvider, _extract_json, build_provider


def test_build_provider_none_without_key(settings: Settings):
    assert build_provider(settings) is None


def test_build_provider_returns_adapter_with_key(settings: Settings):
    assert isinstance(build_provider(replace(settings, openai_api_key="k")), OpenAIProvider)


def test_extract_json_plain():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_prose_wrapped():
    assert _extract_json('Sure, here is the plan:\n{"a": 1}\nHope that helps!') == {"a": 1}


def test_extract_json_rejects_non_object():
    with pytest.raises(ValueError):
        _extract_json("[1, 2, 3]")


def _client(behaviour):
    calls: list[dict] = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=behaviour(kwargs)))]
        )

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), calls


def test_retries_without_json_mode_when_gateway_rejects_it(settings: Settings, monkeypatch):
    """OpenRouter-style gateways reject response_format; we must still succeed."""

    provider = OpenAIProvider(replace(settings, openai_api_key="k", llm_max_retries=0))

    def behaviour(kwargs):
        if "response_format" in kwargs:
            raise RuntimeError("response_format is not supported by this model")
        return '```json\n{"summary": "ok"}\n```'

    client, calls = _client(behaviour)
    monkeypatch.setattr(provider, "_client", lambda *a, **k: client)

    assert provider.complete_json("sys", "user") == {"summary": "ok"}
    assert "response_format" in calls[0]
    assert "response_format" not in calls[1]


def test_raises_provider_error_after_retries(settings: Settings, monkeypatch):
    provider = OpenAIProvider(replace(settings, openai_api_key="k", llm_max_retries=1))
    client, calls = _client(lambda kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(provider, "_client", lambda *a, **k: client)

    with pytest.raises(ProviderError):
        provider.complete_json("sys", "user")
    assert len(calls) == 2  # retries + 1


def test_complete_chat_sends_only_redacted_messages(settings: Settings, monkeypatch):
    provider = OpenAIProvider(
        replace(settings, openai_api_key="test-provider-key", llm_max_retries=0)
    )
    client, calls = _client(
        lambda kwargs: "Your application can be started with its documented command."
    )
    monkeypatch.setattr(provider, "_client", lambda *a, **k: client)

    reply = provider.complete_chat(
        "Help with DevOps.",
        [
            {
                "role": "user",
                "content": "My api_key=private-value. How do I start the app?",
            }
        ],
    )

    assert "documented command" in reply
    assert "private-value" not in calls[0]["messages"][1]["content"]
    assert calls[0]["max_completion_tokens"] == 700


def test_complete_chat_rejects_local_only_mode(settings: Settings):
    provider = OpenAIProvider(
        replace(settings, openai_api_key="key", local_only=True)
    )

    with pytest.raises(ProviderError, match="local-only"):
        provider.complete_chat("sys", [{"role": "user", "content": "hello"}])
