# Changelog

Newest first. Entries record date, summary, affected files, reason, checks run,
and outcome. Failures are appended as corrections, never rewritten away.

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
