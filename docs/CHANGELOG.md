# Changelog

Newest first. Entries record date, summary, affected files, reason, checks run,
and outcome. Failures are appended as corrections, never rewritten away.

## 2026-10-23 — Fix application detection and frontend Docker startup

Confirmed actual user React/CRA failure: generic Node image omitted the frontend compile/serve step and started a nonexistent Node entry, with wrong default preview port. Added evidence-based frontend/runtime strategies across CRA,Vite,Next,Node,Python web apps and plain static sites; retained existing Dockerfiles; choose a single nested app root or explain ambiguity; unknown/unlaunchable projects fail actionably. New runtime metadata flows into generator and preview defaults. Browser bundles include build-time dependencies; production assets use unprivileged Nginx8080 with SPA routing and normalized asset base. Node custom build/start scripts and FastAPI/Flask application objects are honored. Added live bounded build-log updates and separate configurable600s build timeout.

Changed: analyzer/analyzer.py,models.py,planner/planner.py,generator/artifacts.py,services/pipeline.py,services/preview.py,execution/runner.py,config.py,ui/preview_panel.py,ui/streamlit_app.py,.env.example. Added tests/test_frontends.py and tests/smoke_frontends.py; docs/todo-working.png captures actual app interaction. Updated required documentation. Existing user source/old reviews/snapshots preserved; a fresh local-only review and30-minute preview demonstrate the corrected todo app.

Checks: `.\.venv\Scripts\python.exe -m pytest -o addopts="" -rs` →123 passed,1 skipped (Windows symlink privileges); compileall/pip check passed. `.\.venv\Scripts\python.exe tests/smoke_frontends.py --source "C:\Users\abhishek a\Downloads\todo_react_app-master\todo_react_app-master"` →actual CRA app image/HTML/JS/SPA route passed, disposable resources removed. `.\.venv\Scripts\python.exe tests/smoke_frontends.py` →static,Vite,Flask,FastAPI image builds and HTTP checks passed, disposable resources removed. Browser actual todo preview rendered and created a task. Next production strategy is unit-tested only; no new live claims for Java/Go/Rust/Django/Streamlit.

Development test failures: port-reconciliation assumption text and a Next executable-path assertion changed with the new behavior; corrected and full suite rerun. Initial inspection script hit Windows console Unicode output while displaying old logs; no source or runtime state was changed by that read failure. These checks do not establish universal support for arbitrary repositories/private services/invalid source. Existing Dockerfile paths still need inputs allowed by snapshot filtering.

## 2026-10-23 — Snapshot-approved image builds and local previews

Implemented the existing user's approved next milestone: shared outbound AI privacy filtering, an after-analysis request preview, local-only mode/trusted HTTPS provider settings; immutable filtered source+artifact build snapshots; separate build and startup approvals; background image builds with independent image/label verification; local127.0.0.1 previews and startup HTTP health probes; stop/cancel/expiry, restart reconciliation and label-guarded cleanup. Runtime limits and bounded build logs apply; runtime logs are withheld to avoid arbitrary secret output. Optional runtime environment is ephemeral input, not stored in job/preview records. UI polls every2s during build/start and every10s for running previews and provides build/start/open/stop/remove controls. No cloud actions or live AI requests were performed.

Changed: config.py, db.py, api/main.py, execution/runner.py and registry.py, planner/planner.py and provider.py, ui/streamlit_app.py, legacy generator.py, .env.example, tests/test_ui.py. Added: privacy.py, services/preview.py, ui/preview_panel.py, tests/test_preview.py, tests/smoke_preview.py. Updated all required project documentation. Legacy image-build tool now directs callers to the snapshot workflow; normal review contracts remain unchanged. Existing database connections now close explicitly.

Baseline:89 passed,1 skipped. A development full run found a UI fake/response-shape mismatch; added list validation and covered new controls. Initial real Docker smoke achieved Python/Node READY and expected build/start failures but exited with a Windows temporary database file lock. Root cause: SQLite context managers commit but do not close connections. Explicit connection close in both stores fixed it. Subsequent real smoke exited0 and removed all smoke-owned resources.

