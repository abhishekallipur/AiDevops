from dataclasses import replace

import pytest

from aidevops.errors import PolicyError
from aidevops.models import ExecutionRecord, ExecutionStatus
from aidevops.services import pipeline


@pytest.mark.parametrize("status", list(ExecutionStatus))
def test_execution_outcome_requires_all_checks_ok(client, python_repo, monkeypatch, status):
    job_id = client.post("/api/jobs", json={"source_path": str(python_repo)}).json()["id"]
    client.post(f"/api/jobs/{job_id}/run")
    monkeypatch.setattr(pipeline, "run_tool", lambda name, *a, **kw: ExecutionRecord(
        tool=name, status=status if name == "container_test" else ExecutionStatus.OK,
    ))
    result = client.post(f"/api/jobs/{job_id}/execute", json={"approved": True}).json()
    assert result["state"] == ("SUCCEEDED" if status == ExecutionStatus.OK else "FAILED")
    assert client.get(f"/api/jobs/{job_id}").json()["state"] == result["state"]


def test_execution_policy_failure_is_persisted(client, python_repo, monkeypatch):
    job_id = client.post("/api/jobs", json={"source_path": str(python_repo)}).json()["id"]
    client.post(f"/api/jobs/{job_id}/run")
    def deny(*a, **kw):
        raise PolicyError("execution denied")
    monkeypatch.setattr(pipeline, "run_tool", deny)
    result = client.post(f"/api/jobs/{job_id}/execute", json={"approved": True}).json()
    assert result["state"] == "FAILED"
    assert "execution denied" in result["error"]


def test_tool_timeout_is_capped_without_mutating_context(settings, tmp_path, monkeypatch):
    from aidevops.execution import ExecutionContext, run_tool, runner
    from aidevops.execution.registry import ToolResult, get_tool
    ctx = ExecutionContext(tmp_path, replace(settings, exec_timeout_seconds=900))
    seen = []
    monkeypatch.setattr(get_tool("list_workspace"), "handler", lambda args, context: (
        seen.append(context.timeout_seconds) or ToolResult(ExecutionStatus.OK)
    ))
    run_tool("list_workspace", {}, ctx)
    assert seen == [10]
    assert ctx.timeout_seconds == 900


def test_secret_diagnostic_never_contains_match():
    from aidevops.generator.validators import scan_secrets
    value = "AKIA" + "Q" * 16
    issues = scan_secrets(value)
    assert issues
    assert value[:12] not in issues[0].message


def test_oversize_upload_rejected(client):
    client.app.state.settings = replace(client.app.state.settings, max_upload_bytes=10)
    response = client.post("/api/jobs/upload", files={"file": ("big.zip", b"x" * 11)})
    assert response.status_code == 400
    assert response.json()["error"] == "unsafe_input"


def test_subprocess_output_bounded_and_timeout(tmp_path):
    import sys
    from aidevops.execution.runner import _subprocess
    code, output, truncated, reason = _subprocess(
        [sys.executable, "-c", "print('x' * 200000)"],
        cwd=tmp_path, timeout=10, max_output=100,
    )
    assert code == 0 and len(output.encode()) == 100 and truncated and reason is None
    code, _, _, reason = _subprocess(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        cwd=tmp_path, timeout=0.1, max_output=100,
    )
    assert code is None and reason == "timeout"


def test_duplicate_transition_and_stale_cancelled_save_refused(store):
    from aidevops.models import JobRecord, JobState
    from aidevops.errors import InvalidTransitionError
    job = store.create(JobRecord())
    active = store.transition(job.id, JobState.ANALYZING)
    with pytest.raises(InvalidTransitionError):
        store.transition(job.id, JobState.ANALYZING)
    store.cancel(job.id)
    with pytest.raises(InvalidTransitionError):
        store.save(active)
    assert store.get(job.id).state == JobState.CANCELLED


@pytest.mark.parametrize("manifest", ['[]', '{"dependencies": []}', '{"devDependencies": "bad"}'])
def test_malformed_package_manifest_does_not_crash(settings, tmp_path, manifest):
    from aidevops.analyzer import analyze_path
    (tmp_path / "package.json").write_text(manifest)
    assert analyze_path(tmp_path, settings).dependencies == []


def test_package_sources_precede_install_and_ci_installs_pytest(settings, tmp_path):
    from aidevops.models import ProjectProfile, ProjectType
    from aidevops.planner import mock_plan
    from aidevops.generator.artifacts import build_artifact_contents
    profile = ProjectProfile(root=str(tmp_path), project_type=ProjectType.PYTHON,
        dependency_manifests=["pyproject.toml"], test_locations=["tests/test_app.py"])
    artifacts = {path: content for path, _, content, _ in build_artifact_contents(
        profile, mock_plan(profile, "test"))}
    dockerfile = artifacts["Dockerfile"]
    assert dockerfile.index("COPY . .") < dockerfile.index("RUN pip install --no-cache-dir .")
    ci = artifacts[".github/workflows/ci.yml"]
    assert ci.index("pip install pytest") < ci.index("python -m pytest")


def test_container_limits_timeout_and_cleanup(settings, tmp_path, monkeypatch):
    from aidevops.execution import runner, ExecutionContext
    ctx = ExecutionContext(tmp_path, settings)
    ctx.timeout_seconds = 7
    calls = []
    def invoke(argv, **kwargs):
        calls.append((argv, kwargs))
        return None, "deadline", False, "timeout"
    monkeypatch.setattr(runner, "_subprocess", invoke)
    result = runner.run_container("python:3.12-slim", ["python", "--version"], ctx)
    assert result.status == ExecutionStatus.TIMEOUT
    argv, options = calls[0]
    assert options["timeout"] == 7
    for flag in ["--memory", "--cpus", "--pids-limit", "--cap-drop", "--security-opt"]:
        assert flag in argv
    assert calls[1][0] == ["docker", "rm", "--force", argv[argv.index("--name") + 1]]


def test_two_store_instances_claim_phase_only_once(settings):
    from concurrent.futures import ThreadPoolExecutor
    from aidevops.db import JobStore
    from aidevops.models import JobRecord, JobState
    from aidevops.errors import InvalidTransitionError
    first, second = JobStore(settings.db_path), JobStore(settings.db_path)
    job = first.create(JobRecord())
    def claim(store):
        try:
            store.transition(job.id, JobState.ANALYZING)
            return True
        except InvalidTransitionError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, [first, second])) == [False, True]
