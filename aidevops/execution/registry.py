"""Tool registry: typed, allowlisted operations the executor may run.

Each tool has a Pydantic argument model, a declared execution kind, and a
handler. Adding a tool requires editing this file — there is no path by which an
LLM or HTTP caller can introduce a new command.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
import shutil
import tempfile
import shlex
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..errors import BlockedError, NotFoundError
from ..models import ExecutionStatus, ProjectProfile, ProjectType
from ..generator.validators import validate_dockerfile
from .policy import ExecutionContext, check_approval, is_docker_available


# --------------------------------------------------------------------------- #
# Argument models
# --------------------------------------------------------------------------- #
class ListWorkspaceArgs(BaseModel):
    pass


class DockerfileLintArgs(BaseModel):
    path: str = Field(default="Dockerfile", description="Artifact path inside the workspace")


class ContainerArgs(BaseModel):
    pass


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
@dataclass
class ToolResult:
    status: ExecutionStatus
    output: str = ""
    exit_code: int | None = None
    reason: str | None = None
    container: bool = False


@dataclass
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    kind: Literal["read_only", "container"]
    requires_approval: bool
    handler: Callable[[BaseModel, ExecutionContext], ToolResult]
    limits: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #
def _guard(workspace: Path, rel: str) -> Path:
    rel = rel.replace("\\", "/").lstrip("/")
    if ".." in Path(rel).parts:
        raise NotFoundError(f"path escapes workspace: {rel}")
    target = (workspace / rel).resolve()
    if workspace.resolve() != target and workspace.resolve() not in target.parents:
        raise NotFoundError(f"path escapes workspace: {rel}")
    if not target.is_file():
        raise NotFoundError(f"file not found in workspace: {rel}")
    return target


def _list_workspace(args: ListWorkspaceArgs, ctx: ExecutionContext) -> ToolResult:
    if not ctx.workspace.exists():
        return ToolResult(status=ExecutionStatus.OK, output="(workspace is empty)")
    files = sorted(p.relative_to(ctx.workspace).as_posix() for p in ctx.workspace.rglob("*") if p.is_file())
    return ToolResult(status=ExecutionStatus.OK, output="\n".join(files), exit_code=0)


def _dockerfile_lint(args: DockerfileLintArgs, ctx: ExecutionContext) -> ToolResult:
    target = _guard(ctx.workspace, args.path)
    content = target.read_text(encoding="utf-8", errors="replace")
    issues = validate_dockerfile(content, has_dockerignore=True)
    if not issues:
        return ToolResult(status=ExecutionStatus.OK, output="no issues found", exit_code=0)
    lines = [f"[{i.severity}] {i.code}: {i.message}" for i in issues]
    has_error = any(i.severity == "error" for i in issues)
    return ToolResult(
        status=ExecutionStatus.ERROR if has_error else ExecutionStatus.OK,
        output="\n".join(lines),
        exit_code=1 if has_error else 0,
    )


#: Fixed, allowlisted commands owned by this file — never derived from LLM
#: output. Python/Node images do not ship a test runner, so those templates
#: install dependencies first (the only reason a test run needs network).
TEST_COMMANDS: dict[ProjectType, list[str]] = {
    ProjectType.PYTHON: [
        "sh",
        "-c",
        "set -e; if [ -f requirements.txt ]; then pip install -q --disable-pip-version-check -r requirements.txt; "
        "elif [ -f pyproject.toml ]; then pip install -q .; fi; "
        "pip install -q --disable-pip-version-check pytest; "
        "exec python -m pytest -q -p no:cacheprovider",
    ],
    ProjectType.NODE: [
        "sh",
        "-c",
        "set -e; if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; "
        "else npm install --no-audit --no-fund; fi; exec npm test --silent",
    ],
    ProjectType.JAVA_MAVEN: ["mvn", "-B", "test"],
    ProjectType.JAVA_GRADLE: ["./gradlew", "--no-daemon", "test"],
    ProjectType.GO: ["go", "test", "./..."],
    ProjectType.RUST: ["cargo", "test", "--quiet"],
}

PROJECT_IMAGE: dict[ProjectType, str] = {
    ProjectType.PYTHON: "python:3.12-slim",
    ProjectType.NODE: "node:20-slim",
    ProjectType.JAVA_MAVEN: "maven:3.9-eclipse-temurin-21",
    ProjectType.JAVA_GRADLE: "eclipse-temurin:21-jdk",
    ProjectType.GO: "golang:1.22",
    ProjectType.RUST: "rust:1.79",
}


def _container_test(args: ContainerArgs, ctx: ExecutionContext) -> ToolResult:
    from .runner import run_container

    profile = ctx.profile
    ptype = profile.project_type if isinstance(profile, ProjectProfile) else ProjectType.UNKNOWN
    command = TEST_COMMANDS.get(ptype)
    if command is None:
        return ToolResult(
            status=ExecutionStatus.BLOCKED,
            reason="no known test command for the detected project type",
        )
    # Tests live in the *source* repository, not in the generated-artifact
    # workspace. Mount it read-only so a test run cannot modify the project.
    source = ctx.source_path or ctx.workspace
    if not Path(source).is_dir():
        return ToolResult(
            status=ExecutionStatus.BLOCKED,
            reason="the analyzed repository is no longer available; create a new job",
        )
    image = PROJECT_IMAGE.get(ptype, ctx.settings.container_image)
    from ..analyzer.analyzer import _collect_files
    files, _, truncated = _collect_files(Path(source), ctx.settings)
    if truncated:
        return ToolResult(ExecutionStatus.BLOCKED, reason="source exceeds snapshot file/depth limits")
    # Never expose host credentials in the source tree to dependency scripts.
    with tempfile.TemporaryDirectory(prefix="aidevops-test-") as temp:
        snapshot = Path(temp)
        total = 0
        for rel in files:
            original = Path(source) / rel
            if original.is_symlink() or not original.resolve().is_relative_to(Path(source).resolve()):
                return ToolResult(ExecutionStatus.BLOCKED, reason="source changed during snapshot")
            total += original.stat().st_size
            if total > ctx.settings.max_upload_bytes * 4:
                return ToolResult(ExecutionStatus.BLOCKED, reason="source exceeds snapshot size limit")
            target = snapshot / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
        # Build tools need a writable project tree; only the disposable in-container
        # copy is writable. The sanitized host snapshot stays read-only.
        command = ["sh", "-c", "set -e; mkdir -p /tmp/project; cp -R /workspace/. /tmp/project/; "
                   "cd /tmp/project; exec " + shlex.join(command)]
        return run_container(
            image=image, command=command, ctx=ctx, mount=snapshot,
            network="bridge", read_only=True,
        )


def _container_build(args: ContainerArgs, ctx: ExecutionContext) -> ToolResult:
    return ToolResult(ExecutionStatus.BLOCKED,
        reason="Use Build & open your app: image builds require a reviewed source snapshot and its fingerprint.")


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
_REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> None:
    _REGISTRY[spec.name] = spec


def get_tool(name: str) -> ToolSpec:
    spec = _REGISTRY.get(name)
    if spec is None:
        raise NotFoundError(f"unknown tool '{name}'; only allowlisted tools may run")
    return spec


def all_tools() -> list[ToolSpec]:
    return list(_REGISTRY.values())


register(
    ToolSpec(
        name="list_workspace",
        description="List files in the job's generated workspace.",
        args_model=ListWorkspaceArgs,
        kind="read_only",
        requires_approval=False,
        handler=_list_workspace,
        limits={"timeout_seconds": 10},
    )
)
register(
    ToolSpec(
        name="dockerfile_lint",
        description="Static lint of a generated Dockerfile (no execution).",
        args_model=DockerfileLintArgs,
        kind="read_only",
        requires_approval=False,
        handler=_dockerfile_lint,
        limits={"timeout_seconds": 10},
    )
)
register(
    ToolSpec(
        name="container_test",
        description="Run the project's test command inside an isolated container.",
        args_model=ContainerArgs,
        kind="container",
        requires_approval=False,
        handler=_container_test,
        limits={"timeout_seconds": 300, "network": "bridge (dependency install only)", "mount": "source repo, read-only"},
    )
)
register(
    ToolSpec(
        name="container_build_image",
        description="Build the generated Dockerfile inside a container (approval required).",
        args_model=ContainerArgs,
        kind="container",
        requires_approval=True,
        handler=_container_build,
        limits={"timeout_seconds": 600},
    )
)


def authorize(name: str, *, approved: bool) -> ToolSpec:
    """Resolve and authorize a tool, raising on unknown tools or missing approval."""

    spec = get_tool(name)
    check_approval(spec.requires_approval, approved, name)
    if spec.kind == "container" and not is_docker_available():
        raise BlockedError(
            f"tool '{name}' requires container isolation, but the Docker daemon is not available",
            detail="start Docker, or set AIDEVOPS_EXEC_BACKEND to control this behaviour",
        )
    return spec
