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

## Local build/preview release — 2026-10-23 (supersedes earlier absent-feature rows)

| Feature | Status | Evidence/limit |
|---|---|---|
| Approved filtered source+artifact snapshot | VERIFIED | snapshot/hash/secret/exclusion tests; real sample builds |
| Background image build + independent Docker inspection | VERIFIED | real Python/Node smoke; build failure/duplicate/cancel tests |
| Separate startup approval + loopback HTTP preview | VERIFIED | real Python/Node HTTP 200; failed startup test |
| Stop/label-scoped cleanup | VERIFIED | real smoke removed containers/images/snapshots; foreign-container refusal test |
| Expiry and restart reconciliation | VERIFIED | unit tests; requires live backend; no continuous HTTP monitoring |
| Single process ownership and bounded operation count | VERIFIED | worker-lock test; fixed caps in service |
| Outbound AI redaction, approved HTTPS host check, local-only | VERIFIED | fake provider-boundary tests; no live AI call; heuristic coverage |
| Guided build/start UI approvals | VERIFIED | 2 new AppTests (14 UI tests total); full browser build interaction not repeated |
| Runtime settings | PARTIAL | temporary env file and Docker metadata retain local exposure; UI one optional setting/API up to 30 |
| Logs | PARTIAL | filtered bounded build logs; runtime logs withheld for privacy |
| Cloud deploy/production monitoring/rollback | PLANNED | no cloud execution |

Full final suite: 108 passed, 1 Windows symlink skip. Full commands in TESTING.md. Original review crash reconciliation and synchronous execution are not replaced by preview workers.

## Project strategy verification — 2026-10-23

| Strategy | Evidence |
|---|---|
| React/Create React App | VERIFIED: user's actual todo source built; HTML/JS/SPA route checks; browser created a task |
| Vite default output | VERIFIED: real Docker build, HTML/assets/SPA route |
| Static index.html | VERIFIED: real Docker build, HTML/assets/SPA route |
| Flask/FastAPI app objects | VERIFIED: real Docker builds and HTTP responses |
| Node start/main/custom build | VERIFIED: unit tests plus preceding plain Node live smoke; custom compiler path not live checked |
| Next production server | IMPLEMENTED — NOT VERIFIED live; generation unit test |
| Django/Streamlit | IMPLEMENTED — NOT VERIFIED live; conventional strategy code |
| Existing Dockerfile preservation/nested root/ambiguous root | VERIFIED: regression tests; arbitrary custom Dockerfiles not guaranteed |
| Java/Go/Rust | Previous template scope unchanged; not live verified in this update |

Full suite123 passed,1 Windows symlink skip. Unknown project inputs now fail with actionable configuration guidance. Multi-service orchestration/private registry credentials/custom build outputs still require explicit configuration.


## SaaS workspace refresh — 2026-10-23
Replaced the mint review page with a navy sidebar, indigo accents, soft neutral workspace, responsive hero and local CSS illustrations. Added subtle entrance/hover/floating animation with reduced-motion support and visible keyboard focus. Project screens open Build & preview first; Project overview, Setup files and Checks & results are separate tabs. Preview ports, HTTP path and expiry remain prefilled; optional configuration is under Advanced preview settings. Resource removal is collapsed. Existing backend APIs and explicit build/start/check approvals are preserved.
Validation: 124 passed, 1 Windows symlink privilege skip; includes 15 UI AppTests covering navigation, approvals and exact default launch payload. Existing local Streamlit server restarted to load changed imported module/theme. Browser inspected narrow-screen welcome and existing project navigation; no desktop-width or assistive-technology audit. This change does not claim new runtime coverage for generated apps.
