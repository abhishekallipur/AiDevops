"""Autonomous AI DevOps Engineer.

A local-first, evidence-based assistant that analyzes a repository, produces a
deployment plan, generates DevOps artifacts, validates them, and can run a
narrowly scoped set of allowlisted checks.

The package is intentionally layered so that the LLM planner and the command
executor never share a trust boundary:

    analyzer  -> produces ProjectProfile from static evidence (never executes code)
    planner   -> produces DeploymentPlan (LLM-backed or clearly-labelled mock)
    generator -> writes artifacts into an isolated workspace
    execution -> runs only allowlisted tools, in a container when one is available
    api / ui  -> expose the job lifecycle
"""

__version__ = "0.1.0"
