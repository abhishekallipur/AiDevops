"""Bounded tool execution.

Every call is recorded with the tool name, normalized arguments, start/end
time, exit code, and truncated output. Shell interpretation is never used
(``shell=False`` with a fixed argv), container tools run only when a daemon is
available, and container mounts are limited to the job's own workspace — never
the Docker socket or host credentials.
"""

from __future__ import annotations

import subprocess
import threading
import uuid
from copy import copy
from pathlib import Path

from pydantic import ValidationError as PydanticValidationError

from ..errors import NotFoundError, PolicyError, ValidationError
from ..logging_config import get_logger
from ..models import ExecutionRecord, ExecutionStatus, utcnow
from .policy import ExecutionContext, check_approval, is_docker_available
from .registry import ToolResult, get_tool

log = get_logger("aidevops.execution.runner")


def _truncate(text: str, max_bytes: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text, False
    return encoded[:max_bytes].decode("utf-8", errors="replace"), True


def _subprocess(
    argv: list[str], *, cwd: Path, timeout: int, max_output: int
) -> tuple[int | None, str, bool, str | None]:
    """Run a fixed argv. Returns (exit_code, output, truncated, blocked_reason)."""

    try:
        proc = subprocess.Popen(  # fixed argv, no shell
            argv,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except FileNotFoundError:
        return None, "", False, f"executable not found: {argv[0]}"
    except OSError as exc:
        return None, "", False, f"could not start process: {type(exc).__name__}"

    captured = bytearray()
    truncated = False
    def drain():
        nonlocal truncated
        with proc.stdout:
            while chunk := proc.stdout.read(8192):
                available = max(0, max_output - len(captured))
                captured.extend(chunk[:available])
                truncated = truncated or len(chunk) > available
    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        reader.join(timeout=2)
        return None, f"command exceeded {timeout}s timeout", truncated, "timeout"
    reader.join(timeout=2)
    output = bytes(captured).decode("utf-8", errors="replace")
    return proc.returncode, output, truncated, None


def run_container(
    image: str,
    command: list[str],
    ctx: ExecutionContext,
    *,
    mount: Path | None = None,
    network: str = "none",
    read_only: bool = False,
) -> ToolResult:
    """Run a fixed argv inside a throwaway container.

    Only the job's own directories are ever mounted — never the Docker socket,
    ``$HOME``, or any other host path. ``network`` is ``none`` unless a tool
    genuinely needs to fetch dependencies, in which case it is stated explicitly
    by that tool.
    """

    target = Path(mount) if mount is not None else ctx.workspace
    volume = f"{target}:/workspace" + (":ro" if read_only else "")
    container_name = "aidevops-" + uuid.uuid4().hex
    argv = [
        "docker",
        "run",
        "--rm",
        "--name", container_name,
        "--memory", "1g",
        "--cpus", "2",
        "--pids-limit", "256",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--network",
        network,
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-e",
        "PYTHONUNBUFFERED=1",
        "-v",
        volume,
        "-w",
        "/workspace",
        image,
        *command,
    ]
    code, output, truncated, blocked = _subprocess(
        argv,
        cwd=target,
        timeout=ctx.timeout_seconds,
        max_output=ctx.settings.exec_max_output_bytes,
    )
    if blocked == "timeout":
        _subprocess(
            ["docker", "rm", "--force", container_name], cwd=target,
            timeout=10, max_output=1000,
        )
        return ToolResult(ExecutionStatus.TIMEOUT, output, None, "container run timed out", True)
    if blocked:
        return ToolResult(ExecutionStatus.BLOCKED, output, None, blocked, True)
    status = ExecutionStatus.OK if code == 0 else ExecutionStatus.ERROR
    if truncated:
        output += "\n… (output truncated)"
    return ToolResult(status, output, code, None, True)


def run_container_build(ctx: ExecutionContext) -> ToolResult:
    argv = ["docker", "build", "--file", "Dockerfile", "--tag", "aidevops-unverified:local", "."]
    code, output, truncated, blocked = _subprocess(
        argv, cwd=ctx.workspace, timeout=ctx.timeout_seconds, max_output=ctx.settings.exec_max_output_bytes
    )
    if blocked == "timeout":
        return ToolResult(ExecutionStatus.TIMEOUT, output, None, "image build timed out", True)
    if blocked:
        return ToolResult(ExecutionStatus.BLOCKED, output, None, blocked, True)
    if truncated:
        output += "\n… (output truncated)"
    status = ExecutionStatus.OK if code == 0 else ExecutionStatus.ERROR
    return ToolResult(status, output, code, None, True)


def _backend_allows_container(settings) -> tuple[bool, str | None]:
    backend = (settings.exec_backend or "auto").lower()
    if backend == "disabled":
        return False, "container execution is disabled (AIDEVOPS_EXEC_BACKEND=disabled)"
    if not is_docker_available():
        return False, "Docker daemon is not available; refusing to run untrusted code on the host"
    return True, None


def run_tool(
    name: str,
    raw_args: dict | None,
    ctx: ExecutionContext,
    *,
    approved: bool = False,
) -> ExecutionRecord:
    """Validate, authorize, execute, and record a single tool invocation."""

    started = utcnow()
    try:
        spec = get_tool(name)
    except NotFoundError as exc:
        raise PolicyError(
            f"unknown tool '{name}': only allowlisted tools may run",
            detail="see docs/TOOL_REGISTRY.md for the full list",
        ) from exc

    check_approval(spec.requires_approval, approved, name)
    ctx = copy(ctx)
    ctx.timeout_seconds = min(
        ctx.settings.exec_timeout_seconds,
        spec.limits.get("timeout_seconds", ctx.settings.exec_timeout_seconds),
    )

    try:
        args = spec.args_model.model_validate(raw_args or {})
    except PydanticValidationError as exc:
        raise ValidationError(f"invalid arguments for tool '{name}'", detail=str(exc.errors()[:1])) from exc

    record_args = args.model_dump()

    if spec.kind == "container":
        allowed, reason = _backend_allows_container(ctx.settings)
        if not allowed:
            log.info("container tool blocked", extra={"event": "blocked", "tool": name})
            return ExecutionRecord(
                tool=name,
                args=record_args,
                status=ExecutionStatus.BLOCKED,
                reason=reason,
                started_at=started,
                finished_at=utcnow(),
                container=True,
            )

    try:
        result = spec.handler(args, ctx)
    except (NotFoundError, PolicyError):
        raise
    except Exception as exc:  # noqa: BLE001 - tool failures are recorded, not fatal
        log.warning(
            "tool raised", extra={"event": "tool_error", "tool": name, "exc": type(exc).__name__}
        )
        result = ToolResult(
            status=ExecutionStatus.ERROR,
            output="",
            reason=f"tool raised {type(exc).__name__}",
        )

    output, truncated = _truncate(result.output, ctx.settings.exec_max_output_bytes)
    log.info("tool executed", extra={"event": "execute", "tool": name})
    return ExecutionRecord(
        tool=name,
        args=record_args,
        status=result.status,
        exit_code=result.exit_code,
        started_at=started,
        finished_at=utcnow(),
        output=output,
        truncated=truncated,
        reason=result.reason,
        container=result.container,
    )


__all__ = ["run_tool", "run_container", "run_container_build"]
