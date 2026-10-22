"""Static repository analysis.

Guarantees:

* Project code is **never executed** during analysis.
* Symlinks are never followed, so a link cannot escape the selected root.
* Sensitive files (SSH keys, cloud credentials, ``.env``) are skipped and
  reported as a warning rather than read.
* Traversal is bounded by depth, file count, and per-file size so a hostile
  repository cannot exhaust memory or time.

Every finding carries the path that produced it. When evidence is missing the
analyzer reports ``unknown`` instead of guessing.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..config import Settings
from ..logging_config import get_logger
from ..models import Evidence, ProjectProfile, ProjectType

log = get_logger("aidevops.analyzer")

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "dist",
    "build",
    "target",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".idea",
    ".next",
    ".nuxt",
    "coverage",
}

#: Directories that commonly hold credentials; never traversed.
SENSITIVE_DIRS = {".ssh", ".aws", ".gnupg", ".docker", ".kube"}

SENSITIVE_FILE_NAMES = {
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials",
    "credentials.json",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
}

SENSITIVE_SUFFIXES = {".pem", ".key", ".pfx", ".p12", ".jks", ".keystore", ".ppk"}

#: Extensions safe to read as text for evidence gathering.
TEXT_SUFFIXES = {
    ".py",
    ".pyi",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".json",
    ".toml",
    ".cfg",
    ".ini",
    ".txt",
    ".md",
    ".rst",
    ".yaml",
    ".yml",
    ".java",
    ".kt",
    ".gradle",
    ".xml",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".cs",
    ".sh",
    ".bash",
    ".dockerfile",
    ".tf",
    ".env",
}

MANIFEST_FILES = {
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "setup.cfg",
    "Pipfile",
    "poetry.lock",
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "go.mod",
    "Cargo.toml",
}

ENTRY_POINT_NAMES = {
    "main.py",
    "app.py",
    "manage.py",
    "wsgi.py",
    "asgi.py",
    "server.py",
    "run.py",
    "cli.py",
    "index.js",
    "index.ts",
    "server.js",
    "main.js",
    "app.js",
    "main.go",
    "main.rs",
    "Main.java",
    "Application.java",
}

CI_MARKERS = {
    ".gitlab-ci.yml",
    "Jenkinsfile",
    "azure-pipelines.yml",
    ".travis.yml",
    ".circleci/config.yml",
    "bitbucket-pipelines.yml",
}

PORT_PATTERNS = [
    re.compile(r"EXPOSE\s+(\d{2,5})"),
    re.compile(r"--port[= ](\d{2,5})"),
    re.compile(r"\bPORT\b\s*[:=]\s*[\"']?(\d{2,5})"),
    re.compile(r"\bport\s*[:=]\s*[\"']?(\d{2,5})"),
    re.compile(r"listen\(\s*(\d{2,5})"),
    re.compile(r"\.listen\(\s*(\d{2,5})"),
    re.compile(r"Replace\(.*?\"?(\d{4,5})\"?", re.IGNORECASE),
]

PY_FRAMEWORKS = {
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "streamlit": "Streamlit",
    "aiohttp": "aiohttp",
    "starlette": "Starlette",
}
NODE_FRAMEWORKS = {
    "express": "Express",
    "@nestjs/core": "NestJS",
    "next": "Next.js",
    "react": "React",
    "vue": "Vue",
    "fastify": "Fastify",
    "koa": "Koa",
}


def is_sensitive_path(rel_path: str) -> bool:
    """True when a path must not be read (secret material)."""

    p = Path(rel_path)
    lowered_parts = [part.lower() for part in p.parts]
    if any(part in SENSITIVE_DIRS for part in lowered_parts):
        return True
    name = p.name.lower()
    # Allow documented placeholders such as .env.example / secrets.sample.
    if name.endswith((".example", ".sample", ".template", ".dist")):
        return False
    if name in SENSITIVE_FILE_NAMES:
        return True
    if name.startswith(".env.") or (name.startswith(".env") and name != ".env.example"):
        return True
    return p.suffix.lower() in SENSITIVE_SUFFIXES


def _has_text_suffix(name: str) -> bool:
    suffix = Path(name).suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return True
    return Path(name).name in {"Dockerfile", ".dockerignore", "Makefile"}


def _collect_files(
    root: Path, settings: Settings
) -> tuple[list[str], list[str], bool]:
    """Return (relative file paths, warnings, truncated). Never follows symlinks."""

    files: list[str] = []
    warnings: list[str] = []
    truncated = False
    skipped_sensitive = 0

    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > settings.analyzer_max_depth:
            warnings.append(f"max depth {settings.analyzer_max_depth} reached at {current}")
            truncated = True
            continue
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            warnings.append(f"cannot read directory {current}: {exc.strerror or exc}")
            continue

        for entry in entries:
            try:
                is_link = entry.is_symlink()
            except OSError:
                continue
            if is_link:
                warnings.append(f"skipped symlink (not followed): {entry.path}")
                continue
            rel = os.path.relpath(entry.path, root).replace(os.sep, "/")
            if is_sensitive_path(rel):
                skipped_sensitive += 1
                continue
            try:
                if entry.is_dir():
                    if entry.name in SKIP_DIRS:
                        continue
                    stack.append((Path(entry.path), depth + 1))
                elif entry.is_file():
                    files.append(rel)
            except OSError:
                continue
        if len(files) > settings.analyzer_max_files:
            files = files[: settings.analyzer_max_files]
            warnings.append(
                f"file limit {settings.analyzer_max_files} reached; analysis truncated"
            )
            truncated = True
            break

    if skipped_sensitive:
        warnings.append(f"skipped {skipped_sensitive} sensitive file(s)/dir(s)")
    return sorted(files), warnings, truncated


def _read_text(path: Path, max_bytes: int) -> str | None:
    try:
        if path.stat().st_size > max_bytes:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:1024]:  # binary heuristic
        return None
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:  # pragma: no cover - decode guarded above
        return None


def _parse_dependencies(manifest: str, content: str) -> list[str]:
    deps: list[str] = []
    if manifest == "requirements.txt":
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            deps.append(re.split(r"[<>=!\[;]", line)[0].strip())
    elif manifest == "package.json":
        import json

        try:
            data = json.loads(content)
        except (ValueError, TypeError):
            return []
        if not isinstance(data, dict):
            return []
        for section in ("dependencies", "devDependencies"):
            values = data.get(section)
            if isinstance(values, dict):
                deps.extend(values.keys())
    elif manifest in {"pom.xml", "build.gradle", "build.gradle.kts"}:
        deps.extend(re.findall(r"<artifactId>([^<]+)</artifactId>", content))
        deps.extend(re.findall(r"implementation\s+['\"]([^'\"]+)['\"]", content))
    elif manifest == "go.mod":
        deps.extend(re.findall(r"^\s*([\w./-]+)\s+v\d", content, re.MULTILINE))
    return [d for d in deps if d][:80]


def _detect_type(files: list[str]) -> tuple[ProjectType, list[Evidence], list[str]]:
    present = set(files)
    evidence: list[Evidence] = []
    manifests: list[str] = []

    def add(path: str, reason: str) -> None:
        evidence.append(Evidence(path=path, reason=reason))

    scores: dict[ProjectType, int] = {}

    def bump(ptype: ProjectType, amount: int) -> None:
        scores[ptype] = scores.get(ptype, 0) + amount

    for manifest in sorted(MANIFEST_FILES):
        if manifest in present:
            manifests.append(manifest)
            if manifest in {"pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "Pipfile"}:
                bump(ProjectType.PYTHON, 3)
                add(manifest, "python dependency manifest")
            elif manifest in {"package.json"}:
                bump(ProjectType.NODE, 3)
                add(manifest, "node dependency manifest")
            elif manifest == "pom.xml":
                bump(ProjectType.JAVA_MAVEN, 4)
                add(manifest, "maven build descriptor")
            elif manifest in {"build.gradle", "build.gradle.kts"}:
                bump(ProjectType.JAVA_GRADLE, 4)
                add(manifest, "gradle build descriptor")
            elif manifest == "go.mod":
                bump(ProjectType.GO, 4)
                add(manifest, "go module descriptor")
            elif manifest == "Cargo.toml":
                bump(ProjectType.RUST, 4)
                add(manifest, "rust crate descriptor")

    if not scores:
        return ProjectType.UNKNOWN, evidence, manifests

    best = max(scores.items(), key=lambda item: item[1])[0]
    return best, evidence, manifests


def analyze_path(root: Path | str, settings: Settings) -> ProjectProfile:
    """Analyze a directory and return evidence-based findings."""

    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"{root} is not a directory")

    files, warnings, truncated = _collect_files(root, settings)
    profile = ProjectProfile(root=str(root), warnings=list(warnings), truncated=truncated)
    profile.files_scanned = len(files)
    present = set(files)

    project_type, evidence, manifests = _detect_type(files)
    profile.project_type = project_type
    profile.evidence.extend(evidence)
    profile.dependency_manifests = manifests

    language_map = {
        ProjectType.PYTHON: "Python",
        ProjectType.NODE: "JavaScript/TypeScript",
        ProjectType.JAVA_MAVEN: "Java",
        ProjectType.JAVA_GRADLE: "Java",
        ProjectType.GO: "Go",
        ProjectType.RUST: "Rust",
    }
    profile.language = language_map.get(project_type)

    # Entry points ---------------------------------------------------------
    for name in sorted(ENTRY_POINT_NAMES):
        for path in files:
            if Path(path).name == name:
                profile.entry_points.append(path)
                profile.evidence.append(Evidence(path=path, reason="conventional entry point"))

    # Tests ----------------------------------------------------------------
    test_dirs = {"tests", "test", "spec", "__tests__"}
    for path in files:
        parts = Path(path).parts
        name = Path(path).name
        if any(part in test_dirs for part in parts):
            profile.test_locations.append(path)
        elif name.startswith("test_") and name.endswith(".py"):
            profile.test_locations.append(path)
        elif name.endswith(("_test.py", ".test.js", ".spec.js", ".test.ts", ".spec.ts")):
            profile.test_locations.append(path)
        elif name.endswith(("Test.java", "Tests.java")):
            profile.test_locations.append(path)
    profile.test_locations = profile.test_locations[:50]

    # Docker / CI ----------------------------------------------------------
    for path in files:
        name = Path(path).name
        if name == "Dockerfile" or name.startswith("Dockerfile.") or name.endswith(".dockerfile"):
            profile.existing_dockerfiles.append(path)
        if name in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}:
            profile.existing_dockerfiles.append(path)
    for path in files:
        if path in CI_MARKERS or path.startswith(".github/workflows/"):
            profile.existing_ci_files.append(path)

    # Content scanning (bounded) ------------------------------------------
    framework = None
    ports: set[int] = set()
    dependencies: list[str] = []
    content_scanned = 0

    for path in files:
        if content_scanned >= 400:
            break
        if not _has_text_suffix(path):
            continue
        manifest_name = Path(path).name
        text = _read_text(root / path, settings.analyzer_max_file_bytes)
        if text is None:
            continue
        content_scanned += 1

        if manifest_name in MANIFEST_FILES:
            dependencies.extend(_parse_dependencies(manifest_name, text))

        for pattern in PORT_PATTERNS:
            for match in pattern.findall(text):
                try:
                    value = int(match)
                except (TypeError, ValueError):
                    continue
                if 1 <= value <= 65535:
                    ports.add(value)

        if project_type == ProjectType.PYTHON:
            for dep_key, label in PY_FRAMEWORKS.items():
                if framework is None and re.search(rf"\b{dep_key}\b", text, re.IGNORECASE):
                    framework = label
        elif project_type == ProjectType.NODE:
            for dep_key, label in NODE_FRAMEWORKS.items():
                if framework is None and f'"{dep_key}"' in text:
                    framework = label
        elif project_type in {ProjectType.JAVA_MAVEN, ProjectType.JAVA_GRADLE}:
            if framework is None and re.search(r"spring-boot", text, re.IGNORECASE):
                framework = "Spring Boot"

        if project_type in {ProjectType.PYTHON, ProjectType.UNKNOWN}:
            if re.search(r'if\s+__name__\s*==\s*["\']__main__["\']', text) and path not in profile.entry_points:
                profile.entry_points.append(path)
                profile.evidence.append(
                    Evidence(path=path, reason="__main__ guard")
                )

    if project_type == ProjectType.PYTHON and framework is None:
        lowered = " ".join(dependencies).lower()
        for dep_key, label in PY_FRAMEWORKS.items():
            if dep_key in lowered:
                framework = label
                break

    profile.framework = framework
    profile.dependencies = sorted(set(d.strip() for d in dependencies if d.strip()))[:80]
    profile.entry_points = sorted(set(profile.entry_points))[:20]
    profile.declared_ports = sorted(ports)[:10]

    # Confidence -----------------------------------------------------------
    confidence = 0.3 if project_type != ProjectType.UNKNOWN else 0.1
    if manifests:
        confidence += 0.25
    if profile.entry_points:
        confidence += 0.15
    if profile.test_locations:
        confidence += 0.1
    if profile.declared_ports:
        confidence += 0.1
    if profile.framework:
        confidence += 0.1
    if project_type == ProjectType.UNKNOWN:
        confidence = min(confidence, 0.2)
        profile.warnings.append(
            "no recognized dependency manifest found; project type is unknown"
        )
    profile.confidence = round(min(confidence, 0.98), 2)

    log.info(
        "analysis complete",
        extra={"event": "analyze", "tool": "analyzer"},
    )
    return profile
