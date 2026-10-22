# Architecture

## Component diagram

```
                 ┌─────────────────────────┐
  HTTP / UI ───▶ │  api/main.py (FastAPI)  │  routes, request-id, error mapping
                 └───────────┬─────────────┘
                             │ orchestrates
                 ┌───────────▼─────────────┐
                 │ services/pipeline.py    │  ONLY writer of job state
                 └───┬───────┬───────┬─────┘
                     │       │       │
        ┌────────────▼─┐ ┌───▼────┐ ┌▼──────────────┐
        │ analyzer/    │ │planner/│ │generator/     │
        │ static only  │ │  LLM   │ │ writes to     │
        │ no exec      │ │ or mock│ │ isolated WS   │
        └──────────────┘ └───┬────┘ └───────┬───────┘
                             │ provider     │ validators
                             ▼              ▼
                      openai-compatible   Dockerfile lint
                      (env credentials)   + secret scan
                     ┌──────────────────────────────────┐
                     │ execution/  registry + policy    │
                     │ allowlisted tools, limits, gates │
                     └──────────────────────────────────┘
                     ┌──────────────────────────────────┐
                     │ db.py  SQLite JobStore + states  │
                     └──────────────────────────────────┘
```

## Layers and their responsibilities

| Layer | Module | May do | May **not** do |
|---|---|---|---|
| Analysis | `analyzer/` | read files (bounded), detect, extract archives | execute code, follow symlinks, read secrets |
| Planning | `planner/` | call the LLM, validate schema | execute anything; touch the shell |
| Generation | `generator/` | write to the isolated workspace, validate | overwrite source files, write outside the workspace |
| Execution | `execution/` | run registry tools with limits | run arbitrary/LLM-supplied commands, mount the Docker socket |
| Orchestration | `services/pipeline.py` | mutate job state, sequence steps | bypass the state machine |
| API | `api/` | validate requests, map errors | contain business logic |

## Data flow (happy path)

1. `POST /api/jobs` → `JobStore.create` → state `PENDING`.
2. `run` → `analyze_and_plan`:
   - `ANALYZING`: `analyze_path` builds a `ProjectProfile` from evidence.
   - `build_plan` validates a `DeploymentPlan` (LLM) or builds a mock plan.
   - → `PLANNED`.
3. `generate_and_validate`:
   - `GENERATING`: `generate_artifacts` writes into
     `data/generated/<job_id>/` and validates each file.
   - `VALIDATING`: error-severity issues → `FAILED`; otherwise →
     `AWAITING_APPROVAL` (the approval gate).
4. `POST /api/jobs/{id}/execute {approved:true}`:
   - `EXECUTING`: `run_tool` for each planned tool; every call recorded.
   - `VERIFYING`: lint results checked.
   - → `SUCCEEDED` (or `FAILED`).

## State machine

```
PENDING ─▶ ANALYZING ─▶ PLANNED ─▶ GENERATING ─▶ VALIDATING ─▶ AWAITING_APPROVAL
                                                    │                    │
                                                    ▼                    ▼
                                                  FAILED             EXECUTING ─▶ VERIFYING ─▶ SUCCEEDED
                                                                                              └─▶ FAILED
Any non-terminal state may also go to CANCELLED. SUCCEEDED/FAILED/CANCELLED are terminal.
```

Defined in `aidevops/models.py` (`ALLOWED_TRANSITIONS`) and enforced by
`JobStore.transition`, which appends to each job's `history`.

## Trust boundaries

- **Untrusted:** repository contents, uploaded archives, LLM output.
- **Trusted:** the application code, the tool registry, and the allowlist.
- The planner and executor are deliberately separated: a plan's `command` fields
  are advisory strings for a human, never fed to a shell.
- All untrusted code execution is deferred to containers; when no daemon is
  available the system blocks and reports rather than degrading to host
  execution.

## Extension points (intentionally not implemented)

- **AWS/Terraform:** `DeploymentPlan.steps` already contains a gated `deploy`
  step; a `generator/terraform.py` can follow the same write-validate pattern.
- **Monitoring:** a read-only `execution` tool could query CloudWatch with the
  same timeout/limit/approval machinery.
- **Recovery:** bounded actions should be new registry tools with approvals, not
  free-form commands.

## 2026-10-22 audit corrections

Execution verification now requires every scheduled record to be OK, including container tests. BLOCKED/TIMEOUT/ERROR results cause FAILED with a persisted reason. SUCCEEDED confirms scheduled checks only; image building/deployment is not part of execute_job. Policy/tool exceptions after phase entry persist FAILED rather than leaving active states.

JobStore transitions use BEGIN IMMEDIATE to claim phases atomically; duplicate entry is a conflict. save requires the database state to match the document state, preventing stale saves from reviving cancelled work. This is not full revision-based optimistic concurrency. Cancellation stops subsequent tools, not a currently running subprocess. Active jobs are not reconciled on restart; synchronous routes remain unchanged.

Test execution now snapshots filtered source into a temporary host directory, mounts it read-only and copies to writable /tmp/project in the container. Resource limits apply to docker run; retained subprocess output is bounded; named cleanup is attempted after timeout. The separate image-build tool still points at generated-only output and needs a safe combined build context. See TOOL_REGISTRY.md and SECURITY.md for exact boundaries.

## Guided UI layer — 2026-10-22
The Streamlit client now separates plain-language display mappings (ui/presentation.py) and local responsive/animation styling (ui/styles.css) from HTTP actions (ui/streamlit_app.py). Internal states map to three user-facing stages without changing backend states. Technical details use collapsed expanders. File bundles are generated in memory from the actual artifact response; no source files are modified. Approval remains an explicit API request after per-project user consent, and unavailable test environments disable the run action.
