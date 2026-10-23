"""Guided Streamlit client: add a project, understand its setup, approve checks."""
from __future__ import annotations

import io
import os
from html import escape
from pathlib import Path
import zipfile

import httpx
import streamlit as st

from aidevops.ui.presentation import FILES, RESULTS, TOOLS, badge, journey, status
from aidevops.ui.preview_panel import render as render_preview_panel

API_URL = os.getenv("AIDEVOPS_API_URL", "http://localhost:8000").rstrip("/")
SAMPLE_REPO = str(Path(__file__).resolve().parents[2] / "examples" / "sample_python_app")
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}


def api(method, path, **kwargs):
    try:
        response = httpx.request(method, f"{API_URL}{path}", timeout=300, **kwargs)
    except httpx.HTTPError:
        return None, "We could not connect to the project service. Please try again."
    if response.status_code >= 400:
        try:
            detail = response.json().get("message", "Please try again.")
        except (ValueError, AttributeError):
            detail = "The service could not complete this request. Please try again."
        return None, str(detail)
    try:
        return response.json(), None
    except ValueError:
        return None, "The service sent an unreadable response. Please try again."


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
    with st.expander("Service & settings"):
        if health:
            st.caption("Project service: connected")
            st.caption("AI planning: configured" if health["llm_mode"] == "live" else "AI planning: off · example plans available")
            st.caption("Test environment: available" if health["docker_available"] else "Test environment: unavailable · start Docker to run project tests")
            st.caption(f"Version {health['version']} · {API_URL}")
        else:
            st.caption("Project service: disconnected")
    st.markdown('<p class="aid-footnote">You stay in control.<br>Publishing and cloud deployment are not available yet.</p>', unsafe_allow_html=True)

if health_error:
    st.markdown('<div class="aid-hero"><div class="aid-kicker">Welcome to Aidevops</div><h1>A clearer path for your project.</h1><p>Understand your app, prepare its setup, and run checks with guidance at each step.</p></div>', unsafe_allow_html=True)
    callout("Let’s connect your project service", "The local service is offline. Once it is started, your projects and guided review will be available here.")
    if st.button("Try connecting again", type="primary"):
        st.rerun()
    with st.expander("Setup help for the person installing Aidevops"):
        st.code(r".\.venv\Scripts\python.exe -m uvicorn aidevops.api.main:app --host 127.0.0.1 --port 8000", language="powershell")
    st.stop()

st.markdown('<div class="aid-topbar"><span>Workspace <span class="aid-slash">/</span> Projects</span><span class="aid-connected">● Service connected</span></div>', unsafe_allow_html=True)
job_id = st.session_state.get("job_id")
if not job_id or st.session_state.get("new_project"):
    st.markdown('<div class="aid-hero"><div class="aid-hero-copy"><div class="aid-kicker">LESS SETUP. MORE BUILDING.</div><h1>Your project.<br><span>Ready for its next chapter.</span></h1><p>Bring your code. Get a tailored setup. Build and open your app, all from one workspace.</p><div class="aid-hero-tags"><span>↗ Project-aware setup</span><span>◉ Local previews</span><span>✓ You approve each run</span></div></div><div class="aid-launch-art" aria-hidden="true"><div class="aid-art-title"><i></i> YOUR NEXT LAUNCH</div><div class="aid-art-row"><span class="aid-art-icon">01</span><div><b>Bring your project</b><small>ZIP archive or local folder</small></div><em>↗</em></div><div class="aid-art-line"></div><div class="aid-art-row"><span class="aid-art-icon">02</span><div><b>Make it runnable</b><small>Review · build · preview</small></div><em>✦</em></div><div class="aid-art-footer">Your code. A clearer workflow.</div></div></div>', unsafe_allow_html=True)
    st.markdown('<div class="aid-section-heading"><h2>Create your next workspace</h2><span>Start with your source code</span></div>', unsafe_allow_html=True)
    main, aside = st.columns([1.7, 1], gap="large")
    with main:
        st.subheader("Add your project")
        st.write("Upload an archive or paste a folder location. We’ll identify your app and prepare its setup.")
        upload_tab, folder_tab = st.tabs(["Upload a project", "Use a folder"])
        with upload_tab:
            upload = st.file_uploader("Choose your project archive", type=["zip", "tar", "gz", "tgz"], help="Upload your app’s source files as a ZIP or TAR archive. Aidevops cannot analyze a screenshot or a finished app installer.")
            st.caption("Have a project folder? Compress it into a ZIP first. Leave out passwords, keys, and private files.")
            if st.button("Review this upload", type="primary", disabled=upload is None, use_container_width=True):
                create_and_run(files={"file": (upload.name, upload.getvalue(), "application/octet-stream")})
        with folder_tab:
            with st.form("project_folder"):
                source = st.text_input("Project folder location", placeholder=r"E:\MyProjects\my-app", help="The folder must be accessible on the computer running the project service.")
                st.caption("On Windows: open your project folder in File Explorer, then copy its address from the top bar.")
                submitted = st.form_submit_button("Review this folder", type="primary", use_container_width=True)
            if submitted:
                if not source.strip():
                    st.error("Add the folder location first, or try the example project.")
                else:
                    create_and_run(payload={"source_path": source.strip()})
    with aside:
        callout("Take a quick test drive.", "Explore the workflow with an included sample app. No project files needed.")
        if st.button("Try an example project", use_container_width=True):
            create_and_run(payload={"source_path": SAMPLE_REPO})
        st.caption("Uses a bundled sample app. The plan is AI-generated only when a provider is available; otherwise it is clearly labelled as an example plan.")
    st.divider()
    cards = st.columns(3)
    for col, (number, title, detail) in zip(cards, [
        ("01", "Understand your app", "See the project type and what Aidevops found in your files."),
        ("02", "Get a starting setup", "Download packaging and check configuration prepared for your project."),
        ("03", "Build & open your app", "Approve a build, launch a local preview, and open it in your browser."),
    ]):
        col.markdown(f'<div class="aid-feature"><span class="aid-kicker">{number}</span><b>{title}</b><p>{detail}</p></div>', unsafe_allow_html=True)
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

