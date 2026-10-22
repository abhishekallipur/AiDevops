"""Artifact validation and secret scanning.

Validation is deliberately conservative: it inspects generated text for
accidentally embedded credentials and for Dockerfile flaws that are common in
generated files (running as root, unpinned base images, missing instructions).
Only ``error`` severity blocks an artifact; ``warning``/``info`` are advisory.
"""

from __future__ import annotations

import re

from ..models import GeneratedArtifact, ValidationIssue, ValidationReport

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("SEC_AWS_KEY", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("SEC_PRIVATE_KEY", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("SEC_PASSWORD", re.compile(r"(?i)\bpassword\b\s*[:=]\s*['\"][^'\"]{3,}['\"]")),
    ("SEC_SECRET", re.compile(r"(?i)\bsecret\b\s*[:=]\s*['\"][^'\"]{6,}['\"]")),
    ("SEC_API_KEY", re.compile(r"(?i)\bapi[_-]?key\b\s*[:=]\s*['\"][^'\"]{8,}['\"]")),
    ("SEC_TOKEN", re.compile(r"(?i)\btoken\b\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]")),
    ("SEC_OPENAI", re.compile(r"sk-[A-Za-z0-9]{20,}")),
]

# Placeholders are expected in generated scaffolds and are not secrets.
PLACEHOLDER_MARKERS = ("${", "$", "<", "your-", "changeme", "placeholder", "example", "todo", "xxx")


def scan_secrets(text: str, *, path: str = "artifact") -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for code, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            snippet = match.group(0).lower()
            if any(marker in snippet for marker in PLACEHOLDER_MARKERS):
                continue
            issues.append(
                ValidationIssue(
                    severity="error",
                    code=code,
                    message=f"possible hard-coded credential in {path} (value redacted)",
                )
            )
    return issues


def validate_dockerfile(content: str, *, has_dockerignore: bool = True) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    upper = content.upper()
    lines = [ln.strip() for ln in content.splitlines() if ln.strip() and not ln.strip().startswith("#")]

    if not re.search(r"(?im)^\s*FROM\s+\S+", content):
        issues.append(
            ValidationIssue(severity="error", code="DF001", message="Dockerfile has no FROM instruction")
        )

    from_lines = [ln for ln in lines if ln.upper().startswith("FROM")]
    for from_line in from_lines:
        parts = from_line.split()
        if len(parts) >= 2 and ":" not in parts[1] and parts[1].lower() != "scratch":
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="DF004",
                    message=f"base image '{parts[1]}' is not pinned to a tag (implicit :latest)",
                )
            )
        elif len(parts) >= 2 and parts[1].lower().endswith(":latest"):
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="DF004",
                    message=f"base image '{parts[1]}' uses the :latest tag",
                )
            )

    if "USER" not in upper:
        issues.append(
            ValidationIssue(
                severity="warning",
                code="DF002",
                message="no USER instruction; container would run as root",
            )
        )
    elif re.search(r"(?im)^\s*USER\s+(root|0)\s*$", content):
        issues.append(
            ValidationIssue(severity="warning", code="DF007", message="container runs as root")
        )

    if re.search(r"(?im)^\s*COPY\s+(--\S+\s+)*\.\s+\.", content) and not has_dockerignore:
        issues.append(
            ValidationIssue(
                severity="warning",
                code="DF003",
                message="COPY . . without a .dockerignore bloats the context and may copy secrets",
            )
        )

    if re.search(r"(?im)^\s*ADD\s+\S+", content):
        issues.append(
            ValidationIssue(
                severity="info",
                code="DF005",
                message="ADD is used; prefer COPY unless remote extraction is required",
            )
        )

    if "EXPOSE" not in upper:
        issues.append(
            ValidationIssue(
                severity="info",
                code="DF008",
                message="no EXPOSE instruction; confirm the application port",
            )
        )

    issues.extend(scan_secrets(content, path="Dockerfile"))
    return issues


def validate_dockerignore(content: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    entries = {ln.strip() for ln in content.splitlines() if ln.strip() and not ln.startswith("#")}
    if not any(e in entries for e in {".git", ".git/"}):
        issues.append(
            ValidationIssue(severity="warning", code="DI001", message=".dockerignore does not exclude .git")
        )
    if not any(e.startswith(".env") for e in entries):
        issues.append(
            ValidationIssue(
                severity="warning", code="DI002", message=".dockerignore does not exclude .env files"
            )
        )
    return issues


def validate_compose(content: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if "services:" not in content:
        issues.append(
            ValidationIssue(severity="error", code="DC001", message="compose file has no 'services:' key")
        )
    if "privileged: true" in content:
        issues.append(
            ValidationIssue(severity="error", code="DC002", message="compose enables privileged mode")
        )
    if re.search(r"/var/run/docker\.sock", content):
        issues.append(
            ValidationIssue(
                severity="error",
                code="DC003",
                message="compose mounts the Docker socket, which grants host control",
            )
        )
    issues.extend(scan_secrets(content, path="docker-compose.yml"))
    return issues


def validate_artifact(artifact: GeneratedArtifact, *, has_dockerignore: bool = True) -> ValidationReport:
    if artifact.kind == "Dockerfile":
        issues = validate_dockerfile(artifact.content, has_dockerignore=has_dockerignore)
    elif artifact.kind == ".dockerignore":
        issues = validate_dockerignore(artifact.content)
    elif artifact.kind == "docker-compose.yml":
        issues = validate_compose(artifact.content)
    else:
        issues = scan_secrets(artifact.content, path=artifact.path)

    if not artifact.content.strip():
        issues.append(
            ValidationIssue(severity="error", code="GEN001", message="artifact is empty")
        )

    passed = not any(i.severity == "error" for i in issues)
    return ValidationReport(artifact_path=artifact.path, passed=passed, issues=issues)
