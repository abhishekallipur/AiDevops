# Implementation status

Updated 2026-10-22. Labels: VERIFIED = implementation and relevant observed check; IMPLEMENTED — NOT VERIFIED = code without successful check; PARTIAL = limited functionality; PLANNED = absent; BLOCKED = specific missing prerequisite; BROKEN = confirmed failure. Verification scope matters.

| Feature | Status | Evidence and limits |
|---|---|---|
| FastAPI routes, approval gate and persistence | VERIFIED | pytest API/state tests; real temporary-server Python+Node workflow via tests/smoke_local.py |
| Static Python/Node detection and malformed Node manifests | VERIFIED | analyzer and audit regression tests; heuristic, other runtimes not live checked |
| Archive guards | PARTIAL | traversal/link/bomb tests pass; rejection is not all-or-nothing cleanup; malformed archives may return generic errors |
| Symlink rejection | IMPLEMENTED — NOT VERIFIED | Windows symlink test skipped for privileges |
| Planner schema, mock labels, provider failures/gateway fallback | VERIFIED | unit tests; no provider network call this audit |
| Live AI provider | IMPLEMENTED — NOT VERIFIED | historical 2026-10-21 OpenRouter success in changelog; not repeated 2026-10-22 |
| Docker/Compose/CI generation and static validation | VERIFIED | generator tests; not a runtime/build verification |
| Package-source install order and pytest CI dependency | VERIFIED | audit generator regression test; no image/remote CI execution |
| Registry and approval boundaries | VERIFIED | execution tests and live HTTP refusal without approval |
| Sanitized test snapshot and writable container copy | VERIFIED | execution regression and live Python+Node tests |
| Test container resource flags | VERIFIED | argv regression; live Python+Node runs with flags; not penetration-tested |
| Subprocess timeouts and retained-output bounds | VERIFIED | real short-lived subprocess tests; tool timeout cap regression |
| Atomic state transitions and stale-state refusal | VERIFIED | duplicate, cancellation, cross-store transition regression tests |
| Success requires all scheduled checks OK | VERIFIED | parameterized outcomes, blocked API execution, live successful tests |
| Restart reconciliation and interrupting active tools on cancel | PLANNED | persistence exists; active tasks are not resumed or reconciled |
| Image building | PARTIAL | approval gate exists; generated-only build context lacks source; not scheduled by execute_job |
| Streamlit interactions | VERIFIED | 6 headless AppTest cases with fake HTTP; live health+HTML only |
| Browser responsiveness/accessibility | IMPLEMENTED — NOT VERIFIED | no browser interaction session |
| AWS/Terraform, CloudWatch, recovery | PLANNED | no implementation/execution |

Final commands/counts are in [TESTING.md](TESTING.md). Outstanding work is ordered in [PROJECT_MEMORY.md](../PROJECT_MEMORY.md).

## Latest UI verification — 2026-10-22
- VERIFIED: guided onboarding, plain-language labels, example flow, recent selection, input validation, mock disclosure, offline recovery, consent/environment gate and new-project navigation (12 AppTests).
- VERIFIED: existing desktop browser welcome rendering, folder tab/empty validation, opening an existing project review, return to onboarding.
- IMPLEMENTED — NOT VERIFIED independently: mobile layout, reduced-motion OS preference, assistive-technology compatibility, browser download content (ZIP construction is implemented).
- Final full suite: 89 passed, 1 Windows symlink skip in 7.87s. No backend or tool contract changes.
