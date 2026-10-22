# Security

Updated 2026-10-22. Local single-user application; no authentication, authorization or rate limiting. Bind API/UI to loopback. Never expose this service to untrusted networks.

Repository/archive contents and model responses are untrusted. Static analysis executes no code, skips known sensitive paths and symlinks, and applies file/depth/read bounds. Archives reject traversal, absolute paths, links and oversized content. Rejection can leave partial extracted data; multipart spooling occurs before endpoint reads, so bounded UploadFile.read is not a complete ingress quota. Malformed archive normalization and cleanup remain open.

Planning uses schema validation, labelled mock fallback and bounded provider retries. SDK retries are disabled to avoid multiplying configured attempts. Proposed commands are advisory. Artifact values are sanitized and statically scanned for secrets; diagnostics redact matching values. These checks are heuristic, not proof of a safe or buildable configuration.

Execution is registry-only. Human API approval is required; image builds require a tool approval too. Docker tests use filtered temporary source snapshots, read-only mounts and writable in-container copies. Known credential paths, VCS/caches and symlinks are omitted; no host environment credentials or Docker socket are passed through. A 1 GiB memory limit, 2 CPU limit, 256 PID limit, dropped capabilities and no-new-privileges apply to runtime test containers. Source changes during snapshotting and secrets with unusual names remain risks; only run trusted/approved projects. Test/dependency network access can exfiltrate any data present in the snapshot. It is not restricted to package hosts.

Subprocess output capture retains bounded memory, deadlines are capped by global/tool limits, and timed-out test containers receive a named force-removal attempt. Docker daemon failure can defeat cleanup. These runtime controls do not establish equivalent isolation/resource bounds for docker build. Building uses a generated-only context and remains PARTIAL; normal execute_job does not invoke it.

Atomic SQLite transitions reject duplicate phase entry; stale-state saves cannot overwrite cancellation. Cancellation does not interrupt the current subprocess and restart does not reconcile active jobs. Same-state concurrent saves lack revision checks. Local paths default enabled and are operator-selected rather than constrained by an enforced allowlist of roots.

.env and data/ are ignored. Do not print secrets or persist provider responses/errors containing them. Secret scanning uses a denylist/regex and cannot guarantee absence. Arbitrary test output can itself contain sensitive data and is persisted; generic output redaction is not implemented. No dependency-vulnerability/SAST scan was run.

No production/cloud/destructive operations were performed. Future infrastructure, permission or destructive actions must have explicit approval and independent verification.
