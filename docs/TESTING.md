# Testing

Historical baseline: 2026-10-22, Asia/Calcutta. All commands from E:/Aidevops in PowerShell.

| Exact command | Observed result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest -o addopts="" -rs` before edits | PASS: 65 passed, 1 skipped in 8.48s |
| `.\.venv\Scripts\python.exe -m pytest -o addopts="" -rs` final | PASS: 83 passed, 1 skipped in 5.83s |
| `.\.venv\Scripts\python.exe -m pip check` | PASS: No broken requirements found |
| `.\.venv\Scripts\python.exe -m compileall -q aidevops tests` | PASS: exit 0 |
| `docker info --format '{{.ServerVersion}}'` | PASS: 29.6.2 |
| `.\.venv\Scripts\python.exe tests/smoke_local.py` | PASS: live temporary API health, create/run/approval refusal/execution for Python and Node, real container tests OK, jobs SUCCEEDED; Streamlit health+HTML passed |

Skipped: tests/test_analyzer.py::test_symlink_is_not_followed; Windows symlink creation needs privileges. No other skips.

Regression coverage includes all execution result statuses, persisted policy exceptions, per-tool/global timeout selection, real subprocess output bounds/timeouts, duplicate phase claims across two stores, stale cancelled saves, malformed package manifests, oversized upload, redacted secret diagnostics, Docker limits/cleanup argv, Python install/CI order, filtered source snapshots, new-job selection persistence and invalid UI action disabling.

Tests use temporary SQLite databases/workspaces and fake providers. AppTest uses fake HTTP and does not establish browser responsiveness/accessibility. smoke_local.py uses real loopback servers and Docker with disposable sources/data, clears the provider key in child processes, terminates its servers, and does not modify existing runtime data. It is opt-in because it can pull images and download/install dependencies inside containers. Python and Node were actually executed; other runtime commands were not.

Not run in the historical baseline: browser interactions/mobile/accessibility, live LLM/provider requests, generated image builds/health checks, remote GitHub Actions, Terraform validation/plan/apply, AWS/CloudWatch/recovery, SAST/dependency vulnerability scans. No frontend production bundle exists (Streamlit). No lint/type/format tool is configured; these checks are not claimed as passing. pip check checks installed dependency consistency, not vulnerabilities.

Historical 2026-10-21 live AI/container checks are retained in CHANGELOG.md. They are historical observations, not repeat checks of this revision.

## UI redesign verification — 2026-10-22 (supersedes earlier final count)
- `.\.venv\Scripts\python.exe -m pytest tests/test_ui.py -o addopts="" -q`: 12 passed.
- `.\.venv\Scripts\python.exe -m pytest -o addopts="" -rs`: 89 passed, 1 skipped in 7.87s (same Windows symlink privilege skip).
- `.\.venv\Scripts\python.exe -m compileall -q aidevops tests`: passed.
- Existing desktop browser at localhost:8501: welcome screen inspected visually; folder tab, empty-form feedback, existing review selection and new-project navigation confirmed. No new execution or live AI request was triggered by browser testing.
- Mobile layouts, OS reduced-motion settings, screen readers and browser ZIP contents were not independently tested. Previous live Docker smoke evidence belongs to the preceding backend audit; no runtime/tool changes were made by this UI redesign.

## Build/preview release — 2026-10-23

| Exact command | Observed result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest -o addopts="" -rs` |108 passed,1 skipped; skip remains Windows symlink creation privileges |
| `.\.venv\Scripts\python.exe -m compileall -q aidevops tests generator.py` |PASS exit0 |
| `.\.venv\Scripts\python.exe -m pip check` |PASS No broken requirements found |
| `.\.venv\Scripts\python.exe tests/smoke_preview.py` |PASS exit0: real Python/Node builds, verified image IDs, loopback HTTP200, stop; deliberate build/start failures; owned resources removed |

17 preview/privacy tests cover snapshot exclusions/hash invalidation, secret source rejection, background build outcomes, startup/expiry/cleanup, duplicate/cancel claims, interruption reconciliation, environment validation, privacy at the provider boundary, disabled execution, normal environment lookup source, single-worker lock, foreign-container protection, validation error secrecy and daemon-unavailable cleanup.14 UI tests include new build/start consent controls. External AI calls remain faked in tests.

Historical failure preserved: first real smoke completed Docker cases but failed temporary-directory cleanup because SQLite connections remained open on Windows. Fixed with explicit close; reruns passed. Docker Desktop was initially stopped, was launched from the installed vendor executable, and server29.6.2 became available. No package installation was needed.

Smoke resources use unique label-verified identities and disposable sources/data. Base image layers/shared Docker cache may remain; the test does not prune shared resources. Browser end-to-end Docker execution, mobile/assistive technology, OS reduced-motion preferences, external provider retention/security and cloud deployment are not established by these tests. Runtime logs are intentionally withheld. Expiry/restart edge cases use unit tests rather than a long-running outage simulation.

Final desktop browser check: existing analyzed project opened; new Build & open your app/Prepare build snapshot controls rendered from the updated backend. Saved docs/local-preview.png. No user project was built or started through browser actions; actual build/start/failure/cleanup tests used disposable smoke sources.

## Runtime strategy regression — 2026-10-23

