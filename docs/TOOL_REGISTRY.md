# Tool registry

Updated 2026-10-22. Registry-only execution; LLM plan commands never reach a shell. API execution always needs human approval. Tool argument schemas are Pydantic models; unknown tools are refused.

| Tool | Kind / arguments | Approval | Limits / behavior |
|---|---|---|---|
| list_workspace | in-process read-only / {} | tool: no | generated workspace listing; declared 10s (not preemptive) |
| dockerfile_lint | in-process read-only / {path: "Dockerfile"} | tool: no | workspace path guard, static lint; declared 10s (not preemptive) |
| container_test | Docker runtime / {} | API: yes | min(global timeout, 300s); filtered snapshot :ro; writable copy in /tmp/project; bridge network |
| container_build_image | docker build / {} | yes | min(global timeout, 600s); generated workspace context; PARTIAL: source absent, not scheduled by normal workflow |

Global timeout defaults to 120s. run_tool copies its context and selects the smaller global/tool timeout without mutating the caller. Subprocess output retains at most AIDEVOPS_EXEC_MAX_OUTPUT_BYTES bytes while draining further output. Read-only Python handlers do not have a forced wall-clock timer.

Test snapshots use analyzer skip rules and bounds; known secrets, symlinks, VCS and caches are omitted. Oversized snapshots block rather than test a partial tree. Sources must remain stable while snapshotting. Denylist filtering cannot prove absence of credentials. No host environment credentials, home directory or Docker socket are passed to the container. Test containers use --rm, unique names, --memory 1g, --cpus 2, --pids-limit 256, --cap-drop ALL, --security-opt no-new-privileges. A timeout attempts docker rm --force with a 10s cleanup deadline; daemon failure can prevent cleanup.

Python installs requirements.txt or pyproject.toml, then pytest; Node uses npm ci with package-lock.json, otherwise npm install. Dependency errors stop execution instead of being swallowed. Maven/Gradle/Go/Rust retain fixed registry commands. All commands run on a disposable writable in-container copy; Python/Node were live verified on 2026-10-22. Other runtimes remain unverified. Network is available to the whole test container, including tests, not only package installation.

Records contain tool, args, status, timestamps, output, exit code and reason. Any non-OK scheduled result fails job verification. SUCCEEDED means only the scheduled checks passed, never a deployment or image health claim.

To add a tool, define typed arguments, fixed handler/argv, kind, permissions, approval and limits; add policy and failure tests; update memory, security docs and this catalog.
