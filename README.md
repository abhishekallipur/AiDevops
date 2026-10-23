# Aidevops

A local workspace that helps you turn an existing app into a Docker image and open a preview in your browser. Add your project, review the suggested setup, approve the build, and launch it locally.

Aidevops includes a FastAPI backend and a Streamlit frontend. AI planning is optional: without a provider key, it uses clearly labelled rule-based example plans.

## Quick navigation

- [Requirements](#requirements)
- [First-time setup](#first-time-setup-windows-powershell)
- [Run the project](#run-the-project)
- [Use the workspace](#use-the-workspace)
- [Supported projects](#supported-projects)
- [Configuration and AI privacy](#configuration-and-ai-privacy)
- [Troubleshooting](#troubleshooting)
- [API example](#api-example-powershell)
- [Tests and developer documentation](#tests-and-developer-documentation)

## Requirements

| Requirement | Purpose |
| --- | --- |
| Python 3.11 or newer | Runs the backend and UI. Python 3.14.2 was tested locally. |
| Docker Desktop with Linux containers | Required to build images, start previews, and run container tests. Start it before the backend. |
| Internet access | Usually needed to install Python packages and download Docker images/app dependencies. |
| Your app's source code | Upload a ZIP/TAR archive or use a folder on the backend computer. |
| AI provider key (optional) | Enables external AI planning. The project works without one. |

The commands below are for **Windows PowerShell** and assume this checkout is at **`E:\Aidevops`**. Change that path if you saved it elsewhere. Other operating systems have not been verified in this environment.

## First-time setup (Windows PowerShell)

Run these commands once from PowerShell:

```powershell
cd E:\Aidevops
py --version
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`py --version` must report Python 3.11 or newer. If `py` is unavailable but `python` points to a supported version, use `python -m venv .venv` instead.

**Already installed?** Skip virtual-environment creation. After pulling dependency changes, run only the `pip install -r requirements.txt` command above.

These instructions call the virtual environment's Python directly. You do not need to activate it or change PowerShell's execution policy.

### Optional configuration file

Defaults are enough to try the app. To customize them, copy the example only if `.env` does not already exist:

```powershell
cd E:\Aidevops
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
}
notepad .env
```

Keep `.env` private and do not commit it. Restart the backend after changing its configuration. Existing shell environment variables take precedence over `.env`.

## Run the project

### 1. Start Docker Desktop

Wait until its engine is ready. Check it in PowerShell:

```powershell
docker version
```

You should see both **Client** and **Server** information. Without Docker, you can still review projects and download setup files, but builds, previews, and container tests cannot run.

### 2. Start the backend â€” terminal 1

```powershell
cd E:\Aidevops
.\.venv\Scripts\python.exe -m uvicorn aidevops.api.main:app --host 127.0.0.1 --port 8000
```

Leave this terminal running.

### 3. Start the frontend â€” terminal 2

Open a second PowerShell window:

```powershell
cd E:\Aidevops
$env:AIDEVOPS_API_URL = "http://127.0.0.1:8000"
.\.venv\Scripts\python.exe -m streamlit run aidevops/ui/streamlit_app.py --server.address 127.0.0.1 --server.port 8501
```

Leave this terminal running too. Open **[http://localhost:8501](http://localhost:8501)**.

| Address | What it opens |
| --- | --- |
| [localhost:8501](http://localhost:8501) | Aidevops workspace |
| [localhost:8000/health](http://localhost:8000/health) | Backend connection/configuration status |
| [localhost:8000/docs](http://localhost:8000/docs) | Interactive API reference |

Run **one backend process per data directory**. Do not add multiple Uvicorn workers: the preview service uses a single-process worker lock.

### Stop or restart

1. In the UI, stop any active preview you no longer need. Use **Remove preview resources** if you also want its image and snapshot removed.
2. Press **Ctrl+C** in each terminal to stop the frontend and backend.
3. To restart, run the two startup commands again.

Stopping the frontend does not stop a preview container. Automatic preview expiry requires the backend to remain running; it reconciles expired sessions after restart. If the backend is offline, expiry is not enforced at that time.

After updating the project, restart both processes to load configuration and imported-module changes, then refresh the browser. Create a **new project review** to regenerate setup files; an old review keeps its previously generated files.

## Use the workspace

### 1. Add a project

Choose **ï¼‹ New project**, then one of:

- **Upload a project:** upload the source as ZIP, TAR, GZ, or TGZ. The backend upload limit defaults to 50,000,000 bytes, even if the browser uploader displays a higher limit.
- **Use a folder:** paste an absolute folder path, such as `E:\MyProjects\todo-app`. It must be accessible on the computer running the backend.
- **Try an example project:** explore the bundled sample without uploading files.

Use the app's source folder containing its manifest or entry point. Leave out `.env`, credentials, dependency directories, build caches, and unrelated files. A screenshot or finished installer is not app source.

Aidevops reads project clues, prepares a plan, generates setup files in an isolated workspace, and performs static validation. Original source files are not overwritten. The review then waits for your decisions.

### 2. Review the suggested setup

Use the project tabs:

| Tab | Purpose |
| --- | --- |
| **Build & preview** | Prepare a snapshot, build an image, and launch the app. Opens first. |
| **Project overview** | See the detected language/framework, evidence, plan, and assumptions. |
| **Setup files** | Inspect generated Docker/Compose/CI files and download them individually or as a ZIP. |
| **Checks & results** | Separately approve checks and inspect their results. |

The sidebar lets you reopen previous project reviews. **Refresh** reloads a project's status.

A plan is labelled **AI-generated suggestion** or **Example plan Â· not AI-generated**. A static validation pass means the generated instructions passed those checks; it does not prove an image builds or the app works.

### 3. Build the Docker image

In **Build & preview**:

1. Select **Prepare build snapshot**. This creates a filtered copy of the source plus setup files.
2. Review the setup, then check **I reviewed this setup and approve building this snapshot**.
3. Select **Build my app**.
4. Wait for **Image built and verified**. Open **Build log & technical details** for progress or errors.

The snapshot has a fingerprint so approval applies to that fixed copy. To include source changes, prepare and approve a new snapshot. Builds download dependencies and execute project build instructions with network access; use projects you trust.

### 4. Start and open your app

1. Check **I approve starting this app locally with internet access**.
2. Usually, keep the prefilled settings. Open **Advanced preview settings** if you need to change:
   - **App port:** the port inside the container, not the public browser port.
   - **Health-check path:** a working HTTP endpoint, usually `/`.
   - **Stop automatically after:** 15, 30, 60, or 120 minutes; default 30.
   - **Environment variable:** one optional runtime name/value in the UI.
3. Select **Start local preview**.
4. After the startup HTTP check passes, select **Open my app**.

The app must listen on `0.0.0.0` inside its container. Aidevops assigns a host port bound to `127.0.0.1`, so the preview is local to this computer. A passing HTTP check establishes basic availability, not complete functionality or security.

The panel refreshes every two seconds during build/start/stop and every ten seconds while a preview is ready. **Stop preview / cancel operation** stops the operation or running container. Expand **Remove preview resources**, confirm removal, then click its button to remove that preview's container, image, and snapshot.

### 5. Run optional project checks

In **Checks & results**, review the explanation, check the approval box, then select **Approve & run checks**. Container tests require Docker and may download dependencies and execute app code.

**Checks passed**, **image built**, and **preview ready** are separate results. Running checks does not build a preview image or deploy an app. If no tests were detected, static checks alone cannot establish app correctness.

## Supported projects

Detection and generation use project files and conventions; arbitrary projects are not guaranteed to run automatically.

| Project | Current strategy |
| --- | --- |
| Create React App / Vite | Build browser assets, then serve with Nginx on container port 8080. |
| Next.js | Production build and Node server, normally port 3000. |
| Node.js server | Uses declared start/main and supported build scripts. |
| FastAPI / Flask | Detects app objects and generates a web-server launch command. |
| Django / Streamlit | Convention-based launch strategies. |
| Static HTML | Serves an `index.html` project without a package manifest. |
| Existing Dockerfile | Preserves it for review and build use. |

CRA, Vite, static HTML, Flask, FastAPI, and Node paths have recorded live Docker checks. Other strategies have narrower verification; see [implementation status](docs/IMPLEMENTATION_STATUS.md).

A single nested app can be selected automatically. For repositories containing multiple apps, select the intended app folder. Databases, private packages, custom build layouts, missing credentials, unsupported runtimes, and invalid app code can require configuration or your own Dockerfile. Database provisioning and multi-service deployment are not automatic.

## Configuration and AI privacy

See [.env.example](.env.example) for the full list. Common settings:

| Variable | Default / meaning |
| --- | --- |
| `AIDEVOPS_DATA_DIR` | `data`; persistent application data. |
| `AIDEVOPS_ALLOW_LOCAL_PATHS` | `true`; permits folder-based reviews. |
| `AIDEVOPS_EXEC_BACKEND` | `auto`; container checks run if Docker is available. `disabled` blocks container check tools and new preview snapshots; stop existing previews separately. |
| `AIDEVOPS_EXEC_TIMEOUT_SECONDS` | `120`; normal tool timeout. |
| `AIDEVOPS_BUILD_TIMEOUT_SECONDS` | `600`; separate image-build timeout, capped at 1800 seconds. |
| `AIDEVOPS_LOCAL_ONLY` | `false`; set `true` to disable external AI requests. |
| `AIDEVOPS_AI_ALLOWED_HOSTS` | `api.openai.com,openrouter.ai`; permitted HTTPS AI destinations. |
| `OPENAI_API_KEY` | Empty by default; optional planning provider credential. |
| `OPENAI_MODEL` | Provider model identifier; see the repository defaults in `.env.example`. |
| `OPENAI_BASE_URL` | Optional compatible provider endpoint; must pass the destination policy. |
| `AIDEVOPS_API_URL` | Frontend backend address; explicitly set it in terminal 2 as shown above. |

To enable external planning, edit the provider fields in `.env`, set `AIDEVOPS_LOCAL_ONLY=false`, and restart the backend. Provider/model compatibility varies. `/health` reporting `llm_mode: "live"` means configured, not proof that a provider request succeeded. Check each plan's label; failures may fall back to an example plan.

For no external AI requests, put this in `.env` and restart the backend:

```dotenv
AIDEVOPS_LOCAL_ONLY=true
```

This disables external AI only. Docker builds, package downloads, and running apps can still access the network.

### What is protected, and what needs care

- Analysis does not execute project code; known sensitive paths and symlinks are excluded.
- AI requests pass through filtering/redaction and a permitted HTTPS destination check. Open **Privacy Â· see what is sent to AI** to inspect the filtered request after analysis. This is not a consent screen before the original request.
- Secret filtering is heuristic. Unusual filenames, unknown token formats, or sensitive source content can escape detection. Use local-only mode when external AI transmission is unsuitable.
- Model-proposed commands are advisory. Registered tools and explicit approvals control execution.
- Preview containers have resource limits and security restrictions. The Docker socket is not mounted into the app container. This is a local development tool, not a complete sandbox for hostile code.
- Runtime environment values are not sent to AI or saved in review records. Docker can retain them in container metadata until removal. Runtime app logs are withheld in the UI because apps can print secrets; filtered build logs remain available.
- The service has no multi-user authentication. Keep it on loopback; do not expose it publicly.

Read [SECURITY.md](docs/SECURITY.md) for the full boundaries and limitations.

### Where files are stored

With default settings:

| Location | Contents |
| --- | --- |
| `data/aidevops.db` | Project reviews and their state. |
| `data/generated/<JOB_ID>/` | Generated setup files. |
| `data/previews.db` | Preview state and build records. |
| `data/previews/` | Preview snapshots and worker lock. |

Treat these as local project data. Do not delete the data directory as a routine troubleshooting step. Use the UI's resource-removal controls for previews.

## Troubleshooting

| Problem | What to do |
| --- | --- |
| `.venv\Scripts\python.exe` cannot be found | Run first-time setup from `E:\Aidevops`. Confirm `py --version` is supported. |
| `ModuleNotFoundError` | Run `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` from the project directory. |
| Backend is offline in the UI | Keep terminal 1 running. Open `/health`, check terminal errors, and verify terminal 2's `AIDEVOPS_API_URL`. |
| Port 8000 or 8501 is already in use | Check whether Aidevops is already running. Stop the previous instance in its own terminal with Ctrl+C before restarting. |
| Docker is unavailable | Start Docker Desktop with Linux containers, wait for `docker version` to show Server information, then restart the backend and refresh. |
| Another preview worker owns the data directory | Stop duplicate backend processes gracefully. Run one backend for that directory; deleting the lock file is not a substitute. |
| Upload rejected | Check the backend size limit, archive format, and excluded/unsafe files. Try the local source folder instead. |
| Project type is unknown / several apps detected | Select the actual app folder containing its manifest or entry point, or supply a suitable Dockerfile. |
| Image build fails | Read **Build log & technical details**. Check dependency access, build scripts, missing files, and Dockerfile assumptions. Fix the source and create a new review/snapshot. |
| Build times out | Increase `AIDEVOPS_BUILD_TIMEOUT_SECONDS` within its maximum, restart the backend, and retry the reviewed snapshot. |
| Image builds but preview fails | Check the internal port, a valid HTTP path, `0.0.0.0` binding, and required runtime settings/services. |
| AI plan is labelled as an example | Check provider configuration and local-only mode. The label is intentional; a configured key does not guarantee a successful model response. |
| Old UI or Dockerfile remains | Restart both services and refresh. Create a new review to generate updated setup files. |
| Snapshot limit reached | Remove unused preview resources through the UI. The service currently permits 20 unremoved snapshots and two active operations. |

## API example (PowerShell)

The UI is the easiest starting point. For scripting, start the backend and run the following in another PowerShell terminal:

```powershell
cd E:\Aidevops
$apiBase = "http://127.0.0.1:8000"
$samplePath = (Resolve-Path .\examples\sample_python_app).Path
$createBody = @{ source_path = $samplePath } | ConvertTo-Json
$job = Invoke-RestMethod -Method Post -Uri "$apiBase/api/jobs" -ContentType "application/json" -Body $createBody
$jobId = $job.id

# Analyze, plan, generate, and validate.
$review = Invoke-RestMethod -Method Post -Uri "$apiBase/api/jobs/$jobId/run"
$review | Select-Object id, state, project_name

# Inspect generated files before approving execution.
$setup = Invoke-RestMethod -Uri "$apiBase/api/jobs/$jobId/artifacts"
$setup.artifacts | Select-Object path, kind, verified
```

After reviewing the setup, this separate command approves the registered checks. It does not build a preview image:

```powershell
$approvalBody = @{ approved = $true } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$apiBase/api/jobs/$jobId/execute" -ContentType "application/json" -Body $approvalBody
```

Use [the API reference](http://localhost:8000/docs) for upload, cancellation, sanitized prompt inspection, and separate preview snapshot/build/start/stop/cleanup endpoints. Build approval includes the snapshot digest; startup requires its own approval.

## Tests and developer documentation

Run automated tests from the repository root:

```powershell
cd E:\Aidevops
.\.venv\Scripts\python.exe -m pytest -o addopts="" -rs
```

Last full-suite verification on **24 October 2026 (India time): 124 passed, 1 skipped**. The skipped test needs Windows symlink privileges. This includes 15 Streamlit UI tests; ordinary tests use isolated data and fake external services rather than proving every uploaded app builds.

Optional integration checks below start temporary services and perform real Docker work. They may download dependencies and take longer; inspect their scripts before running:

```powershell
.\.venv\Scripts\python.exe tests/smoke_local.py
.\.venv\Scripts\python.exe tests/smoke_preview.py
.\.venv\Scripts\python.exe tests/smoke_frontends.py
```

| Document | Purpose |
| --- | --- |
| [Project memory](PROJECT_MEMORY.md) | Contributor handoff and verification context. |
| [Architecture](docs/ARCHITECTURE.md) | Components and data flow. |
| [Implementation status](docs/IMPLEMENTATION_STATUS.md) | Feature coverage and verification limits. |
| [Testing](docs/TESTING.md) | Tests and recorded evidence. |
| [Security](docs/SECURITY.md) | Privacy, execution boundaries, and known risks. |
| [Tool registry](docs/TOOL_REGISTRY.md) | Allowlisted execution tools. |
| [Decisions](docs/DECISIONS.md) | Design decisions. |
| [Changelog](docs/CHANGELOG.md) | Change history. |
| [Roadmap](docs/ROADMAP.md) | Planned work. |

Cloud deployment, Kubernetes management, automatic database provisioning, multi-user authentication, and autonomous recovery/rollback are not implemented.

### Legacy prototype

`app.py`, `rag.py`, `generator.py`, and `knowledge/` belong to the older notes-retrieval prototype. They are separate from the main Aidevops workspace. To explore it, use another free UI port:

```powershell
cd E:\Aidevops
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```
