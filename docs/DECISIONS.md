# Decisions

Material architectural/tooling decisions. Each records alternatives, reason,
trade-offs, and the condition that would justify revisiting it.

## D1 — SQLite with a JSON document per job (2026-10-21)

- **Decision:** Persist each job as one JSON `JobRecord` in a `jobs` table with a
  few indexed scalar columns, rather than normalized relational tables.
- **Alternatives:** Postgres; fully normalized SQLite schema; in-memory only.
- **Reason:** The MVP has one writer and document-shaped payloads; JSON keeps the
  store migration-free while the schema is still moving.
- **Trade-offs:** No cross-job SQL querying of nested fields; full-document writes.
- **Revisit when:** multiple writers, concurrent jobs, or a need to query nested
  fields arises.

## D2 — Execution only through an allowlisted tool registry (2026-10-21)

- **Decision:** The executor can run only tools defined in
  `aidevops/execution/registry.py`. LLM-proposed commands are advisory text.
- **Alternatives:** Let the model propose shell commands and validate them with a
  blocklist; a generic sandboxed shell.
- **Reason:** A blocklist is trivially bypassed; an allowlist with typed arguments
  makes the safe set explicit and auditable.
- **Trade-offs:** Adding capability requires a code change; fewer ad-hoc actions.
- **Revisit when:** a declarative tool-definition format is introduced.

## D3 — Labelled mock fallback instead of failing without a provider (2026-10-21)

- **Decision:** With no provider key (or on provider failure), return a
  deterministic plan with `source="mock"` and an explanatory assumption.
- **Alternatives:** Hard-fail; return an empty plan; hide the fallback.
- **Reason:** The app must be demonstrable and testable offline, but mock output
  must never be mistaken for AI output.
- **Trade-offs:** Callers must check `source` to know what they got.
- **Revisit when:** a second real provider is added — the reliability of the
  fallback label should be re-verified.

## D4 — Generated artifacts live in an isolated workspace (2026-10-21)

- **Decision:** All generated files go under `data/generated/<job_id>/`, never
  into the analyzed repository.
- **Alternatives:** Write next to the source files; write only on accept.
- **Reason:** Silent overwrites of user files are unacceptable; a separate
  workspace makes preview/approval straightforward.
- **Trade-offs:** The user must copy artifacts into place.
- **Revisit when:** an explicit "apply to repository" flow with diff/approval is
  built.

## D5 — Container isolation required for untrusted code; block otherwise (2026-10-21)

- **Decision:** Container tools refuse to run when no Docker daemon is reachable,
  recording `BLOCKED` instead of falling back to host execution.
- **Alternatives:** Run on the host; best-effort sandboxing.
- **Reason:** Running untrusted repository code on the host is a serious risk with
  no reliable mitigation on Windows.
- **Trade-offs:** Less functionality when Docker is down.
- **Revisit when:** a rootless/VM isolation backend is added.

## D8 — Test tools mount the source repo read-only; only they get network (2026-10-21)

- **Decision:** `ExecutionContext` carries both the generated-artifact
  `workspace` and the `source_path`. `container_test` mounts the source at
  `/workspace` **read-only** and is the only tool allowed `--network bridge`,
  because bare language images ship no test runner.
- **Alternatives:** Mount the source read/write; bake custom per-language test
  images; drop container testing and stay lint-only.
- **Reason:** Live execution showed the tool mounted the wrong directory (so
  there was nothing to test) and then failed on a missing `pytest`. Mounting
  read-only keeps a test run from mutating the user's project; requiring network
  only for dependency installs keeps isolation for the rest.
- **Trade-offs:** Test runs can fetch third-party packages, which is a real risk
  for untrusted repositories (documented in `docs/SECURITY.md`). Some ecosystems
  may not work with a read-only mount.
- **Revisit when:** purpose-built toolchain images are available per language, at
  which point network can be removed from test runs.

## D7 — The plan's artifact list is a floor, not a ceiling (2026-10-21)

- **Decision:** Generation is evidence-driven. A detected port always adds
  `docker-compose.yml`, and detected tests with no existing CI always add a
  workflow, even if the LLM plan did not list them.
- **Alternatives:** Trust the plan's list exactly; always generate every artifact
  type; let the user select artifacts manually.
- **Reason:** A live LLM plan narrowed its list to `Dockerfile`, so a repository
  with a known port and tests got fewer artifacts than the evidence warranted.
  The analyzer already knows these facts; the mock path used them, so the two
  paths disagreed.
- **Trade-offs:** The generated set can be larger than the plan literally says;
  the plan's list is therefore intent, not a contract.
- **Revisit when:** users want explicit artifact selection, in which case the
  choice should move to an explicit request field rather than plan inference.

## D6 — Keep the legacy AIDevOps Copilot package separate (2026-10-21)

- **Decision:** Preserve `app.py`, `rag.py`, `generator.py`, `knowledge/`
  unchanged; the new system is a separate `aidevops/` package.
- **Alternatives:** Delete the prototype; refactor it into the new package.
- **Reason:** It works and is unrelated to the analyzer/planner pipeline;
  preserving it avoids regressions and lost work.
- **Trade-offs:** Two Streamlit entry points and some duplicated intent.
- **Revisit when:** the RAG knowledge base is repurposed as planner context.

## D9 — Fail verification on incomplete scheduled checks (2026-10-22)

All scheduled tools must return OK; blocked infrastructure cannot count as successful validation. Use existing FAILED state with detailed reason instead of adding an incompatible state. Success says only scheduled checks passed, not that deployment/build happened. Exception reasons are persisted before transitioning.

## D10 — Filtered snapshots and disposable writable test copies (2026-10-22)

Mounting raw source exposed .env/credential files to dependency scripts and read-only mounts broke tools writing node_modules/build outputs. Reuse bounded analyzer filtering for a disposable host snapshot, mount read-only, and copy inside the container. Keep network for dependency installation, explicitly acknowledge tests also have it, and add resource/capability limits. Denylist filtering and race resistance are not a complete secret/isolation guarantee.

## D11 — Atomic phase claims without changing synchronous API (2026-10-22)

Use SQLite write transactions for transitions and reject same-state phase entry; reject saves whose state is stale. This prevents duplicate starts and cancellation resurrection while preserving current API/UI contracts. Background workers, revision checks and restart reconciliation remain separate follow-ups.

## D12 — Guided nontechnical UI with progressive disclosure (2026-10-22)
Keep Streamlit and existing API contracts; replace the developer-heavy dashboard with a three-step journey and meaningful next actions. Upload/example are first-class entry points; technical plans/logs/files stay accessible in expanders. Use actual backend data with explicit example/AI distinctions. Animations are decorative and respect reduced motion, never simulate workflow progress. No framework migration or new hosting service is needed.
