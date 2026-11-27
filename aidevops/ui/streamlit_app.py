"""Guided Streamlit client: add a project, understand its setup, approve checks."""
from __future__ import annotations

import io
import os
import re
from html import escape
from pathlib import Path
import zipfile

import httpx
import streamlit as st

from aidevops.auth import SESSION_COOKIE
from aidevops.ui.aws_dashboard import render as render_aws_dashboard
from aidevops.ui.aws_management import render as render_aws_management
from aidevops.ui.aws_setup import render as render_aws_setup
from aidevops.ui.presentation import FILES, RESULTS, TOOLS, badge, status
from aidevops.ui.docker_dashboard import render as render_docker_dashboard
from aidevops.ui.preview_panel import render as render_preview_panel

API_URL = os.getenv("AIDEVOPS_API_URL", "http://127.0.0.1:8000").rstrip("/")
SAMPLE_REPO = str(Path(__file__).resolve().parents[2] / "examples" / "sample_python_app")
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}


def api(method, path, **kwargs):
    try:
        response = httpx.request(method, f"{API_URL}{path}", timeout=300, **kwargs)
    except httpx.HTTPError:
        return None, "We could not connect to the project service. Please try again."
    if response.status_code >= 400:
        try:
            payload = response.json()
        except (ValueError, AttributeError, TypeError):
            payload = {}

        detail = None
        if isinstance(payload, dict):
            detail = payload.get("detail") or payload.get("message")
            if isinstance(detail, list):
                detail = "; ".join(
                    str(item.get("msg") if isinstance(item, dict) else item)
                    for item in detail
                    if item is not None and (not isinstance(item, dict) or item.get("msg") is not None)
                ) or None

        if not detail:
            detail = "The service could not complete this request. Please try again."
        return None, str(detail)
    try:
        return response.json(), None
    except ValueError:
        return None, "The service sent an unreadable response. Please try again."


_SESSION_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,128}$")


def render_ai_assistant(api, session_cookie=None) -> None:
    if "assistant_messages" not in st.session_state:
        st.session_state["assistant_messages"] = []

    st.title("Aidevops assistant")
    st.caption(
        "Ask about your project or get live Docker and AWS status. Live infrastructure "
        "readings and allowlisted management actions require the configured administrator and "
        "are handled by the backend, not the AI provider."
    )
    st.info(
        "Try “Show EC2 CPU and RAM”, “List running containers”, or an exact command such as "
        "`aws stop i-0123456789abcdef0`. Termination and container removal require a second "
        "confirmation phrase. General questions use the configured AI provider; infrastructure "
        "commands do not."
    )

    messages = st.session_state["assistant_messages"]
    for message in messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    error = st.session_state.get("assistant_error")
    if error:
        st.error(error)

    prompt = st.chat_input("Ask Aidevops", max_chars=2000)
    if not prompt:
        return
    clean_prompt = prompt.strip()
    if not clean_prompt:
        return

    messages.append({"role": "user", "content": clean_prompt})
    headers = {}
    if isinstance(session_cookie, str) and _SESSION_TOKEN.fullmatch(session_cookie):
        headers["Cookie"] = f"{SESSION_COOKIE}={session_cookie}"
    with st.spinner("Checking the right source…"):
        response, error = api(
            "POST",
            "/api/assistant/chat",
            headers=headers,
            json={"messages": messages[-12:]},
        )
    if error:
        st.session_state["assistant_error"] = error
    else:
        messages.append({"role": "assistant", "content": response["reply"]})
        st.session_state.pop("assistant_error", None)
    st.rerun()


def new_project():
    st.session_state.pop("job_id", None)
    st.session_state["project_picker"] = None
    st.session_state["new_project"] = True


def select_project():
    st.session_state["job_id"] = st.session_state["project_picker"]
    st.session_state["new_project"] = False


def callout(title, text):
    st.markdown(f'<div class="aid-callout"><h3>{escape(title)}</h3><p>{escape(text)}</p></div>', unsafe_allow_html=True)


