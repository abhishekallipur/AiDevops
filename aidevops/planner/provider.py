"""LLM provider adapters.

The planner talks to a provider only through this interface, so swapping
providers never touches business logic. Credentials come from the environment;
nothing here reads or writes them to disk.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from ..config import Settings
from ..errors import ProviderError
from ..privacy import redact, validate_destination
from ..logging_config import get_logger

log = get_logger("aidevops.planner.provider")

_FENCE_RE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*|\s*```\s*$")

#: Substrings that indicate a gateway rejected the JSON response format rather
#: than a genuine transient failure. Many OpenRouter models fall here.
_UNSUPPORTED_JSON_HINTS = ("response_format", "json_object", "json mode", "unsupported parameter")


def _extract_json(content: str) -> dict[str, Any]:
    """Parse JSON that may be wrapped in markdown fences or surrounded by prose.

    Gateways differ: some honour ``response_format``, others return a fenced code
    block or a sentence of preamble before the object. Be tolerant here so a
    good answer is not thrown away.
    """

    text = _FENCE_RE.sub("", (content or "").strip())
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("provider did not return a JSON object")
    return parsed


class LLMProvider(Protocol):
    name: str

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        """Return a parsed JSON object, or raise :class:`ProviderError`."""


class OpenAIProvider:
    """OpenAI-compatible chat provider (also works against compatible gateways)."""

    name = "openai"

    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise ProviderError("no provider API key configured")
        self._settings = settings
        self._model = settings.openai_model
        self._timeout = settings.llm_timeout_seconds
        self._retries = max(0, settings.llm_max_retries)

    def _client(self, settings: Settings | None = None):
        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - depends on install
            raise ProviderError(f"openai SDK unavailable: {exc}") from exc
        active = settings or self._settings
        kwargs: dict[str, Any] = {
            "api_key": active.openai_api_key,
            "timeout": self._timeout,
            "max_retries": 0,  # retries are bounded by complete_json, not multiplied by the SDK
        }
        if active.openai_base_url:
            kwargs["base_url"] = active.openai_base_url
        return OpenAI(**kwargs)

    def _chat(self, client, system: str, user: str, *, json_mode: bool) -> str:
        request: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        }
        if json_mode:
            request["response_format"] = {"type": "json_object"}
        response = client.chat.completions.create(**request)
        return response.choices[0].message.content or ""

    @staticmethod
    def _json_mode_unsupported(exc: Exception) -> bool:
        message = str(exc).lower()
        return any(hint in message for hint in _UNSUPPORTED_JSON_HINTS)

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        if self._settings.local_only:
            raise ProviderError("External AI is disabled by local-only mode")
        validate_destination(self._settings.openai_base_url, self._settings.ai_allowed_hosts)
        system = redact(system, [self._settings.openai_api_key])
        user = redact(user, [self._settings.openai_api_key])
        client = self._client()
        last_exc: Exception | None = None
        json_mode = True
        attempts = 0
        while attempts <= self._retries:
            attempts += 1
            try:
                return _extract_json(self._chat(client, system, user, json_mode=json_mode))
            except json.JSONDecodeError as exc:
                last_exc = exc
                log.warning("provider returned unparseable JSON", extra={"event": "llm_parse"})
            except Exception as exc:  # noqa: BLE001 - provider errors are opaque
                last_exc = exc
                if json_mode and self._json_mode_unsupported(exc):
                    # Gateway (e.g. OpenRouter) rejects response_format: retry once
                    # without it rather than giving up.
                    log.info(
                        "gateway rejected JSON mode; retrying without response_format",
                        extra={"event": "llm_json_mode_fallback"},
                    )
                    json_mode = False
                    attempts -= 1
                    continue
                log.warning(
                    "provider request failed",
                    extra={"event": "llm_request", "tool": type(exc).__name__},
                )
        raise ProviderError(
            f"provider request failed after {attempts} attempt(s)",
            detail=type(last_exc).__name__ if last_exc else None,
        )

    def complete_chat(self, system: str, messages: list[dict[str, str]]) -> str:
        if self._settings.local_only:
            raise ProviderError("External AI is disabled by local-only mode")
        validate_destination(self._settings.openai_base_url, self._settings.ai_allowed_hosts)
        safe_system = redact(system, [self._settings.openai_api_key])
        safe_messages = [
            {
                "role": message["role"],
                "content": redact(message["content"], [self._settings.openai_api_key]),
            }
            for message in messages
        ]
        client = self._client()
        try:
            response = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": safe_system},
                    *safe_messages,
                ],
                temperature=0.3,
                max_completion_tokens=700,
            )
        except Exception as exc:  # noqa: BLE001 - provider errors are opaque
            log.warning(
                "assistant provider request failed",
                extra={"event": "assistant_request", "tool": type(exc).__name__},
            )
            raise ProviderError(
                "assistant provider request failed",
                detail=type(exc).__name__,
            ) from exc
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("assistant provider returned an empty response")
        return redact(content, [self._settings.openai_api_key])


def build_provider(settings: Settings) -> LLMProvider | None:
    """Return a provider when configured, else ``None`` (caller uses mock)."""

    if settings.llm_configured:
        return OpenAIProvider(settings)
    return None
