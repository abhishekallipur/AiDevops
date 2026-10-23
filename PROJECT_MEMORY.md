# Project memory

Canonical handoff, updated 2026-10-22 (Asia/Calcutta). Code and observed tests are authoritative.

## Project-aware Docker generation — 2026-10-23

User failure reproduced from stored review job_67d0ee470cbe: a Create React App repository built a generic Node image, then exited because it was launched as node index.js and preview port defaulted8000. A frontend source entry is not a Node server. Fixed runtime inference from root package scripts/dependencies and static AST evidence, not project names.

Current strategies: CRA/react-scripts and Vite browser apps compile with development build dependencies then serve built assets through unprivileged Nginx on8080 with SPA fallback; CRA PUBLIC_URL=/ and Vite --base=/ normalize local asset URLs. Vite literal outDir is supported. Next.js has build+production-server generation on3000 (unit-tested, not live verified). Node servers honor package start/main and custom build scripts rather than blindly running index.js. Static index.html folders work without package.json. Python FastAPI/Flask application objects are identified by AST and served with Uvicorn/Gunicorn; Streamlit and Django have conventional runtime command generation (not newly live verified). Pyproject dependencies are parsed without execution. One nested app folder can become the build root; multiple app folders require explicit selection. Existing Dockerfiles are retained for reviewed custom builds. Unknown inputs/Node projects with no supported startup fail with an actionable message instead of pretending a guessed template works.

New profile metadata: web_build_tool, package_scripts (names only), node_main, build_output, suggested_port, suggested_health_path, python_app. Pipeline updates source_path to the selected profile root. Generator uses detected serving ports over conflicting AI suggestions. Preview records carry recommendations; Docker image EXPOSE metadata can refine a unique port. Build logs update during execution. AIDEVOPS_BUILD_TIMEOUT_SECONDS now independently defaults600s (env loader clamps1..1800), replacing the old120s test deadline for preview builds.

Real Docker verification: actual downloaded React todo app built, HTTP page/JS asset/SPA route passed; browser loaded My Tasks and created a task. A new persistent review job_f5c20b2c6155 and30-minute preview were created without editing its source. docs/todo-working.png records the browser result. Separate static,Vite,Flask,FastAPI smoke projects built and served successfully; smoke-owned resources removed. Next/Django/Streamlit and other language templates do not gain live verification from these results.

Tests: tests/test_frontends.py and tests/smoke_frontends.py added. Full suite123 passed,1 Windows symlink skip; compileall/pip check passed. Earlier development failures were assertion wording (detected-port assumption, Next binary path), corrected and rerun. Existing older snapshots are immutable/historical: create a new review/snapshot to use the new strategy. No universal guarantee for arbitrary repositories: custom build output, native dependencies, multiple services, private packages, missing secrets, unsupported package managers/frameworks or invalid application code may need a supplied Dockerfile/configuration. HTTP readiness is not complete app correctness.

## Current release — 2026-10-23: approved local build and preview

This section supersedes older statements that image building/local previews and outbound privacy filtering are absent. The existing review workflow remains; a separate Build & open your app panel adds filtered snapshots, fingerprint-bound build approval, background Docker builds, independently inspected image IDs, separate start approval, loopback-only HTTP previews, startup health checks, stop/cancel, expiry and owned-resource cleanup. No cloud deployment is implemented.

New modules: aidevops/privacy.py, services/preview.py and ui/preview_panel.py. Preview records persist in data/previews.db; per-preview contexts and short-lived runtime files live in data/previews/<id>/. An OS file lock enforces one backend process per preview data directory. Use one Uvicorn worker. No extra dependencies were added. Legacy JobStore connections now explicitly close, fixing Windows database file locks.

Privacy: main provider and legacy generator apply final request redaction; recognized credential URLs, token/key patterns, assignments and local paths are filtered, incomplete private keys block transmission. AIDEVOPS_LOCAL_ONLY=true disables external AI in both flows. HTTPS destinations default to api.openai.com/openrouter.ai; AIDEVOPS_AI_ALLOWED_HOSTS explicitly extends that list. This is heuristic, not a guarantee against all secrets/prompt injection. The UI exposes the filtered request after analysis; it is not an approval-before-first-AI-call feature. Use local-only mode for no external AI traffic.

