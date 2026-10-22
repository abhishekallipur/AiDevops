# DevOps workflow notes

## General workflow
A typical CI workflow checks out source code, installs dependencies, runs tests, builds an artifact, and records the result. Deployment should be a separate controlled step.

## Safety
- Never store credentials in source files.
- Use environment variables or a secret manager for secrets.
- Review generated pipeline and infrastructure code before running it.
- Prefer least-privilege credentials.
- Do not apply Terraform changes without reviewing terraform plan.
- Keep destructive operations behind explicit human approval.

## Troubleshooting
- Read the first meaningful error in the logs, not only the final failure line.
- Check dependency versions and required environment variables.
- Reproduce a failure with the smallest safe test.
