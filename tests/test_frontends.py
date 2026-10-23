import json
from pathlib import Path

import pytest

from aidevops.analyzer import analyze_path
from aidevops.generator.artifacts import build_artifact_contents
from aidevops.models import DeploymentPlan, ProjectType
from aidevops.planner import mock_plan


@pytest.mark.parametrize("tool", ["cra", "vite"])
def test_browser_apps_build_assets_and_serve_http(tmp_path, settings, tool):
    scripts = {"build": "react-scripts build", "start": "react-scripts start"} if tool == "cra" else {"build": "tsc -b && vite build", "dev": "vite"}
    package = {"scripts": scripts, "dependencies": {"react": "18.2.0"}, "devDependencies": {"vite": "6.0.0"}}
    (tmp_path / "package.json").write_text(json.dumps(package))
    (tmp_path / "package-lock.json").write_text("{}")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/index.js").write_text("import React from 'react';")
    profile = analyze_path(tmp_path, settings)
    assert profile.web_build_tool == tool
    assert profile.suggested_port == 8080
    # An incompatible model suggestion must not break a recognized static app.
    plan = DeploymentPlan(summary="bad suggestion", run_command="node index.js", base_image="python:3.12", exposed_port=8000)
    files = {p: c for p, _, c, _ in build_artifact_contents(profile, plan)}
    content = files["Dockerfile"]
    assert "FROM node:22-slim AS build" in content
    assert "npm ci --include=dev" in content
    assert "npm run build" in content
    assert "COPY --from=build /app/" + ("build" if tool == "cra" else "dist") in content
    assert "EXPOSE 8080" in content and "USER 101" in content
    assert "try_files $uri $uri/ /index.html" in content
    assert 'ENTRYPOINT ["nginx"' in content
    assert "node index.js" not in content
    assert "PUBLIC_URL=/" in content if tool == "cra" else "--base=/" in content
    assert "8080:8080" in files["docker-compose.yml"]
    assert mock_plan(profile, "offline").exposed_port == 8080


def test_vite_custom_output(tmp_path, settings):
    (tmp_path / "package.json").write_text('{"scripts":{"build":"vite build"}}')
    (tmp_path / "vite.config.ts").write_text("export default { build: { outDir: 'web-output' } }")
    profile = analyze_path(tmp_path, settings)
    assert profile.build_output == "web-output"
    dockerfile = build_artifact_contents(profile, mock_plan(profile, "offline"))[0][2]
    assert "/app/web-output/" in dockerfile
    assert "npm install --include=dev" in dockerfile


def test_node_backend_uses_start_script(tmp_path, settings):
    (tmp_path / "package.json").write_text('{"scripts":{"start":"node server.js"}}')
    (tmp_path / "server.js").write_text("app.listen(3000)")
    profile = analyze_path(tmp_path, settings)
    assert profile.web_build_tool is None
    content = build_artifact_contents(profile, mock_plan(profile, "offline"))[0][2]
    assert 'CMD ["npm", "start"]' in content
    assert "nginx" not in content


def test_static_site_without_package(tmp_path, settings):
    (tmp_path / "index.html").write_text("<html><body>Todo</body></html>")
    profile = analyze_path(tmp_path, settings)
    assert profile.project_type == ProjectType.STATIC
    assert profile.suggested_port == 8080
    content = build_artifact_contents(profile, mock_plan(profile, "offline"))[0][2]
    assert "nginx" in content and "npm" not in content


def test_next_production_build_and_runtime(tmp_path, settings):
    (tmp_path / "package.json").write_text('{"scripts":{"build":"next build","start":"next start"},"dependencies":{"next":"15.0.0","react":"19.0.0"}}')
    profile = analyze_path(tmp_path, settings)
    assert profile.web_build_tool == "next" and profile.suggested_port == 3000
    content = build_artifact_contents(profile, mock_plan(profile, "offline"))[0][2]
    assert "RUN npm run build" in content
    assert '"./node_modules/.bin/next", "start"' in content
    assert "EXPOSE 3000" in content and "nginx" not in content


@pytest.mark.parametrize("framework,dependency,source,expected,port", [
    ("FastAPI", "fastapi", "from fastapi import FastAPI\napi = FastAPI()", "app:api", 8000),
    ("Flask", "flask", "from flask import Flask\nweb = Flask(__name__)", "app:web", 5000),
])
def test_python_web_object_is_inferred_without_execution(tmp_path, settings, framework, dependency, source, expected, port):
    (tmp_path / "requirements.txt").write_text(dependency)
    (tmp_path / "app.py").write_text(source)
    profile = analyze_path(tmp_path, settings)
    assert profile.python_app == expected and profile.suggested_port == port
    content = build_artifact_contents(profile, mock_plan(profile, "offline"))[0][2]
    assert expected in content and f"EXPOSE {port}" in content
    assert "uvicorn" in content if framework == "FastAPI" else "gunicorn" in content


def test_nested_single_application_root_is_selected(tmp_path, settings):
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend/package.json").write_text('{"scripts":{"build":"vite build"}}')
    profile = analyze_path(tmp_path, settings)
    assert Path(profile.root) == tmp_path / "frontend"
    assert profile.web_build_tool == "vite"


def test_multiple_application_roots_require_explicit_selection(tmp_path, settings):
    from aidevops.errors import ValidationError
    for name in ("client", "server"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "package.json").write_text('{}')
    with pytest.raises(ValidationError, match="Multiple application"):
        analyze_path(tmp_path, settings)


def test_pyproject_dependencies_are_read(tmp_path, settings):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="example"\ndependencies=["flask>=3"]\n')
    (tmp_path / "app.py").write_text('from flask import Flask\napp=Flask(__name__)')
    profile = analyze_path(tmp_path, settings)
    assert "flask" in profile.dependencies
    assert profile.python_app == "app:app"


def test_existing_dockerfile_is_preserved(tmp_path, settings):
    original = 'FROM alpine:3.20\nUSER 10001\nEXPOSE 9123\nCMD ["sleep","60"]\n'
    (tmp_path / "Dockerfile").write_text(original)
    (tmp_path / "custom-service").mkdir()
    (tmp_path / "custom-service/package.json").write_text('{}')
    profile = analyze_path(tmp_path, settings)
    files = build_artifact_contents(profile, mock_plan(profile, "offline"))
    assert files[0][2] == original
    assert Path(profile.root) == tmp_path


def test_unrecognized_node_entry_requires_configuration(tmp_path, settings):
    from aidevops.errors import ValidationError
    (tmp_path / "package.json").write_text('{}')
    profile = analyze_path(tmp_path, settings)
    with pytest.raises(ValidationError, match="startup"):
        build_artifact_contents(profile, mock_plan(profile, "offline"))


def test_custom_node_build_script_runs_before_start(tmp_path, settings):
    (tmp_path / "package.json").write_text('{"scripts":{"build":"tsc","start":"node dist/server.js"}}')
    profile = analyze_path(tmp_path, settings)
    content = build_artifact_contents(profile, mock_plan(profile, "offline"))[0][2]
    assert "--include=dev" in content and "RUN npm run build" in content
    assert 'CMD ["npm", "start"]' in content


def test_unrecognized_input_fails_with_next_action(client, tmp_path):
    (tmp_path / "notes.txt").write_text("just notes, not an application")
    created = client.post("/api/jobs", json={"source_path": str(tmp_path)}).json()
    result = client.post(f"/api/jobs/{created['id']}/run").json()
    assert result["state"] == "FAILED"
    assert "source folder" in result["error"] and not result["artifacts"]
