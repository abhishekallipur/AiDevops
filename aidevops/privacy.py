"""Shared outbound privacy boundary. Heuristic redaction, never a secrecy proof."""
import re
from urllib.parse import urlsplit

from .errors import PolicyError

PATTERNS = [
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", "[REDACTED PRIVATE KEY]"),
    (r"(?i)(https?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@"),
    (r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", "[REDACTED KEY]"),
    (r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{16,})\b", "[REDACTED TOKEN]"),
    (r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED TOKEN]"),
    (r"(?i)\b(password|passwd|api[_-]?key|secret|access[_-]?token|authorization)\s*[:=]\s*[\"']?[^\s\"',;}]+", r"\1=[REDACTED]"),
    (r"[A-Za-z]:[\\/][^\n\r\"<>]+", "[LOCAL PATH]"),
    (r"/(?:home|Users|root|mnt|var|tmp|etc)/[^\s\"',]+", "[LOCAL PATH]"),
]


def redact(text: str, secrets=()) -> str:
    for value in secrets:
        if value:
            text = text.replace(value, "[REDACTED]")
    for pattern, replacement in PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.DOTALL if "PRIVATE KEY" in pattern else 0)
    if "-----BEGIN" in text and "PRIVATE KEY" in text:
        raise PolicyError("Incomplete private key detected; request blocked")
    return text


def validate_destination(base_url: str | None, allowed_hosts: tuple[str, ...]) -> None:
    parsed = urlsplit(base_url or "https://api.openai.com/v1")
    if (parsed.scheme != "https" or parsed.username or parsed.password
            or parsed.hostname not in allowed_hosts or parsed.port not in (None, 443)):
        raise PolicyError("AI destination is not an approved HTTPS provider")
