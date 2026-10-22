# Testing

Current verification: 2026-10-22, Asia/Calcutta. All commands from E:/Aidevops in PowerShell.

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

Not run: browser interactions/mobile/accessibility, live LLM/provider requests in this audit, generated image builds/health checks, remote GitHub Actions, Terraform validation/plan/apply, AWS/CloudWatch/recovery, SAST/dependency vulnerability scans. No frontend production bundle exists (Streamlit). No lint/type/format tool is configured; these checks are not claimed as passing. pip check checks installed dependency consistency, not vulnerabilities.

Historical 2026-10-21 live AI/container checks are retained in CHANGELOG.md. They are historical observations, not repeat checks of this revision.

## UI redesign verification — 2026-10-22 (supersedes earlier final count)
- `.\.venv\Scripts\python.exe -m pytest tests/test_ui.py -o addopts="" -q`: 12 passed.
- `.\.venv\Scripts\python.exe -m pytest -o addopts="" -rs`: 89 passed, 1 skipped in 7.87s (same Windows symlink privilege skip).
- `.\.venv\Scripts\python.exe -m compileall -q aidevops tests`: passed.
- Existing desktop browser at localhost:8501: welcome screen inspected visually; folder tab, empty-form feedback, existing review selection and new-project navigation confirmed. No new execution or live AI request was triggered by browser testing.
- Mobile layouts, OS reduced-motion settings, screen readers and browser ZIP contents were not independently tested. Previous live Docker smoke evidence belongs to the preceding backend audit; no runtime/tool changes were made by this UI redesign.