build_tab, overview_tab, files_tab, checks_tab = st.tabs(["Build & preview", "Project overview", "Setup files", "Checks & results"])
with build_tab:
    if job.get("artifacts"):
        poll_key = "preview_poll_" + job_id
        poll_interval = st.session_state.get(poll_key)
        @st.fragment(run_every=poll_interval)
        def local_preview():
            next_interval = render_preview_panel(api, job_id, profile)
            if next_interval != poll_interval:
                st.session_state[poll_key] = next_interval
                st.rerun()
        local_preview()
    if not job.get("artifacts"):
        st.info("Finish the project review to prepare your build and local preview.")
with overview_tab:
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

with files_tab:
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

with checks_tab:
    if state == "AWAITING_APPROVAL":
        st.divider()
        st.subheader("Ready to check your project?")
        st.write("We’ll review the packaging instructions and, if tests were found, run them in a temporary environment. This may download dependencies and run your project’s code with internet access. Your original project files will not be edited.")
        st.caption("This does not build a deployable image or publish your app. You can download the setup files without running checks.")
        needs_docker = bool(profile and profile.get("test_locations"))
        unavailable = needs_docker and (not health["docker_available"] or health.get("exec_backend") == "disabled")
        if unavailable:
            st.warning("Project tests are unavailable right now. Start Docker and enable container checks in the service settings, then refresh. You can still review and download your setup files.")
        approved = st.checkbox("I have reviewed the setup and allow these checks to run", key="approve_" + job_id)
        if st.button("Approve & run checks", type="primary", disabled=not approved or unavailable, use_container_width=True):
            with st.status("Running your project checks…", expanded=True) as progress:
                result, error = api("POST", f"/api/jobs/{job_id}/execute", json={"approved": True})
                if error:
                    progress.update(label="Checks could not start", state="error")
                    st.error(error)
                else:
                    progress.update(label=status(result["state"])[0], state="complete" if result["state"] == "SUCCEEDED" else "error")
                    st.rerun()

    if job.get("executions"):
        st.subheader("What happened in your checks")
        for record in job["executions"]:
            with st.container(border=True):
                st.write("**" + TOOLS.get(record["tool"], record["tool"]) + "**")
                st.markdown(badge(RESULTS.get(record["status"], record["status"]), "ok" if record["status"] == "ok" else "warn"), unsafe_allow_html=True)
                if record.get("reason"):
                    st.write(record["reason"])
                with st.expander("View technical log"):
                    st.caption(f"{record['tool']} · exit code {record.get('exit_code')}")
                    st.code(record.get("output") or "No additional output.", language="text")

    if state != "AWAITING_APPROVAL" and not job.get("executions"):
        st.info("Check results will appear here after you approve and run project checks.")

with st.expander("Review details & controls"):
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
