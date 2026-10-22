# Project memory

Canonical handoff, updated 2026-10-22 (Asia/Calcutta). Code and observed tests are authoritative.

## Current state
Autonomous AI DevOps Engineer is a local FastAPI/Streamlit application: static repository analysis → schema-validated AI or explicitly labelled mock planning → isolated artifact generation → static validation → human approval → allowlisted checks → persisted verification outcome. AWS deployment, monitoring and recovery are PLANNED. No production/cloud actions were performed.

The existing repository is E:/Aidevops. At audit start, application files were untracked and Git had no versioned application baseline. Preserve them; no initial commit was made. Legacy app.py, generator.py, rag.py and knowledge/ remain separate.

## Verified stack
Python 3.14.2; FastAPI 0.158.0; Starlette 1.9.0; Uvicorn 0.54.0; Pydantic 2.14.1; Streamlit 1.66.0; OpenAI SDK 3.35.1; httpx 0.28.1; pytest 9.1.1. SQLite is stdlib. These are installed versions, not a reproducible lockfile. Docker server responded with 29.6.2 on this audit.

## Repository map
- aidevops/config.py: environment/.env settings. Never print .env or secret values.
- aidevops/models.py: Pydantic contracts, JobRecord and state machine.
- aidevops/db.py: SQLite jobs table; indexed scalar fields plus full JSON document, atomic transition transactions, stale-state save rejection.
- aidevops/analyzer/: static detection and bounded archive extraction. No source execution.
- aidevops/planner/: OpenAI-compatible chat adapter, schema validation, labelled mock fallback. OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL configure it. Provider timeout/retries come from AIDEVOPS_LLM_*; SDK retries are disabled to avoid multiplying attempts.
- aidevops/generator/: Docker/Compose/CI templates, output workspace guards and static lint/secret scan. Static validation is not a successful image build.
- aidevops/execution/: typed registry, approvals, container gating and bounded subprocess runner.
- aidevops/services/pipeline.py: orchestration and verification aggregation.
- aidevops/api/main.py: API factory and routes.
- aidevops/ui/streamlit_app.py: HTTP client, new/recent jobs, evidence, plan/artifact previews, downloads, approval and execution records.
- tests/: pytest/AppTest; smoke_local.py is opt-in real HTTP/Streamlit/Docker smoke.
- data/: ignored runtime DB, uploaded/extracted sources and generated artifacts. Never delete user runtime state casually.

## Run and configuration
From E:/Aidevops, PowerShell:
```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Only if .env does not exist: Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn aidevops.api.main:app --host 127.0.0.1 --port 8000
# Second terminal:
$env:AIDEVOPS_API_URL = "http://127.0.0.1:8000"
.\.venv\Scripts\python.exe -m streamlit run aidevops/ui/streamlit_app.py
.\.venv\Scripts\python.exe -m pytest -o addopts="" -rs
```
Python >=3.11 is declared; only 3.14.2 was exercised here. Settings include AIDEVOPS_DATA_DIR, AIDEVOPS_DB_PATH, AIDEVOPS_GENERATED_DIR, AIDEVOPS_ALLOW_LOCAL_PATHS, AIDEVOPS_EXEC_BACKEND, AIDEVOPS_EXEC_TIMEOUT_SECONDS and AIDEVOPS_EXEC_MAX_OUTPUT_BYTES. See .env.example. No key is needed for labelled mock mode.

## Contracts and workflow
GET / and /health expose service information; /api/tools catalogs tools. POST /api/jobs accepts source_path; POST /api/jobs/upload accepts multipart file. GET /api/jobs lists up to 50 recent summaries; GET /api/jobs/{id} returns the full JobRecord. POST suffixes /analyze, /generate, /run, /execute and /cancel advance/cancel the job. GET /artifacts returns artifacts, reports and preview. Execution requires {"approved": true}. Routes remain synchronous HTTP 200; create uses 201. Invalid state transitions use 409; application input errors use 400; request-schema errors use 422; unknown jobs use 404.

Job path: PENDING → ANALYZING → PLANNED → GENERATING → VALIDATING → AWAITING_APPROVAL → EXECUTING → VERIFYING → SUCCEEDED or FAILED. Nonterminal jobs can be CANCELLED. Every scheduled execution must be OK for success; BLOCKED/TIMEOUT/ERROR cause FAILED with a persisted reason. This means unavailable Docker prevents success when tests are scheduled. Success means the scheduled checks passed, not that an image was built or a deployment is healthy. No-test repositories can finish static checks without runtime evidence.

