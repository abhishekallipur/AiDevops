from pathlib import Path

import pytest

from aidevops.config import Settings
from aidevops.errors import NotFoundError, PolicyError
from aidevops.execution import ExecutionContext, run_tool
from aidevops.models import ExecutionStatus


@pytest.fixture
def ctx(settings: Settings, tmp_path: Path) -> ExecutionContext:
    (tmp_path / "Dockerfile").write_text(
        "FROM python:3.12-slim\nUSER 10001\nEXPOSE 8000\n", encoding="utf-8"
    )
    return ExecutionContext(tmp_path, settings)


def test_unknown_tool_is_rejected(ctx: ExecutionContext):
    with pytest.raises(PolicyError):
        run_tool("rm -rf /", {}, ctx)


def test_approval_required_for_image_build(ctx: ExecutionContext):
    with pytest.raises(PolicyError):
        run_tool("container_build_image", {}, ctx)


def test_container_tool_blocked_when_disabled(ctx: ExecutionContext):
    record = run_tool("container_test", {}, ctx)
    assert record.status == ExecutionStatus.BLOCKED
    assert record.reason


def test_dockerfile_lint_runs_read_only(ctx: ExecutionContext):
    record = run_tool("dockerfile_lint", {"path": "Dockerfile"}, ctx)
    assert record.status == ExecutionStatus.OK
    assert record.exit_code == 0


def test_lint_rejects_path_escape(ctx: ExecutionContext):
    with pytest.raises(NotFoundError):
        run_tool("dockerfile_lint", {"path": "../outside"}, ctx)


def test_lint_flags_missing_non_root_user(settings: Settings, tmp_path: Path):
    (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    ctx = ExecutionContext(tmp_path, settings)
    record = run_tool("dockerfile_lint", {"path": "Dockerfile"}, ctx)
    assert "DF002" in record.output


def test_container_test_mounts_source_repo_read_only(
    settings: Settings, tmp_path: Path, monkeypatch
):
    """Regression: the test must run against the source repo, not the generated workspace."""

    from dataclasses import replace

    from aidevops.execution import runner as runner_mod
    from aidevops.execution.registry import ToolResult
    from aidevops.models import ProjectProfile, ProjectType

    workspace = tmp_path / "ws"
    workspace.mkdir()
    source = tmp_path / "src"
    source.mkdir()
    profile = ProjectProfile(root=str(source), project_type=ProjectType.PYTHON)

    captured: dict = {}

    def fake_run_container(image, command, ctx, **kwargs):
        captured.update({"image": image, "command": command, **kwargs})
        assert not (kwargs["mount"] / ".env").exists()
        assert (kwargs["mount"] / "app.py").read_text() == "print('safe')"
        return ToolResult(ExecutionStatus.OK, "1 passed", 0, None, True)

    monkeypatch.setattr(runner_mod, "is_docker_available", lambda: True)
    monkeypatch.setattr(runner_mod, "run_container", fake_run_container)

    ctx = ExecutionContext(
        workspace, replace(settings, exec_backend="auto"), profile, source_path=source
    )
    (source / ".env").write_text("SECRET=never-mount")
    (source / "app.py").write_text("print('safe')")
    record = run_tool("container_test", {}, ctx)

    assert record.status == ExecutionStatus.OK
    assert captured["mount"] != source
    assert "cp -R /workspace/." in captured["command"][2]
    assert captured["read_only"] is True


def test_list_workspace(ctx: ExecutionContext):
    record = run_tool("list_workspace", {}, ctx)
    assert record.status == ExecutionStatus.OK
    assert "Dockerfile" in record.output
