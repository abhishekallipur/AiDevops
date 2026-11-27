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

## Phase 3 — AWS deployment (typed and approval-gated)

- Implemented: verified static images can deploy to S3; server images can publish
  to ECR and run on configured EC2. A project-type recommendation precedes a
  separate deployment approval and public-access confirmation.
- Implemented: AWS access defaults to LocalStack with dummy credentials; AWS mode
  is explicit. SDK calls are typed and do not execute model-produced commands.
- Follow-up: add Terraform artifact/plan review, narrower per-action permission
  scoping, and independently verified rollback/cleanup. Current success paths are
  not yet verified against LocalStack or real AWS.

## Phase 4 — Monitoring and verification

- Implemented: administrator-only account status, EC2/S3 inventory, bounded
  CloudWatch CPU metrics, and persistent Aidevops deployment status.
- Follow-up: add deployment health checks, S3 object/traffic metrics, stopped
  instance controls, and localstack/real-account verification with recorded
  evidence.

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

## Updated priorities — 2026-10-23

Local snapshot/build/start/HTTP-check/stop/cleanup is now implemented and real Python+Node workflows verified. Preview background work, explicit approvals, expiry and restart reconciliation are implemented; original analyze/run/execute remains synchronous.

Next: stronger runtime secret transport/OS ACLs and detection; browser/mobile/full workflow QA; continuous HTTP health checks; isolated builder resource/network controls and version-pinned reproducible builds; original-review background workers/crash reconciliation; then approval-gated cloud deployment and rollback. Runtime logs are intentionally withheld. AWS/Terraform/CloudWatch/recovery remain PLANNED.

## Broader project support — 2026-10-23

Actual CRA todo startup fixed and browser-verified; Vite/static/Flask/FastAPI live fixtures added. Next and other conventional runtime strategies need additional live fixtures. Remaining: Yarn/pnpm and workspace-aware installs,custom frontend output/base patterns,Next export/standalone modes,Python application factories,Java/Go/Rust live coverage,multi-service/database orchestration and private dependency configuration. Arbitrary files or incomplete repositories are not runnable applications; surface requirements rather than guarantee all inputs work.