def prepare(job_id, route="run"):
    with st.status("Getting your project ready…", expanded=True) as progress:
        st.write("Reading your files, preparing a suggested setup, and reviewing it for common issues.")
        result, error = api("POST", f"/api/jobs/{job_id}/{route}")
        if error:
            progress.update(label="We could not finish this review", state="error")
            st.error(error)
            return
        title, _, _, _ = status(result["state"])
        progress.update(label=title, state="error" if result["state"] == "FAILED" else "complete")


def create_and_run(payload=None, files=None):
    with st.spinner("Adding your project…"):
        data, error = api("POST", "/api/jobs/upload" if files else "/api/jobs", **({"files": files} if files else {"json": payload}))
    if error:
        st.error(error)
        return
    st.session_state["job_id"] = data["id"]
    st.session_state["new_project"] = False
    prepare(data["id"])
    st.rerun()


st.set_page_config(page_title="Aidevops · Project workspace", page_icon="✳", layout="wide", initial_sidebar_state="expanded")
st.set_option("client.toolbarMode", "viewer")
st.markdown("<style>" + Path(__file__).with_name("styles.css").read_text(encoding="utf-8") + "</style>", unsafe_allow_html=True)
health, health_error = api("GET", "/health")

with st.sidebar:
    st.markdown('<div class="aid-brand"><span class="aid-mark">a</span> aidevops<span class="aid-local">LOCAL</span></div>', unsafe_allow_html=True)
    section = st.radio(
        "Section",
        [
            "Project workspace",
            "Docker monitoring",
            "AWS monitoring",
            "AWS management",
            "AWS setup",
            "AI assistant",
        ],
        label_visibility="collapsed",
        key="app_section",
    )
    st.caption("YOUR PROJECT WORKSPACE")
    st.write("")
    st.button("＋ New project", on_click=new_project, use_container_width=True, type="primary")
    st.markdown('<div class="aid-section">Workspace projects</div>', unsafe_allow_html=True)
    jobs, jobs_error = api("GET", "/api/jobs") if not health_error else ([], None)
    jobs = jobs or []
    if jobs_error:
        st.caption("Workspace projects could not load.")
    if jobs:
        by_id = {j["id"]: j for j in jobs}
        options = list(by_id)
        selected = st.session_state.get("job_id")
        st.selectbox("Open a project review", options, index=options.index(selected) if selected in options else None,
            placeholder="Choose a previous review", key="project_picker", on_change=select_project,
            format_func=lambda value: f"{by_id[value].get('project_name') or 'Untitled project'} · {status(by_id[value]['state'])[0]} · {value[-6:]}")
    else:
        st.caption("Your projects will appear here after your first review.")
    st.divider()
    with st.expander("How it works"):
        st.write("**1. Add a project.** Upload a project archive or use a folder already on this computer.")
        st.write("**2. Review the setup.** See what Aidevops found and download the files it prepared.")
        st.write("**3. Choose your checks.** Review the details and give permission before anything runs.")
    with st.expander("Service"):
        if health:
            st.caption("Project service: connected")
            st.caption("AI planning: configured" if health["llm_mode"] == "live" else "AI planning: off · example plans available")
            st.caption("Test environment: available" if health["docker_available"] else "Test environment: unavailable · start Docker to run project tests")
            st.caption(f"Version {health['version']} · {API_URL}")
        else:
            st.caption("Project service: disconnected")
    st.markdown('<p class="aid-footnote">You stay in control.<br>Cloud actions require your approval.</p>', unsafe_allow_html=True)
    st.markdown(
        f'<a class="aid-sidebar-logout" href="{escape(API_URL)}/logout" '
        'target="_self" title="End your current login session">'
        '<span aria-hidden="true">↪</span> Sign out</a>',
        unsafe_allow_html=True,
    )

if section == "Docker monitoring":
    render_docker_dashboard(api, st.context.cookies.get(SESSION_COOKIE))
    st.stop()

