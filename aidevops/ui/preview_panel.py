"""Build/preview controls backed exclusively by the preview API."""
import streamlit as st

LABELS = {
    "AWAITING_BUILD_APPROVAL": "Snapshot ready for your review",
    "BUILDING": "Building your app…", "BUILT": "Image built and verified",
    "STARTING": "Starting the app and checking its response…", "READY": "Your local preview is ready",
    "BUILD_FAILED": "The image could not be built", "START_FAILED": "The app did not pass its startup check",
    "STOPPING": "Stopping the operation…", "STOPPED": "Preview stopped", "EXPIRED": "Preview session expired",
    "CANCELLED": "Build cancelled", "INTERRUPTED": "Service restarted; create a new snapshot",
    "REMOVED": "Preview resources removed", "CLEANUP_FAILED": "Cleanup needs attention",
}


def render(api, job_id, profile):
    with st.expander("Privacy · see what is sent to AI"):
        if st.button("Show AI request preview", key="prompt_" + job_id):
            payload, error = api("GET", f"/api/jobs/{job_id}/ai-prompt")
            if error:
                st.error(error)
            else:
                st.caption("Local-only mode is on: no external AI request is made." if payload["local_only"] else "This is the filtered request content. Recognizable secrets and local paths are redacted; detection is not a guarantee.")
                st.code(payload["system"], language="text")
                st.code(payload["user"], language="text")
    st.subheader("From source code to a running app")
    st.markdown('<div class="aid-build-steps"><span><b>01</b> Prepare snapshot</span><span><b>02</b> Approve & build</span><span><b>03</b> Start & open preview</span></div>', unsafe_allow_html=True)
    st.write("Prepare a fixed copy of your project, review it, then build and open a local preview. Your original files stay unchanged.")
    st.caption("Builds and apps run project code with network access. Use projects you trust. No cloud resources are created.")
    if st.button("Prepare build snapshot", key="snapshot_" + job_id, type="primary"):
        with st.spinner("Copying permitted files and checking for recognizable secrets…"):
            _, error = api("POST", f"/api/jobs/{job_id}/previews")
        if error:
            st.error(error)
    records, error = api("GET", f"/api/jobs/{job_id}/previews")
    if error or not isinstance(records, list):
        st.info("The preview service is not available. Restart the backend after installing this update.")
        return
    if not records:
        st.caption("Your build snapshot will appear here. Files with known secret names are excluded; recognizable credentials in other source files block preparation.")
        return
    for record in records[:5]:
        identity, state = record["id"], record["state"]
        with st.container(border=True):
            st.write("**" + LABELS.get(state, state) + "**")
            st.caption(f"Snapshot {identity[-8:]} · {record['file_count']} files · fingerprint {record['digest'][:12]}")
            if record.get("error"):
                st.warning(record["error"])
            if state in {"AWAITING_BUILD_APPROVAL", "BUILD_FAILED"}:
                consent = st.checkbox("I reviewed this setup and approve building this snapshot", key="build_consent_" + identity)
                if st.button("Build my app", disabled=not consent, key="build_" + identity, type="primary"):
                    _, error = api("POST", f"/api/previews/{identity}/build", json={"approved": True, "digest": record["digest"]})
                    if error:
                        st.error(error)
                    else:
                        st.rerun()
            if state in {"BUILT", "STOPPED", "EXPIRED", "START_FAILED"} and record.get("image_id"):
                st.caption("Choose the port your app listens on inside its container. Web apps must listen on 0.0.0.0. The preview itself is exposed only on this computer.")
                consent = st.checkbox("I approve starting this app locally with internet access", key="start_consent_" + identity)
                with st.form("start_" + identity, clear_on_submit=True):
                    st.caption("We filled in the app settings for you. Open advanced settings only if your app needs something different.")
                    with st.expander("Advanced preview settings"):
                        default_port = record.get("suggested_port") or (profile or {}).get("suggested_port") or (int(profile["declared_ports"][0]) if (profile or {}).get("declared_ports") else 8000)
                        port = st.number_input("App port", min_value=1, max_value=65535, value=default_port)
                        path = st.text_input("Health-check path", value=record.get("suggested_health_path") or ("/health" if (profile or {}).get("framework") == "FastAPI" else "/"))
                        ttl = st.selectbox("Stop automatically after", [15, 30, 60, 120], index=1, format_func=lambda n: f"{n} minutes")
                        st.caption("Optional: provide one runtime setting. It is not sent to AI or saved in the review. Docker can retain it in container metadata until the container is removed.")
                        env_name = st.text_input("Environment variable name", placeholder="DATABASE_URL")
                        env_value = st.text_input("Environment variable value", type="password")
                    start = st.form_submit_button("Start local preview", disabled=not consent, type="primary")
                if start:
                    _, error = api("POST", f"/api/previews/{identity}/start", json={"approved": True,
                        "port": int(port), "health_path": path, "ttl_minutes": ttl,
                        "environment": {env_name: env_value} if env_name else {}})
                    if error:
                        st.error(error)
                    else:
                        st.rerun()
            if state == "READY" and record.get("url"):
                st.success("The container is running and its HTTP check passed. This is a basic availability check, not a full correctness or security assessment.")
                st.link_button("Open my app", record["url"], type="primary")
                st.caption("Expires at " + record["expires_at"] + " (UTC). Automatic expiry requires the backend to remain running.")
            if state in {"BUILDING", "STARTING", "STOPPING"}:
                st.info("Work continues in the background. This panel checks for updates every two seconds.")
            if state in {"BUILDING", "STARTING", "READY", "CLEANUP_FAILED"}:
                if st.button("Stop preview / cancel operation", key="stop_" + identity):
                    _, error = api("POST", f"/api/previews/{identity}/stop")
                    if error:
                        st.error(error)
                    else:
                        st.rerun()
            with st.expander("Build log & technical details"):
                st.code(record.get("log") or "No build output recorded yet.", language="text")
                st.caption("Runtime logs are withheld because apps can print credentials. Inspect them locally with Docker if needed.")
                if record.get("image_id"):
                    st.code(record["image_id"], language="text")
            if state not in {"BUILDING", "STARTING", "STOPPING", "REMOVED"}:
                with st.expander("Remove preview resources"):
                    remove = st.checkbox("Remove this preview’s image, container and snapshot", key="remove_consent_" + identity)
                    if st.button("Remove preview resources", disabled=not remove, key="remove_" + identity):
                        _, error = api("POST", f"/api/previews/{identity}/cleanup")
                        if error:
                            st.error(error)
                        else:
                            st.rerun()

    if any(r["state"] in {"BUILDING", "STARTING", "STOPPING"} for r in records):
        return "2s"
    if any(r["state"] == "READY" for r in records):
        return "10s"
    return None
