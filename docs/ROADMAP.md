# Roadmap

Status is tracked in `docs/IMPLEMENTATION_STATUS.md`. This file describes future
phases and their acceptance criteria. Items here are `PLANNED` unless the status
doc says otherwise.

## Phase 1 — Local foundation (this milestone) ✅ done

Analyzer, planner (with labelled mock), generator, validation, controlled
execution, job lifecycle, UI, tests, docs.
Acceptance met: app starts; `/health` ok; sample repo analyzed without execution;
schema-validated or labelled-mock plan; Dockerfile + `.dockerignore` generated in
a separate workspace; validation results recorded; UI/API show plan/artifacts/
status; unapproved commands rejected; tests cover core behavior + an unsafe
input; docs accurate.

## Phase 2 — Harden the local workflow

- Initial git commit + CI for this repository (run `pytest` on push).
- Verify the live LLM planning path with a real provider key.
- Verify container execution with Docker running; add a slow-tool timeout test.
- Background/async job execution so `/run` and `/execute` return `202`.
- A UI smoke test.
- **Acceptance:** all checks green; container test and live LLM results recorded
  with evidence.

## Phase 3 — AWS deployment via Terraform (approval-gated)

- A real `generator/terraform.py` that produces reviewed `.tf` for a plan,
  mirroring the write-then-validate pattern.
- Read-only tool `terraform_fmt` / `terraform_validate`; **no `apply`** without an
  explicit, separate approval tool.
- **Acceptance:** generated Terraform passes `terraform fmt -check` and
  `terraform validate`; `plan` produces a summary; nothing is applied
  automatically; every step has an execution record.

## Phase 4 — Monitoring and verification

- Read-only CloudWatch/health tools behind the same registry, timeout, and
  approval machinery.
- Post-deploy health verification with recorded evidence.
- **Acceptance:** a deploy can be followed by a recorded health check; failures
  are surfaced, not swallowed.

## Phase 5 — Bounded recovery

- A small set of narrowly scoped, approved recovery actions (for example:
  restart a service, roll back to the previous image tag).
- **Acceptance:** every recovery action is an allowlisted tool, requires
  approval, is time-boxed, and is logged; no free-form remediation.

## Explicit non-goals for now

- Kubernetes orchestration.
- Multi-user authentication/authorization.
- Support for every language/framework.
- Unrestricted autonomous self-healing.

These are deferred deliberately: they are large surfaces that should not be
faked with shallow placeholders.

## Priority correction — 2026-10-22

Current audit delivered timeout/output tests, real Python+Node container execution, headless UI regressions and live API/UI HTTP smoke. Earlier checklist entries requesting first verification of those are historical. Remaining order:
1. Repair image-build source+artifact context and independently verify built images.
2. Background workers, restart reconciliation, active cancellation and revision-aware writes.
3. Refresh Docker availability; archive preflight/cleanup/ingress quotas; stronger source-root and secret boundaries.
4. Browser desktop/mobile/accessibility checks; other runtime fixtures and actual image/remote CI checks; reproducible dependency lock and security scans.
5. Review/commit existing untracked project and configure repository CI.
6. Only then extend approval-gated Terraform/AWS/monitoring/recovery with explicit authorization. None was implemented in this audit.