if section == "AWS monitoring":
    render_aws_dashboard(api, st.context.cookies.get(SESSION_COOKIE))
    st.stop()

if section == "AWS management":
    render_aws_management(api, st.context.cookies.get(SESSION_COOKIE))
    st.stop()

if section == "AWS setup":
    render_aws_setup(api, st.context.cookies.get(SESSION_COOKIE))
    st.stop()

if section == "AI assistant":
    render_ai_assistant(api, st.context.cookies.get(SESSION_COOKIE))
    st.stop()

if health_error:
    st.title("Project service unavailable")
    callout("Let’s connect your project service", "The local service is offline. Once it is started, your projects and guided review will be available here.")
    if st.button("Try connecting again", type="primary"):
        st.rerun()
    with st.expander("Setup help for the person installing Aidevops"):
        st.code(r".\.venv\Scripts\python.exe -m uvicorn aidevops.api.main:app --host 127.0.0.1 --port 8000", language="powershell")
    st.stop()

st.markdown('<div class="aid-topbar"><span>Workspace <span class="aid-slash">/</span> Projects</span><span class="aid-connected">● Service connected</span></div>', unsafe_allow_html=True)
job_id = st.session_state.get("job_id")
if not job_id or st.session_state.get("new_project"):
    st.title("Build and deploy your app")
    st.write(
        "Add your source code. Aidevops will identify the app, prepare a Docker setup, "
        "and guide you through a local preview and optional AWS deployment."
    )
    upload_col, folder_col = st.columns(2, gap="large")
    with upload_col:
        with st.container(border=True):
            st.subheader("Upload a source archive")
            upload = st.file_uploader("Choose your project archive", type=["zip", "tar", "gz", "tgz"], help="Upload your app’s source files as a ZIP or TAR archive. Aidevops cannot analyze a screenshot or a finished app installer.")
            st.caption("ZIP, TAR, GZ, or TGZ. Leave out passwords, keys, and private files.")
            if st.button("Review this upload", type="primary", disabled=upload is None, use_container_width=True):
                create_and_run(files={"file": (upload.name, upload.getvalue(), "application/octet-stream")})
    with folder_col:
        with st.container(border=True):
            st.subheader("Use a folder on this computer")
            with st.form("project_folder"):
                source = st.text_input(
                    "Project folder",
                    placeholder=r"E:\Projects\my-app",
                    help="The folder must be accessible to the computer running Aidevops.",
                )
                submitted = st.form_submit_button(
                    "Review this folder", type="primary", use_container_width=True
                )
            if submitted:
                if not source.strip():
                    st.error("Enter the project folder location first, or use the example project below.")
                else:
                    create_and_run(payload={"source_path": source.strip()})
    with st.container(border=True):
        st.markdown("#### Want to try the workflow first?")
        st.caption("Create a review using the included sample app.")
        if st.button("Open the example project"):
            create_and_run(payload={"source_path": SAMPLE_REPO})
    st.caption(
        "Review generated setup and approve each build or deployment before it runs. "
        "Uploading files does not publish your app."
    )
    st.stop()

job, error = api("GET", f"/api/jobs/{job_id}")
if error:
    st.error(error)
    if st.button("Back to projects", on_click=new_project):
        st.rerun()
    st.stop()
state = job["state"]
title, guidance, kind, _ = status(state)
profile, plan = job.get("profile"), job.get("plan")
st.markdown('<div class="aid-kicker">Your project review</div>', unsafe_allow_html=True)
heading, refresh = st.columns([5, 1])
heading.title(job.get("project_name") or "Your project")
with refresh:
    if st.button("Refresh", use_container_width=True):
        st.rerun()
st.markdown(badge(title, kind), unsafe_allow_html=True)
st.caption(guidance)

if state == "PENDING":
    if st.button("Start review", type="primary"):
        prepare(job_id)
        st.rerun()
elif state == "PLANNED":
    if st.button("Prepare setup files", type="primary"):
        prepare(job_id, "generate")
        st.rerun()