Verification commands:
- `.\.venv\Scripts\python.exe -m pytest -o addopts="" -rs` →108 passed,1 skipped (Windows symlink privileges).
- `.\.venv\Scripts\python.exe -m compileall -q aidevops tests generator.py` →exit0.
- `.\.venv\Scripts\python.exe -m pip check` →No broken requirements found.
- `.\.venv\Scripts\python.exe tests/smoke_preview.py` →Python and Node image builds/HTTP200 previews/stops passed; intentional BUILD_FAILED and START_FAILED classified correctly; all smoke-owned images/containers/snapshots removed; exit0.
- Existing idle local backend identity verified, restarted on127.0.0.1:8000; live health/preview-list/prompt-preview routes checked. No existing jobs or user source were deleted.

Limits: single API process per data directory (OS lock); max2 active operations/20 snapshots; expiry needs running backend; startup HTTP check is not ongoing app correctness monitoring. Docker builder cancellation/resource isolation remains best effort; base images/shared build cache are not pruned. Runtime envfile inherits Windows ACLs and Docker metadata retains values until container removal. Secret detection/redaction remains heuristic. Original review endpoints remain synchronous. Broader cloud deployment and production monitoring are still planned.

## 2026-10-22 — Guided interface for nontechnical users

Replaced the dense Streamlit dashboard with a calm mint/green, three-step experience: Add your project → Review your setup → Run your checks. Main onboarding offers upload/folder tabs, folder-location help, a bundled example, and recent project navigation. Status names explain the next action. Technical evidence, commands, file contents and logs remain available in expanders. Download all setup files creates a real ZIP in memory. Explicit per-project consent and environment availability gate checks; no deployment capability is implied. Offline/reconnect, failure, no-tests, incomplete analysis and stopped states have plain-language guidance.

Added subtle CSS entrance, hover and decorative pulse animations with prefers-reduced-motion support; responsive three-step layout, visible keyboard focus and local system fonts (no external assets). Developer Deploy control is hidden via Streamlit viewer toolbar mode. New project resets recent selection; archive and API contracts are preserved.

Files: aidevops/ui/streamlit_app.py (redesigned), aidevops/ui/presentation.py and styles.css (new), .streamlit/config.toml, tests/test_ui.py. Documentation: README, PROJECT_MEMORY, IMPLEMENTATION_STATUS, ARCHITECTURE, DECISIONS, TESTING and this CHANGELOG. Tool/backend contracts unchanged.

Checks: `.\.venv\Scripts\python.exe -m pytest tests/test_ui.py -o addopts="" -q` → 12 passed; final `.\.venv\Scripts\python.exe -m pytest -o addopts="" -rs` → 89 passed, 1 skipped in 7.87s; `.\.venv\Scripts\python.exe -m compileall -q aidevops tests` → pass. Browser verified the existing localhost:8501 desktop welcome screen, folder-tab interaction/blank-folder validation, opening an existing review and return to onboarding. No project checks, deployment or new live AI call were initiated by browser testing. Automated approval/example coverage uses faked HTTP.

A background preview-server start was rejected by automatic approval review (reason: blocked by policy); existing API/UI servers were subsequently discovered on 8000/8501 and used for read-only/browser navigation checks. Desktop screenshot inspected. Mobile/assistive-technology/reduced-motion behavior is implemented but not independently browser-tested.

## 2026-10-22 — Functional/security audit and regression fixes

Baseline observed 65 passed, 1 skipped. The baseline passed despite a false-success defect: only Dockerfile lint failures affected final job outcome.

- services/pipeline.py: all non-OK scheduled results fail verification; persist exception reasons; policy errors cannot leave EXECUTING; stop before subsequent tools after cancellation.
- db.py: atomic BEGIN IMMEDIATE phase transitions reject duplicate work across store instances; conditional saves refuse stale state overwrites after cancellation. Same-state updates remain without revision checks.
- execution/policy.py, runner.py: per-invocation timeout capped by tool/global settings; bounded retained subprocess output while draining; CPU/memory/PID/capability controls; uniquely named test container removal attempted after timeout.
- execution/registry.py: known-secret/symlink/cache/VCS-filtered bounded snapshots, read-only host mount and disposable writable container copy. Stop on dependency installation failure; Python supports pyproject-only install; Node respects package-lock. This fixes read-only build directories and hidden install errors. Python/Node live execution passed.
- analyzer/analyzer.py: malformed package.json values no longer crash dependency extraction.
- api/main.py: bounded UploadFile read before processing (does not replace upstream multipart/ingress quotas).
- planner/provider.py: disable SDK retries so application retry budget is not multiplied.
- generator/validators.py: secret diagnostics redact match values.
- generator/artifacts.py: copy package source before pip install .; install pytest in generated Python CI; correct Maven skipped-tests note.
- ui/streamlit_app.py: recent-list selection no longer replaces newly created job; only offer Run in PENDING; surface cancel errors; failed pipeline gets error feedback; failed/cancelled state stepper no longer marks all phases completed; escape repository/HTML values.
- tests/test_api.py, tests/test_execution.py, tests/test_ui.py updated; tests/test_audit_regressions.py and tests/smoke_local.py added. No dependencies changed or files deleted.
- Documentation synchronized: PROJECT_MEMORY.md, README.md and all eight files under docs/ (architecture, implementation status, changelog, decisions, tools, testing, security, roadmap).

