"""Typed application errors with safe, structured payloads."""

from __future__ import annotations


class AIDevOpsError(Exception):
    """Base class. ``code`` is a stable machine-readable identifier."""

    code = "error"
    http_status = 400

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict[str, str]:
        payload = {"error": self.code, "message": self.message}
        if self.detail:
            payload["detail"] = self.detail
        return payload


class ValidationError(AIDevOpsError):
    code = "validation_error"


class NotFoundError(AIDevOpsError):
    code = "not_found"
    http_status = 404


class InvalidTransitionError(AIDevOpsError):
    code = "invalid_transition"
    http_status = 409


class PolicyError(AIDevOpsError):
    """A requested operation was refused by the command policy."""

    code = "policy_denied"
    http_status = 403


class BlockedError(AIDevOpsError):
    """The operation is legitimate but cannot run in this environment."""

    code = "blocked"
    http_status = 409


class UnsafeInputError(AIDevOpsError):
    """Input failed a safety check (path traversal, symlink escape, ...)."""

    code = "unsafe_input"
    http_status = 400


class ProviderError(AIDevOpsError):
    code = "provider_error"
    http_status = 502
