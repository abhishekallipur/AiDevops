"""Plain-language display helpers. No workflow or API behavior lives here."""
from html import escape

STATUS = {
    "PENDING": ("Ready to start", "Choose Start review to continue.", "info", 0),
    "ANALYZING": ("Getting to know your project", "We are reading the project files.", "info", 1),
    "PLANNED": ("Your plan is ready", "Continue to prepare your setup files.", "info", 1),
    "GENERATING": ("Preparing your setup", "We are creating setup files for your project.", "info", 1),
    "VALIDATING": ("Reviewing the setup files", "We are checking the generated files for common issues.", "info", 1),
    "AWAITING_APPROVAL": ("Ready for your review", "Look over the setup below, then decide whether to run checks.", "info", 2),
    "EXECUTING": ("Running your checks", "Checks are running in a temporary environment. This may take a few minutes.", "info", 2),
    "VERIFYING": ("Reviewing the results", "We are checking the outcome of each completed task.", "info", 2),
    "SUCCEEDED": ("Your checks passed", "The scheduled checks passed. Your project has not been published or deployed.", "ok", 3),
    "FAILED": ("This review needs attention", "Some work failed or could not run. See what needs attention below.", "warn", None),
    "CANCELLED": ("Review stopped", "No further checks will start. A check already running may still finish.", "warn", None),
}
FILES = {
    "Dockerfile": ("App packaging", "Instructions for packaging your app into a portable environment."),
    ".dockerignore": ("Files to leave out", "Keeps unnecessary files and known private file types out of the package."),
    "docker-compose.yml": ("Local launch setup", "Describes how the packaged app would run on your computer."),
    "ci_workflow": ("Automatic check setup", "A starting point for running checks when code changes on GitHub."),
}
TOOLS = {"list_workspace": "Setup files found", "dockerfile_lint": "Packaging instructions reviewed", "container_test": "Project tests", "container_build_image": "App package build"}
RESULTS = {"ok": "Passed", "error": "Needs attention", "blocked": "Could not run", "timeout": "Took too long"}


def status(state):
    return STATUS.get(state, ("Status unavailable", "Refresh to check for an update.", "warn", None))


def badge(text, kind="info"):
    return f'<span class="aid-badge {kind}">{escape(str(text))}</span>'


def journey(state):
    active = status(state)[3]
    items = []
    for index, (title, detail) in enumerate([
        ("Add your project", "Upload or choose a folder"),
        ("Review your setup", "See what we prepared"),
        ("Run your checks", "Only with your approval"),
    ]):
        cls = "done" if active is not None and index < active else "current" if index == active else ""
        marker = "&#10003;" if cls == "done" else str(index + 1)
        items.append(f'<div class="aid-stage {cls}"><span class="aid-number">{marker}</span><div><b>{title}</b><small>{detail}</small></div></div>')
    return '<div class="aid-journey" aria-label="Your project review steps">' + ''.join(items) + '</div>'