if job.get("error") or state == "FAILED":
    blocked = any(e.get("status") == "blocked" and e.get("tool") == "container_test" for e in job.get("executions", []))
    if blocked and not health["docker_available"]:
        st.warning("Your project tests could not run because Docker, the separate test environment, is unavailable. Start Docker, then create a new review for this project.")
    else:
        st.warning("The review could not complete every check. Open the check results below to see what happened. You can start a new review after the issue is resolved.")
    if job.get("error"):
        with st.expander("Technical error details"):
            st.code(job["error"], language="text")

with st.container(border=True):
    st.subheader("Build & preview")
    if job.get("artifacts"):
        poll_key = "preview_poll_" + job_id
        poll_interval = st.session_state.get(poll_key)
        @st.fragment(run_every=poll_interval)
        def local_preview():
            next_interval = render_preview_panel(
                api, job_id, profile, st.context.cookies.get(SESSION_COOKIE)
            )
            if next_interval != poll_interval:
                st.session_state[poll_key] = next_interval
                st.rerun()
        local_preview()
    if not job.get("artifacts"):
        st.info("Finish the project review to prepare your build and local preview.")

if state == "AWAITING_APPROVAL":
    with st.container(border=True):
        st.subheader("Ready to check your project?")
        st.write(
            "We’ll review the packaging instructions and, if tests were found, run them "
            "in a temporary environment. This may download dependencies and run your "
            "project’s code with internet access. Your original project files will not be edited."
        )
        st.caption(
            "This does not build a deployable image or publish your app. "
            "You can download the setup files without running checks."
        )
        needs_docker = bool(profile and profile.get("test_locations"))
        unavailable = needs_docker and (
            not health["docker_available"] or health.get("exec_backend") == "disabled"
        )
        if unavailable:
            st.warning(
                "Project tests are unavailable right now. Start Docker and enable "
                "container checks in the service settings, then refresh. You can still "
                "review and download your setup files."
            )
        approved = st.checkbox(
            "I have reviewed the setup and allow these checks to run",
            key="approve_" + job_id,
        )
        if st.button(
            "Approve & run checks",
            type="primary",
            disabled=not approved or unavailable,
            use_container_width=True,
        ):
            with st.status("Running your project checks…", expanded=True) as progress:
                result, error = api(
                    "POST", f"/api/jobs/{job_id}/execute", json={"approved": True}
                )
                if error:
                    progress.update(label="Checks could not start", state="error")
                    st.error(error)
                else:
                    progress.update(
                        label=status(result["state"])[0],
                        state="complete" if result["state"] == "SUCCEEDED" else "error",
                    )
                    st.rerun()
elif job.get("executions"):
    with st.expander("Check results", expanded=False):
        st.subheader("What happened in your checks")
        for record in job["executions"]:
            with st.container(border=True):
                st.write("**" + TOOLS.get(record["tool"], record["tool"]) + "**")
                st.markdown(
                    badge(
                        RESULTS.get(record["status"], record["status"]),
                        "ok" if record["status"] == "ok" else "warn",
                    ),
                    unsafe_allow_html=True,
                )
                if record.get("reason"):
                    st.write(record["reason"])
                st.caption(f"{record['tool']} · exit code {record.get('exit_code')}")
                st.code(record.get("output") or "No additional output.", language="text")
else:
    with st.expander("Check results", expanded=False):
        st.info("Check results will appear here after you approve and run project checks.")

