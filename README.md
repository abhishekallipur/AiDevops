# Autonomous AI DevOps Engineer

An AI-assisted DevOps system that **analyzes a repository, plans a deployment,
generates DevOps artifacts, validates them, and runs a narrow set of allowlisted
checks** — all locally and safely. Deployment to AWS is a planned extension, not
part of this milestone.

> **Project memory:** read [`PROJECT_MEMORY.md`](./PROJECT_MEMORY.md) first. It is
> the canonical, evidence-based handoff and records exactly what is verified.

## What works today (Milestone 1)

- **Repository analyzer** — static, evidence-based detection of language,
  framework, dependencies, entry points, tests, ports, and existing Docker/CI
  files. It **never executes repository code**.
- **AI planner** — produces a schema-validated deployment plan. With no provider
  key it returns a **clearly-labelled mock plan** (`source="mock"`), never
  disguised as AI output.
- **Artifact generator** — writes a project-specific `Dockerfile`,
  `.dockerignore`, and (when relevant) `docker-compose.yml` and a GitHub Actions
  workflow into an **isolated workspace**; it never overwrites your source.
- **Validation** — Dockerfile lint plus secret scanning; artifacts are marked
  verified/unverified.
- **Controlled execution** — a fixed, allowlisted tool registry with timeouts,
  output limits, working-directory restrictions, approval gates, and audit
  records. Container tools run only when a Docker daemon is available; otherwise
  they are recorded as `BLOCKED` rather than run on the host.
- **Job lifecycle** — explicit states persisted in SQLite, with an approval gate
  before execution.
- **FastAPI backend + Streamlit UI.**

**Not implemented yet:** AWS/Terraform deployment, CloudWatch monitoring,
Kubernetes, autonomous recovery/rollback, multi-user auth. See
[`docs/ROADMAP.md`](./docs/ROADMAP.md).

## Requirements

- Windows 10/11 (verified); other OSes should work but are untested.
- Python 3.11+ (3.14.2 verified).
- Optional: Docker Desktop, for container execution.
- Optional: an OpenAI-compatible API key, for live planning.

## Setup (PowerShell)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env      # optional; every variable has a safe default
```

## Run

Start the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn aidevops.api.main:app --port 8000
# root:   http://localhost:8000/        (service index)
# health: http://localhost:8000/health
# docs:   http://localhost:8000/docs
```

Start the UI (in a second terminal, with the API running):

```powershell
$env:AIDEVOPS_API_URL = "http://localhost:8000"
.\.venv\Scripts\python.exe -m streamlit run aidevops/ui/streamlit_app.py
# http://localhost:8501
```

The UI has its own light theme (`.streamlit/config.toml`). **Create + run
pipeline** performs the whole analyze → plan → generate → validate pass with a
live progress panel, then pauses at the approval gate.

## Try it end to end

Using the bundled sample repository (`examples/sample_python_app`):

```powershell
# 1. Create a job
curl -X POST http://localhost:8000/api/jobs -H "Content-Type: application/json" `
  -d '{"source_path":"E:\\Aidevops\\examples\\sample_python_app"}'

# 2. Analyze + plan + generate + validate (copy the id from step 1)
curl -X POST http://localhost:8000/api/jobs/<JOB_ID>/run

# 3. Inspect artifacts and validation
curl http://localhost:8000/api/jobs/<JOB_ID>/artifacts

# 4. Execution is gated: without approval this is refused (HTTP 400)
curl -X POST http://localhost:8000/api/jobs/<JOB_ID>/execute `
  -H "Content-Type: application/json" -d '{"approved":false}'

# 5. Approve execution
curl -X POST http://localhost:8000/api/jobs/<JOB_ID>/execute `
  -H "Content-Type: application/json" -d '{"approved":true}'