Preview workflow: POST /api/jobs/{job_id}/previews creates a fixed filtered source+artifact snapshot. Build requires approved=true and its exact SHA-256 digest; changes invalidate approval. Start separately requires approved=true, container port, health path, TTL (1–120 minutes), optional environment map. Background operations return 202; polling reports explicit phase/outcome. Fixed commands are owned by PreviewService, never supplied by callers/LLMs. The legacy registry container_build_image tool is BLOCKED with guidance to the snapshot workflow; its old generated-only build path is not used by the new feature.

Limits: max 2 active build/start operations and 20 unremoved snapshots per data directory; source file/count/depth/size limits; build timeout min(global execution timeout, 600s); retained logs bounded by exec_max_output_bytes. Runtime containers have 1 GiB/2 CPU/256 PID limits, dropped capabilities, no-new-privileges, bounded Docker logs, no host source/socket mounts and only 127.0.0.1 port binding. Builds and running apps have network access. HTTP probe does not follow redirects and bypasses environment proxies; a 2xx/3xx response plus running owned container establishes basic availability only.

Runtime settings are not saved in preview/job JSON or sent to AI. They are handed to Docker via a short-lived env file removed after startup and on restart. POSIX mode is 0600; Windows inherits directory ACLs. Docker retains environment values in container metadata until removal. UI accepts one optional variable; API accepts up to 30, total 64 KiB. Use a dedicated OS account for stronger local isolation. Runtime logs are intentionally withheld; build logs are filtered. No generic promise that arbitrary output contains no secrets.

Lifecycle: normal stop/cancel terminates the Docker client for an active operation, removes an owned runtime container and preserves explicit state. Image-build cancellation/daemon-side work is best effort; shared Docker build caches/base images are never pruned. Cleanup removes only label-verified resources and the guarded snapshot folder. Backend restart does not replay interrupted builds/starts; it marks them INTERRUPTED (or CLEANUP_FAILED), removes their owned app container and reconciles READY container presence/expiry. Expiry runs every 10s while backend is alive; if backend is down, existing app containers may continue until reconciliation. Health is a startup probe, not continuous HTTP monitoring. Original analyze/run/execute requests remain synchronous and their older crash-state limitations remain.

Verification: full suite 108 passed, 1 skipped (Windows symlink privileges); compileall and pip check passed. Real Docker smoke verified Python and Node build → inspected image → READY → HTTP 200 → stop; deliberate build failure and startup crash were correctly classified; smoke-owned images/containers/snapshots removed. First smoke exposed SQLite connection cleanup locks on Windows; explicit close fixed them and subsequent smoke passed. Commands/results in docs/TESTING.md. No live external AI or cloud calls were made. Existing local backend was idle and restarted on port 8000 to load the update.

Next priorities: runtime secret transport hardened beyond temporary files, browser/mobile/full live UI workflow validation, continuous health checks, stronger secret detection, broader runtime fixtures, and isolated/reproducible builders before cloud deployment. Do not treat previews as production isolation or expose unauthenticated API/UI to untrusted networks.

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


## SaaS workspace refresh — 2026-10-23
Replaced the mint review page with a navy sidebar, indigo accents, soft neutral workspace, responsive hero and local CSS illustrations. Added subtle entrance/hover/floating animation with reduced-motion support and visible keyboard focus. Project screens open Build & preview first; Project overview, Setup files and Checks & results are separate tabs. Preview ports, HTTP path and expiry remain prefilled; optional configuration is under Advanced preview settings. Resource removal is collapsed. Existing backend APIs and explicit build/start/check approvals are preserved.
Validation: 124 passed, 1 Windows symlink privilege skip; includes 15 UI AppTests covering navigation, approvals and exact default launch payload. Existing local Streamlit server restarted to load changed imported module/theme. Browser inspected narrow-screen welcome and existing project navigation; no desktop-width or assistive-technology audit. This change does not claim new runtime coverage for generated apps.