## Execution boundaries
Tools: list_workspace, dockerfile_lint, container_test, container_build_image. Only registered code supplies argv; plan commands are advisory. Execution API approval is required; image-build tool additionally checks approval. Test containers receive a bounded source snapshot excluding known secret paths, symlinks, caches and VCS files. The snapshot is mounted read-only; a disposable in-container copy is writable for dependency/build tools. Container tests have 1 GiB memory, 2 CPUs, 256 PID limit, all capabilities dropped and no-new-privileges. Network bridge remains available during dependencies AND tests. No Docker socket or environment credentials are mounted. Denylist filtering is not complete secret detection.

Subprocess timeout is min(global setting, tool limit): tests 300s, build 600s. In-process read-only tools declare 10s but do not have a preemptive timer. Output is drained with bounded retained memory. Timed-out test containers receive a named docker rm --force cleanup attempt. Cleanup failure cannot guarantee removal during daemon failure. Builds are separate Docker daemon operations, not runtime containers.

## Audit results and recent changes
Baseline: 65 passed, 1 skipped. Regression fixes cover false success, lost exception reasons/stuck execution, duplicate transitions, stale post-cancel saves, timeout selection, bounded output and process timeout, malformed package manifests, upload read limits, redacted secret diagnostics, UI selection/action/state feedback, and sanitized test mounts. Generator now copies Python package sources before pip install . and generated Python CI installs pytest. Live Python and Node checks passed with real Docker; Streamlit HTTP health/HTML passed. See docs/TESTING.md and docs/CHANGELOG.md for exact commands/final counts. Historical 2026-10-21 live AI evidence is retained in the changelog and was not repeated here.

## Known limitations / next tasks (priority order)
1. PARTIAL: image-build tool still uses the generated-only workspace as build context; typical apps require source files. It is not called by execute_job. Add a reviewed sanitized source+artifact context and independent image verification before advertising a working image build.
2. PARTIAL: jobs persist, but a process crash during active work leaves an active state; add restart reconciliation and background workers. No automatic retry of side effects.
3. PARTIAL: synchronous long HTTP calls; cancellation prevents subsequent tools/stale state writes but does not interrupt the current tool. Same-state concurrent document saves can still lose updates; use revision checks before supporting multiple workers.
4. Security: local single-user only, no auth/rate limits. Do not expose the API to untrusted networks. Local paths are operator-authorized directories, not an enforced root allowlist. Docker availability is cached until restart/reset. Unusual secret filenames, concurrent source mutation and dependency network access remain risks.
5. Archive rejection may leave partial extracted files and uploads; multipart is spooled before route-level bounded reads. Add streaming ingress limits, archive cleanup/preflight and malformed archive error normalization.
6. Generated templates remain heuristic: other runtimes/base-image compatibility and complete builds are not verified; Rust binary naming and unknown templates need manual edits. Static passed/verified flags are not build evidence.
7. No browser/mobile/accessibility interaction run, live LLM recheck, AWS/Terraform/CI execution, dependency vulnerability scan or reproducible dependency lock in this audit.
8. Add versioned history and project CI after review; preserve existing untracked work.

## Next agent instructions
Read this file, README and docs first. Inspect code and Git status before editing. Run pytest baseline. Preserve existing untracked code/runtime data and credentials. Do not run arbitrary model commands or unapproved cloud/destructive operations. Use temporary data for checks. Update memory, status, changelog and relevant docs after meaningful edits. Never infer deployment/build success from lint success or call historical evidence a new verification.

## Documentation index
[README](README.md), [architecture](docs/ARCHITECTURE.md), [status](docs/IMPLEMENTATION_STATUS.md), [changelog](docs/CHANGELOG.md), [decisions](docs/DECISIONS.md), [tools](docs/TOOL_REGISTRY.md), [testing](docs/TESTING.md), [security](docs/SECURITY.md), [roadmap](docs/ROADMAP.md).

## Latest UI handoff — 2026-10-22
The current UI is a guided nontechnical experience, not the old developer dashboard. Read aidevops/ui/presentation.py (display labels only), styles.css (local theme, responsive layout, reduced motion) and streamlit_app.py (HTTP actions). Main flow: upload/folder/example → suggested setup/files → per-project approval/check results. Technical details are progressively disclosed. All setup files download as a ZIP; original individual downloads remain. Viewer toolbar hides Streamlit Deploy. No backend/tools/schema changes in this redesign.

Latest final test result supersedes the earlier audit count: 89 passed, 1 skipped in 7.87s; 12 UI AppTests. Existing desktop browser verified welcome, folder validation, existing review and back-to-new-project navigation. Mobile/assistive technology and reduced-motion settings were not browser tested. The pre-existing localhost:8501 server displayed the new code. No new background server was started (automatic review rejected the attempt). Keep all prior backend/security limitations in scope.
