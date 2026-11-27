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

## AWS deployment and monitoring

- Streamlit calls the administrator-protected `/api/aws` router; AWS credentials
  remain on the backend and never reach the browser.
- `AwsManagementService` is separate from preview and Docker management. It uses
  typed boto3 calls, a LocalStack-only default with dummy credentials, durable
  deployment/audit records, and read-only CloudWatch/EC2/S3 inventory.
- A verified static image can publish its bounded `index.html` asset tree to S3.
  Server images are pushed to ECR and launched on a configured EC2 AMI/profile.
  The analyzer supplies the recommendation; an explicit user approval and a
  separate public-access confirmation gate resource creation.
- This implementation does not generate Terraform. It uses a fixed set of SDK
  operations because the post-build flow needs to transfer an existing verified
  image and deploy to LocalStack/AWS. Infrastructure choices are not model-
  supplied commands. Cloud resource stop/delete and rollback remain future work.

## Extension points

- **Recovery:** bounded actions should be new typed operations with approvals,
  not free-form commands.

## 2026-10-22 audit corrections

Execution verification now requires every scheduled record to be OK, including container tests. BLOCKED/TIMEOUT/ERROR results cause FAILED with a persisted reason. SUCCEEDED confirms scheduled checks only; image building/deployment is not part of execute_job. Policy/tool exceptions after phase entry persist FAILED rather than leaving active states.

JobStore transitions use BEGIN IMMEDIATE to claim phases atomically; duplicate entry is a conflict. save requires the database state to match the document state, preventing stale saves from reviving cancelled work. This is not full revision-based optimistic concurrency. Cancellation stops subsequent tools, not a currently running subprocess. Active jobs are not reconciled on restart; synchronous routes remain unchanged.

Test execution now snapshots filtered source into a temporary host directory, mounts it read-only and copies to writable /tmp/project in the container. Resource limits apply to docker run; retained subprocess output is bounded; named cleanup is attempted after timeout. The separate image-build tool still points at generated-only output and needs a safe combined build context. See TOOL_REGISTRY.md and SECURITY.md for exact boundaries.

## Guided UI layer — 2026-10-22
The Streamlit client now separates plain-language display mappings (ui/presentation.py) and local responsive/animation styling (ui/styles.css) from HTTP actions (ui/streamlit_app.py). Internal states map to three user-facing stages without changing backend states. Technical details use collapsed expanders. File bundles are generated in memory from the actual artifact response; no source files are modified. Approval remains an explicit API request after per-project user consent, and unavailable test environments disable the run action.

## Local preview subsystem — 2026-10-23

PreviewService owns fixed Docker operations behind explicit API schemas. Its separate SQLite document store records snapshots, digest-bound approval, build/start phases, image/container identities, results and expiry without changing existing JobState contracts. Two worker threads perform build/start asynchronously; calls return 202. An OS file lock prevents multiple API processes sharing this preview data directory. Original review endpoints remain synchronous.

A filtered bounded source copy receives generated artifacts and is hashed before approval. Build rehashes before execution, creates a unique labelled image/tag and validates its Docker identity. Start uses the verified image ID, a separately approved port/path/environment and random loopback host port; owned-container inspection and bounded HTTP probing decide READY. Cleanup verifies labels and guarded snapshot location. A 10s watcher handles container presence and expiry while the server is running. Restart reconciliation does not replay side effects. Runtime environment values stay out of persistence; an ephemeral env file and Docker metadata still require OS-local trust.

privacy.py is a final egress boundary for both AI paths. It redacts known patterns/paths and validates configured HTTPS hosts. prompt_preview exposes the filtered planner prompt after analysis. Neither schema validation nor heuristic redaction guarantees safety against arbitrary secret formats or prompt injection.

## Runtime strategy inference — 2026-10-23

Analyzer reads bounded package metadata/Python AST without executing source; it records build tool, script names, application import, build output and serving recommendations. Nested-root resolution updates job.source_path so analysis and snapshot use the same source tree. Generator selects browser compile+static serving versus production Node or Python web commands; existing Dockerfile overrides template selection. Model command/base/port suggestions cannot override a recognized browser serving strategy. Preview persists recommended port/path and refines a single EXPOSE port from image inspection. Background build output is bounded/redacted and persisted during execution; UI polls only during active/running previews.