Final checks: `.\.venv\Scripts\python.exe -m pytest -o addopts="" -rs` → 83 passed, 1 skipped (Windows symlink privileges); `.\.venv\Scripts\python.exe -m pip check` → no broken requirements; `.\.venv\Scripts\python.exe -m compileall -q aidevops tests` → exit 0. `docker info --format '{{.ServerVersion}}'` → 29.6.2. `.\.venv\Scripts\python.exe tests/smoke_local.py` → real temporary API Python+Node jobs SUCCEEDED with all three tool records OK; approval refusal checked; Streamlit health/HTML passed. No browser or cloud/live-LLM verification this session. A SyntaxWarning in the first smoke invocation was corrected by using a raw module docstring; final compileall passed.

Known remaining issues explicitly recorded: generated-only image-build context, crash-state reconciliation, synchronous requests/current-tool cancellation, cached Docker availability, archive cleanup/ingress limits, template heuristics and local-only unauthenticated API. Existing application files were untracked at audit start; no commit was created and no existing runtime state or credentials were modified.

## 2026-10-21 — Milestone 1: local analyze → plan → generate → validate → execute

**Summary.** Built the first working milestone of the Autonomous AI DevOps
Engineer on top of the existing AIDevOps Copilot prototype: a FastAPI backend, a
static repository analyzer with archive support, a schema-validated AI planner
with a labelled mock fallback, project-specific artifact generation into an
isolated workspace, validation with secret scanning, a controlled allowlisted
execution layer, a persisted job lifecycle with an approval gate, a Streamlit UI,
a pytest suite, and this documentation set.

**Files added**
- `aidevops/` — `__init__.py`, `config.py`, `logging_config.py`, `errors.py`,
  `models.py`, `db.py`
- `aidevops/analyzer/` — `__init__.py`, `analyzer.py`, `archive.py`
- `aidevops/planner/` — `__init__.py`, `provider.py`, `planner.py`
- `aidevops/generator/` — `__init__.py`, `artifacts.py`, `validators.py`,
  `workspace.py`
- `aidevops/execution/` — `__init__.py`, `policy.py`, `registry.py`, `runner.py`
- `aidevops/services/` — `__init__.py`, `pipeline.py`
- `aidevops/api/` — `__init__.py`, `main.py`
- `aidevops/ui/` — `__init__.py`, `streamlit_app.py`
- `tests/` — `conftest.py`, `test_models.py`, `test_analyzer.py`,
  `test_archive.py`, `test_planner.py`, `test_generator.py`, `test_execution.py`,
  `test_jobs_state.py`, `test_api.py`, `test_security.py`
- `docs/` — this file plus `ARCHITECTURE.md`, `IMPLEMENTATION_STATUS.md`,
  `DECISIONS.md`, `TOOL_REGISTRY.md`, `TESTING.md`, `SECURITY.md`,
  `ROADMAP.md`; `PROJECT_MEMORY.md`
- `examples/sample_python_app/` — demo repository
- `pyproject.toml`

**Files changed**
- `README.md` — refocused on the new system; legacy copilot section preserved.
- `requirements.txt` — added fastapi, uvicorn, pydantic, python-multipart,
  httpx, pytest.
- `.env.example` — documented all `AIDEVOPS_*` and provider variables.
- `.gitignore` — ignore `data/`, `*.db`, tooling caches.

**Reason.** Implement the first ~50% milestone described in the build prompt: a
narrow, working, tested end-to-end local slice rather than many incomplete
features.