```

Generated files land under `data/generated/<JOB_ID>/`. The job DB is
`data/aidevops.db`.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Last observed result (2026-10-22): **89 passed, 1 skipped** (the skip needs symlink privileges
on Windows). See [`docs/TESTING.md`](./docs/TESTING.md).

## Enable live AI planning (optional)

Set `OPENAI_API_KEY` in `.env` (and optionally `OPENAI_MODEL`,
`OPENAI_BASE_URL`), then restart the API. Without a key the planner returns a
labelled mock plan and `/health` reports `llm_mode: "mock"`. **Never commit
`.env`.**

The provider targets **OpenAI-compatible chat gateways**; compatibility depends on the gateway/model. For
example, with an OpenRouter key (which gives you access to many models):

```
OPENAI_API_KEY=sk-or-v1-...
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=openai/gpt-4o-mini
```

Then plan output will carry `source: "llm"` instead of `source: "mock"`. Models
that reject the `response_format` parameter are handled automatically: the
provider retries without it and tolerates fenced/prose-wrapped JSON.

## Configuration

All configuration is via environment variables (see `.env.example`). Highlights:
`AIDEVOPS_DATA_DIR`, `AIDEVOPS_ALLOW_LOCAL_PATHS`, `AIDEVOPS_EXEC_BACKEND`
(`auto` | `container` | `disabled`), `AIDEVOPS_EXEC_TIMEOUT_SECONDS`,
`OPENAI_API_KEY`, `OPENAI_MODEL`. Secret values are never logged or persisted.

## Safety boundaries

- Repository analysis never executes project code and never follows symlinks.
- SSH keys, cloud credentials, `.env`, and key files are skipped and reported.
- Archives are guarded against zip-slip, absolute paths, symlinks, and bombs.
- LLM-proposed commands are advisory; only registry tools run, with approvals.
- Untrusted code runs only inside a container when a daemon is available;
  otherwise execution is blocked and reported.
- The Docker socket is never mounted into anything.

See [`docs/SECURITY.md`](./docs/SECURITY.md) for the full threat model.

## Legacy: AIDevOps Copilot

The original prototype (`app.py`, `rag.py`, `generator.py`, `knowledge/`) is a
separate Streamlit app that does TF-IDF retrieval over local notes and generates
Jenkinsfile/Dockerfile/Terraform snippets. It is preserved unchanged and is
independent of the new system:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

## Documentation

`PROJECT_MEMORY.md`, `docs/ARCHITECTURE.md`, `docs/IMPLEMENTATION_STATUS.md`,
`docs/CHANGELOG.md`, `docs/DECISIONS.md`, `docs/TOOL_REGISTRY.md`,
`docs/TESTING.md`, `docs/SECURITY.md`, `docs/ROADMAP.md`.

## Audit update — 2026-10-22

Scheduled checks must all return OK for a job to succeed. A blocked container test now produces FAILED with an explanatory reason. SUCCEEDED describes scheduled checks only, not an image build or deployment. The normal execution workflow does not build images; the separate image-build tool still needs a source+artifact build-context fix.

Container tests use filtered read-only snapshots and writable disposable container copies, with CPU/memory/PID limits. Dependency failures stop tests. See [security limitations](docs/SECURITY.md).

Optional live local verification (starts temporary loopback API/UI servers and runs sample Python/Node tests in Docker if available):
```powershell
.\.venv\Scripts\python.exe tests/smoke_local.py
```
Observed: both Docker workflows passed and Streamlit health/HTML returned 200. This is not a browser interaction test. The normal pytest suite uses isolated data and fake external services.

## A simpler guided interface
Open the UI and choose **Upload a project**, **Use a folder**, or **Try an example project**. Aidevops explains what it found, shows your suggested setup and lets you download all setup files together. Review the details, then give permission to run checks. Project files, commands and logs are available in expandable sections. The interface includes gentle animations, reduced-motion support and a responsive layout. It does not publish your app.

Latest verification after UI redesign: **89 passed, 1 skipped**, including 12 UI interaction tests; desktop browser welcome/review navigation and folder validation checked.

## Build & preview locally (2026-10-23)

After reviewing a project, open **Build & open your app**:
1. **Prepare build snapshot** copies permitted source and generated setup into a separate workspace.
2. Review the setup and approve that snapshot, then choose **Build my app**.
3. Once the image is verified, separately approve startup, set the app's internal port and health-check path, then **Start local preview**.
4. When the HTTP check passes, use **Open my app**. **Stop preview** removes the running container. **Remove preview resources** additionally removes its image and snapshot after confirmation.

The panel polls every two seconds during build/start and every ten seconds while a preview runs; it stays idle otherwise. Web apps must listen on 0.0.0.0 inside the container; their exposed preview port is bound only to 127.0.0.1. No cloud resources are created. Runtime app output is withheld because it may contain secrets; filtered build logs remain available. Previews expire while the backend is running (up to 10s polling delay); expiry is reconciled after restart. Run one API process per data directory.

Privacy settings (restart backend after changes):
```text
AIDEVOPS_LOCAL_ONLY=true
AIDEVOPS_AI_ALLOWED_HOSTS=api.openai.com,openrouter.ai
```
Local-only disables external AI, not Docker/package-download network traffic. Destination defaults are HTTPS-only; request redaction is heuristic. **See what is sent to AI** displays the filtered request after analysis, not a pre-send consent screen.

Real Docker smoke (creates only disposable sample resources, then removes its containers/images/snapshots):
```powershell
.\.venv\Scripts\python.exe tests/smoke_preview.py
```
Latest full suite: **108 passed, 1 skipped**. See docs/TESTING.md for evidence and known limits. Existing API servers must be restarted to load preview routes; Streamlit normally reloads changed source.

## Project-aware packaging update

Create a **new review** after updating to regenerate old Dockerfiles. Aidevops now distinguishes browser apps from Node servers: Create React App/Vite compile their assets and serve on8080; Next has a production-server strategy on3000; Node uses declared build/start scripts; FastAPI/Flask objects get appropriate web servers; static index.html projects work without a package manifest. Existing Dockerfiles can be reviewed and used. A single nested app is selected automatically; repositories with several apps ask you to choose one.

Supported is not the same as universally runnable. Private dependencies, databases, missing secrets, custom layouts/build outputs and invalid code can require configuration or a supplied Dockerfile. React(CRA),Vite,static HTML,Flask,FastAPI and Node runtime paths have live checks; other strategies have narrower evidence in IMPLEMENTATION_STATUS.md. Set AIDEVOPS_BUILD_TIMEOUT_SECONDS=600 (default) for build deadlines; normal test timeout stays separate. Live build output is available in the build-log section.


### Workspace navigation
Add a project using an archive, a local folder, or the bundled example. An existing project opens **Build & preview** first: prepare a snapshot, review and approve its build, then start and open the local app. Suggested launch settings are filled automatically; **Advanced preview settings** contains ports, health checks, expiry and an optional runtime environment value. Use **Project overview**, **Setup files**, and **Checks & results** for findings, downloads and separately approved checks. The indigo/navy theme uses local CSS, responsive layouts and animations that respect reduced-motion preferences.