- `.\.venv\Scripts\python.exe -m pytest -o addopts="" -rs`:123 passed,1 Windows symlink skip.
- `.\.venv\Scripts\python.exe -m compileall -q aidevops tests`:PASS.
- `.\.venv\Scripts\python.exe -m pip check`:PASS, no broken requirements.
- `.\.venv\Scripts\python.exe tests/smoke_frontends.py --source "C:\Users\abhishek a\Downloads\todo_react_app-master\todo_react_app-master"`:PASS actual CRA build, HTML,JavaScript asset,SPA route; smoke resources removed.
- `.\.venv\Scripts\python.exe tests/smoke_frontends.py`:PASS real static,Vite,Flask,FastAPI build/start/HTTP checks. Only browser strategies test SPA fallback; Flask/FastAPI test their actual root HTTP response. Smoke resources removed.
- Browser: actual todo app My Tasks rendered; New Task accepted a title/summary and displayed it. Screenshot docs/todo-working.png. This is a concrete interaction check, not an audit of every app feature.

15 new strategy regressions cover CRA/Vite asset serving, custom Vite output, Node scripts, static HTML, Next generation, Python import objects, nested/multiple roots,pyproject dependencies,existing Dockerfiles,missing Node startup,custom Node build and unsupported-input guidance. Older incorrect artifacts/snapshots are not mutated. No private project source was sent to external AI for these checks.


## SaaS workspace refresh — 2026-10-23
Replaced the mint review page with a navy sidebar, indigo accents, soft neutral workspace, responsive hero and local CSS illustrations. Added subtle entrance/hover/floating animation with reduced-motion support and visible keyboard focus. Project screens open Build & preview first; Project overview, Setup files and Checks & results are separate tabs. Preview ports, HTTP path and expiry remain prefilled; optional configuration is under Advanced preview settings. Resource removal is collapsed. Existing backend APIs and explicit build/start/check approvals are preserved.
Validation: 124 passed, 1 Windows symlink privilege skip; includes 15 UI AppTests covering navigation, approvals and exact default launch payload. Existing local Streamlit server restarted to load changed imported module/theme. Browser inspected narrow-screen welcome and existing project navigation; no desktop-width or assistive-technology audit. This change does not claim new runtime coverage for generated apps.

## AWS deployment and monitoring — 2026-11-25

| Exact command | Observed result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest -o addopts="" -rs` | 179 passed, 3 skipped in 32.02s |
| `.\.venv\Scripts\python.exe -m pytest tests/test_aws_management.py tests/test_aws_integration.py tests/test_ui.py -q` | 39 passed, 1 skipped; LocalStack integration skipped unless enabled |
| `$env:AIDEVOPS_AWS_INTEGRATION = '1'; $env:AIDEVOPS_AWS_ENDPOINT_URL = 'http://localhost:4566'; .\.venv\Scripts\python.exe -m pytest tests/test_aws_integration.py -q` | 1 passed against LocalStack; read-only STS identity check |
| `.\.venv\Scripts\python.exe -m compileall -q aidevops tests` | PASS |
| `.\.venv\Scripts\python.exe -m pip check` | PASS: no broken requirements |
| `git diff --check` | PASS |

Mocked AWS tests cover LocalStack-only credentials/defaults, explicit real-AWS mode separation, endpoint-secret redaction, static/S3 and server/EC2 recommendations, public-access and deploy approval gates, bounded static-archive validation, mocked S3 deployment/audit, mocked ECR/EC2 launch arguments, capped CloudWatch requests, and administrator authorization. The opt-in AWS integration test contacts only LocalStack STS; it passed against the local service. A separate local service check confirmed the backend could list the empty EC2/S3 overview. No real AWS calls or deployments were performed. These checks do not establish end-to-end Docker image push, LocalStack deployment compatibility, bootstrapped EC2 app health, or real AWS permissions/cost behavior.

## Project workflow and monitoring assistant update

| Exact command | Observed result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest -o addopts="" -ra` | 189 passed, 3 skipped in 35.09s |
| `.\.venv\Scripts\python.exe -m pytest tests/test_ui.py -q` | 29 Streamlit UI tests passed |
| `.\.venv\Scripts\python.exe -m compileall -q aidevops tests` | PASS |
| `.\.venv\Scripts\python.exe -m pip check` | PASS: no broken requirements |
| `git diff --check` | PASS |

The project home now presents archive upload and local-folder entry together. Build and preview remain the primary project workflow; overview, setup files, and technical check results are expandable details, while required approvals remain visible. The assistant has a dedicated workspace page, submits chat to the backend, and has mocked UI coverage for sending a question and displaying a response. A regression test verifies FastAPI previews offer `/docs` when the saved root URL is unavailable. Existing API tests cover administrator-only live Docker and EC2 readings; general questions still use the configured provider. The three skipped tests require Windows symlink privileges, LocalStack integration opt-in, or Docker Engine integration opt-in. No real provider requests or deployment actions were run.

## AWS connection and deployment improvements — 2026-11-27

| Exact command | Observed result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest tests/test_aws_management.py tests/test_aws_integration.py -o addopts="" -q` | 20 passed, 1 LocalStack opt-in skipped |
| `.\.venv\Scripts\python.exe -m pytest tests/test_ui.py -o addopts="" -q` | 29 passed |
| `.\.venv\Scripts\python.exe -m pytest -o addopts="" -ra` | 192 passed, 3 skipped in 50.45s |
| `.\.venv\Scripts\python.exe -m compileall -q aidevops tests` | PASS |
| `git diff --check` | PASS |

AWS connection failures now distinguish expired/missing SSO credentials and provide a safe refresh instruction. AWS authorization failures identify the rejected operation and the relevant permission category without returning AWS error details. Static S3 assets upload concurrently with a hard limit of eight workers. No AWS resources were created or modified; the current local SSO token could not be retrieved during read-only account verification.