**Checks run**
- `.venv\Scripts\python.exe -m pytest -o addopts="" -rs`
  → **50 passed, 1 skipped** (`test_symlink_is_not_followed`, needs symlink
  privileges on Windows).
- Installed new deps into `.venv`: fastapi 0.158.0, uvicorn 0.54, pytest 9.1.1,
  httpx 0.28.1.
- Live smoke test against `uvicorn` on port 8011:
  `/health` → 200 (`llm_mode=mock`, `docker_available=False`, `tool_count=4`);
  create job → 201; `run` → `AWAITING_APPROVAL`; artifacts
  `[Dockerfile, .dockerignore, docker-compose.yml, .github/workflows/ci.yml]`
  all verified; `execute {approved:false}` → 400; `execute {approved:true}` →
  `SUCCEEDED` with `container_test` recorded `BLOCKED` (Docker down).

**Outcome.** OK. No known-broken functionality. Container execution and the live
LLM path remain unverified because no Docker daemon / provider key is available
in this environment; both are labelled as such in `IMPLEMENTATION_STATUS.md`.

### 2026-10-21 — Follow-up polish (same session)

- `aidevops/analyzer/analyzer.py`: iterate `sorted(MANIFEST_FILES)` so
  `dependency_manifests` ordering is deterministic across runs (Python string
  hashing is randomized; set iteration order was not stable).
- `aidevops/execution/runner.py`: use `models.utcnow()` for execution
  timestamps instead of `datetime.now(tz=None).astimezone()` for consistency
  with the rest of the models.
- Reason: determinism and consistency; no behavior change.
- Checks: `python -m pytest -o addopts="" -q` → **50 passed, 1 skipped**.
- Outcome: OK.

### 2026-10-21 — Provider hardening for OpenAI-compatible gateways (e.g. OpenRouter)

- `aidevops/planner/provider.py`: added `_extract_json` (tolerates markdown-
  fenced and prose-wrapped JSON) and a `response_format` fallback — when a
  gateway rejects JSON mode, the provider retries once without it instead of
  dropping to a mock plan. Refactored the request into `_chat`.
- `tests/test_provider.py` (new): JSON extraction cases, the fallback retry, and
  `ProviderError` after retries. No network: the client is faked.
- `.env.example`, `README.md`, `PROJECT_MEMORY.md` §8: documented OpenRouter and
  other OpenAI-compatible gateways.
- Reason: the operator has an OpenRouter key and needs non-OpenAI models to work
  reliably; several OpenRouter models reject `response_format`.
- Checks: `python -m pytest -o addopts="" -q` → **58 passed, 1 skipped**.
- Outcome: OK. A **live** OpenRouter call is still not verified (no key in this
  environment); the fallback logic is covered by fakes only.

### 2026-10-21 — Live LLM planning verified against OpenRouter

- Configured `.env` with an OpenRouter key
  (`OPENAI_BASE_URL=https://openrouter.ai/api/v1`,
  `OPENAI_MODEL=minimax/minimax-m3.1-flash:free`).
- Ran a direct provider probe and `build_plan` against
  `examples/sample_python_app`.
- **Result:** direct call returned `{'ok': True}`; `build_plan` returned
  `PLAN_SOURCE: llm` with plausible, evidence-referencing assumptions. No key or
  secret was printed.
- Note: the long-running API server was not restarted during the probe, so it
  continued to report `llm_mode: "mock"`; a restart is required to serve live
  plans.
- Docs updated: `PROJECT_MEMORY.md` §3/§8/§14/§15/§16 (LLM path now VERIFIED,
  task removed from the queue), `docs/IMPLEMENTATION_STATUS.md` (planner rows).
- Outcome: OK. Remaining unverified area is container execution (needs Docker).

### 2026-10-21 — Reconcile LLM plans with detected evidence (artifact set + port)

- **Problem observed live:** with a real LLM plan, only `Dockerfile`,
  `.dockerignore` and the CI workflow were generated — no `docker-compose.yml` —
  because generation was driven solely by the plan's `artifacts` list, which the
  model had narrowed to `Dockerfile`.
- `aidevops/planner/planner.py`: `_cross_check` now fills `exposed_port` from
  `profile.declared_ports` when the plan omits it (recorded as an assumption),
  instead of leaving the port unset.
