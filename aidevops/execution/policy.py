"""Command policy: what may run, and under which conditions.

The executor only ever runs *registered tools*. A command string produced by the
LLM (for example in ``plan.steps[].command``) is never passed to a shell — it is
advisory text for the operator. Tools declare their own argv, and this module
decides whether the environment permits them to run at all.
"""

from __future__ import annotations

import functools
import subprocess
from pathlib import Path

from ..errors import PolicyError
from ..logging_config import get_logger

log = get_logger("aidevops.execution.policy")


@functools.lru_cache(maxsize=1)
def is_docker_available() -> bool:
    """True only when the Docker CLI exists *and* the daemon responds."""

    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (FileNotFoundError, OSError):
        return False
    except subprocess.TimeoutExpired:
        log.warning("docker info timed out", extra={"event": "docker_check"})
        return False
    available = proc.returncode == 0 and bool(proc.stdout.strip())
    if not available:
        log.info("docker daemon unavailable; container tools will be blocked")
    return available


def reset_docker_cache() -> None:
    """Allow tests to re-probe the daemon."""

    is_docker_available.cache_clear()


class ExecutionContext:
    """Everything a tool is allowed to touch.

    Two distinct directories matter:

    * ``workspace`` — the job's generated-artifact directory (read/write).
    * ``source_path`` — the analyzed repository, used by test tools. It is
      mounted read-only so a test run can never modify the project.
    """

    def __init__(self, workspace: Path, settings, profile=None, source_path=None) -> None:
        self.workspace = Path(workspace)
        self.settings = settings
        self.profile = profile
        self.source_path = Path(source_path) if source_path else None
        self.timeout_seconds = settings.exec_timeout_seconds


def check_approval(requires_approval: bool, approved: bool, tool_name: str) -> None:
    if requires_approval and not approved:
        raise PolicyError(
            f"tool '{tool_name}' requires explicit operator approval",
            detail="re-submit with approved=true after reviewing the artifacts",
        )