with st.expander("Project overview", expanded=False):
    if profile:
        st.subheader("Here’s what we found")
        cols = st.columns(3)
        cols[0].metric("Project type", profile.get("language") or profile["project_type"])
        cols[1].metric("App framework", profile.get("framework") or "Not identified")
        cols[2].metric("Files reviewed", profile.get("files_scanned", 0))
        if not profile.get("test_locations"):
            st.info("We did not find project tests. File checks can still run, but they cannot show whether your app works correctly.")
        if profile.get("project_type") == "unknown":
            st.warning("We could not identify a runnable app in this folder. Select the app's source folder or provide its Dockerfile. Documents, screenshots and individual config files alone are not a runnable project.")
        if profile.get("web_build_tool"):
            st.caption("Build strategy: " + ("production Node server" if profile["web_build_tool"] == "next" else "compile browser assets, then serve them over HTTP") + f" · app port {profile.get('suggested_port')}")
        if profile.get("truncated"):
            st.warning("This project was larger than the review limit. The findings cover only part of its files.")
        with st.expander("What these findings are based on"):
            st.caption("These are clues from your files, not a full assessment of your app.")
            for evidence in profile.get("evidence", []):
                st.write(f"{evidence['path']} — {evidence['reason']}")
            for warning in profile.get("warnings", []):
                st.warning(warning)

    if plan:
        st.subheader("Your suggested setup")
        st.markdown(badge("AI-generated suggestion" if plan["source"] == "llm" else "Example plan · not AI-generated", "info" if plan["source"] == "llm" else "warn"), unsafe_allow_html=True)
        st.write("Aidevops has prepared a starting point for packaging your app and reviewing its setup. These files still need a person’s review before real-world use.")
        if plan["source"] != "llm":
            st.caption("This plan uses preset rules because AI planning was unavailable. It is based on the files we found.")
        with st.expander("Read the full plan and assumptions"):
            st.write(plan["summary"])
            for step in plan.get("steps", []):
                st.write(f"**{step['title']}** — {step['description']}")
                if step.get("command"):
                    st.code(step["command"], language="bash")
            st.caption("Commands shown here are suggestions. Only the app’s built-in checks can run.")
            for text in plan.get("assumptions", []) + plan.get("risks", []):
                st.write("• " + text)

with st.expander("Setup files", expanded=False):
    st.subheader("Your setup files")
    st.caption("You can download these now. Downloading does not change your app or publish it.")
    data, artifact_error = api("GET", f"/api/jobs/{job_id}/artifacts")
    if artifact_error:
        st.error(artifact_error)
    else:
        artifacts = (data or {}).get("artifacts", [])
        if not artifacts:
            st.info("Your setup files will appear here after the review finishes.")
        else:
            bundle = io.BytesIO()
            with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for artifact in artifacts:
                    archive.writestr(artifact["path"], artifact["content"])
            st.download_button("Download all setup files", data=bundle.getvalue(), file_name="aidevops-setup.zip", mime="application/zip", use_container_width=True)
            reports = {r["artifact_path"]: r for r in data.get("validation", [])}
            for artifact in artifacts:
                name, description = FILES.get(artifact["kind"], (artifact["path"], "A generated setup file for your project."))
                with st.expander(f"{name} · {artifact['path']}"):
                    st.write(description)
                    st.caption("Static file checks passed. This does not prove the app builds or runs." if artifact.get("verified") else "This file needs review before use.")
                    for note in artifact.get("notes", []):
                        st.warning(note)
                    for issue in reports.get(artifact["path"], {}).get("issues", []):
                        st.write(f"{issue['severity'].capitalize()}: {issue['message']}")
                    st.code(artifact["content"], language="dockerfile" if artifact["kind"] == "Dockerfile" else "text")
                    st.download_button("Download " + artifact["path"].split("/")[-1], data=artifact["content"], file_name=artifact["path"].split("/")[-1], key="dl_" + artifact["path"])

with st.expander("Review details & controls", expanded=False):
    st.caption(f"Review reference: {job_id}")
    st.caption("Internal status: " + state)
    for event in job.get("history", []):
        st.write(f"{status(event['from_state'])[0]} → {status(event['to_state'])[0]}")
    if state not in TERMINAL:
        st.caption("Stopping prevents further checks from starting. A running check may continue until it finishes.")
        if st.button("Stop this review"):
            _, error = api("POST", f"/api/jobs/{job_id}/cancel")
            if error:
                st.error(error)
            else:
                st.rerun()
if state in TERMINAL:
    if st.button("Start another project", type="primary", on_click=new_project):
        st.rerun()