- `aidevops/generator/artifacts.py`: `build_artifact_contents` treats the plan's
  artifact list as a **floor, not a ceiling** — a detected port adds Compose, and
  detected tests with no existing CI add a workflow. Mock and LLM paths now
  behave consistently.
- Tests: `test_planner.py::test_llm_plan_missing_port_falls_back_to_detected_port`,
  `test_generator.py::test_evidence_adds_artifacts_the_plan_omitted`.
- Reason: the operator hit the gap in real use; an incomplete LLM plan should not
  silently produce fewer, less usable artifacts than the evidence supports.
- Checks: `python -m pytest -o addopts="" -q` → **60 passed, 1 skipped**. Live
  re-run against OpenRouter → `AWAITING_APPROVAL` with
  `[Dockerfile, .dockerignore, docker-compose.yml, .github/workflows/ci.yml]`
  all `verified=true`.
- Outcome: OK. Decision recorded as D7 in `docs/DECISIONS.md`.

### 2026-10-21 — UI redesign, root route, and a real container-execution fix

**UI/UX.** The Streamlit app was functional but visually plain and confusing: a
click produced a change below the fold with no loading state, which read as
"nothing happened".

- `.streamlit/config.toml` (new): light theme, brand primary colour, headless.
- `aidevops/ui/streamlit_app.py`: rewritten. Hero header, sidebar with
  connection chips + new-job form + recent-jobs picker, a state stepper, metric
  cards for analysis, a plan panel with an explicit `LLM-generated` /
  `MOCK · not AI output` badge, per-artifact tabs with validation issues,
  execution records as cards, and injected CSS for cards/chips.
- **Create + run pipeline** now runs the pipeline immediately with a live
  `st.status` progress panel, so one click produces obvious feedback; the
  redundant `st.rerun()` was removed (the same run already renders the new job).
- API errors are surfaced inline instead of blanking the page.
- `aidevops/api/main.py`: added `GET /` returning a service index (was a 404).

**Bug found by live execution.** `container_test` never worked:

1. It mounted the **generated-artifact workspace**, not the analyzed source
   repository — so no project code or tests were present.
2. The bare `python:3.12-slim` image ships no `pytest`, so `python -m pytest`
   failed with `No module named pytest`.

Fixes: `ExecutionContext` gained `source_path`; `run_container` gained
`mount`/`network`/`read_only`; `container_test` now mounts the source repo
**read-only** and uses a fixed per-language template that installs the test
runner (the only case where a container gets network). Recorded as D8.

**Tests.** `tests/test_ui.py` (new, 4 tests) drives the app headlessly with
Streamlit's `AppTest` against a faked HTTP layer — closing the "UI is only
verified by inspection" gap. `test_execution.py` gained a regression test that
the test tool mounts the source repo read-only.

**Checks.**
- `python -m pytest -o addopts="" -q` → **65 passed, 1 skipped**.
- Live, with Docker running: `container_test` → `ok`, exit 0, `1 passed in
  0.15s`, `container=true`, source mounted read-only; job reached `SUCCEEDED`.
- Live: `GET /` → 200 with the service index; UI on :8501 returns HTML.

**Outcome.** OK. Container execution is now VERIFIED (Python path). Remaining
gaps: per-tool timeouts are not enforced, and non-Python container paths are
untested.

2026-10-23 UI verification follow-up: desktop browser confirmed new controls; saved docs/local-preview.png. Adaptive polling avoids continuously rerendering an idle form. Backend health and new routes returned200.


## SaaS workspace refresh — 2026-10-23
Replaced the mint review page with a navy sidebar, indigo accents, soft neutral workspace, responsive hero and local CSS illustrations. Added subtle entrance/hover/floating animation with reduced-motion support and visible keyboard focus. Project screens open Build & preview first; Project overview, Setup files and Checks & results are separate tabs. Preview ports, HTTP path and expiry remain prefilled; optional configuration is under Advanced preview settings. Resource removal is collapsed. Existing backend APIs and explicit build/start/check approvals are preserved.
Validation: 124 passed, 1 Windows symlink privilege skip; includes 15 UI AppTests covering navigation, approvals and exact default launch payload. Existing local Streamlit server restarted to load changed imported module/theme. Browser inspected narrow-screen welcome and existing project navigation; no desktop-width or assistive-technology audit. This change does not claim new runtime coverage for generated apps.
