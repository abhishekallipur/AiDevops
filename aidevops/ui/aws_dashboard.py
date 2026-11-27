"""Administrator-only AWS resource monitoring page."""

from __future__ import annotations

import re

import streamlit as st

from aidevops.auth import SESSION_COOKIE

_SESSION_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,128}$")


def _aws_api(api, session_cookie, method, path, **kwargs):
    if not isinstance(session_cookie, str) or not _SESSION_TOKEN.fullmatch(session_cookie):
        return None, "Sign in with the configured administrator account to view AWS resources."
    headers = dict(kwargs.pop("headers", {}))
    headers["Cookie"] = f"{SESSION_COOKIE}={session_cookie}"
    return api(method, path, headers=headers, **kwargs)


def _aws_error_guidance(error: str) -> str:
    normalized = error.casefold()
    if any(
        phrase in normalized
        for phrase in ("sign in", "administrator", "not authenticated")
    ):
        return (
            "Sign in as the configured administrator, using the same hostname for the dashboard "
            "and login page (for example, localhost for both). Then refresh this page."
        )
    if normalized == "not found" or "aws management is unavailable" in normalized:
        return (
            "The FastAPI backend may still be running an older version. Restart it to load the "
            "AWS routes, then refresh this page."
        )
    if "localstack" in normalized:
        return (
            "Check LocalStack at http://localhost:4566/_localstack/health. The root URL "
            "http://localhost:4566/ is an API endpoint, not a web console, and may return Not Found."
        )
    return "Check the FastAPI service logs and AWS/LocalStack service configuration for this request."


def render(api, session_cookie=None):
    st.title("AWS monitoring")
    st.caption("Read-only resource and health monitoring. Deployment actions require separate approval in the project build flow.")
    refresh = st.selectbox(
        "Refresh",
        [0, 30, 60],
        index=1,
        format_func=lambda value: "Off" if value == 0 else f"Every {value} seconds",
        key="aws_refresh_interval",
    )

    @st.fragment(run_every=refresh or None)
    def monitoring_panel():
        overview, error = _aws_api(api, session_cookie, "GET", "/api/aws/overview")
        if error:
            st.error(error)
            st.info(_aws_error_guidance(error))
            return

        mode = "LocalStack emulator" if overview["mode"] == "localstack" else "AWS account"
        st.caption(
            f"{mode} · account {overview.get('account_id') or 'unavailable'} · "
            f"region {overview.get('region')}"
        )
        instances = overview.get("instances", [])
        buckets = overview.get("buckets", [])
        deployments = overview.get("deployments", [])
        running = sum(instance["state"] == "running" for instance in instances)
        stopped = sum(instance["state"] == "stopped" for instance in instances)
        columns = st.columns(4)
        columns[0].metric("EC2 instances", len(instances))
        columns[1].metric("Running", running)
        columns[2].metric("Stopped", stopped)
        columns[3].metric("S3 buckets", len(buckets))

        if instances:
            st.subheader("EC2 instances")
            st.dataframe(
                [
                    {
                        "Instance": row.get("name"),
                        "ID": row.get("id"),
                        "State": row.get("state"),
                        "Type": row.get("type"),
                        "Public IP": row.get("public_ip") or "—",
                        "CPU (5-min avg)": (
                            f"{row['cpu_percent']:.1f}%" if row.get("cpu_percent") is not None else "No datapoints"
                        ),
                    }
                    for row in instances
                ],
                use_container_width=True,
                hide_index=True,
            )
            metric_rows = [
                {"Instance": row.get("name"), "CPU utilization (%)": row.get("cpu_percent")}
                for row in instances
                if row.get("cpu_percent") is not None
            ]
            if metric_rows:
                st.caption("CloudWatch CPU utilization · latest available five-minute average")
                st.bar_chart(metric_rows, x="Instance", y="CPU utilization (%)", height=220)
            else:
                st.info("CloudWatch has no recent CPU datapoints for the running instances.")
        else:
            st.info("No EC2 instances were returned for this region.")

        if buckets:
            st.subheader("S3 buckets")
            st.dataframe(
                [{"Bucket": row["name"], "Created": row.get("created_at") or "—"} for row in buckets],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No S3 buckets were returned for this region.")

        st.subheader("Aidevops deployments")
        if deployments:
            st.dataframe(
                [
                    {
                        "State": row["state"],
                        "Target": row["target"].upper(),
                        "Resource": row.get("resource_id") or "—",
                        "Region": row["region"],
                        "Created": row["created_at"],
                        "URL": row.get("url") or "—",
                    }
                    for row in deployments
                ],
                use_container_width=True,
                hide_index=True,
            )
            for row in deployments:
                if row.get("error"):
                    with st.expander(f"Deployment {row['id']} details"):
                        st.error(row["error"])
        else:
            st.caption("No Aidevops deployments have been recorded.")

        st.caption(
            "AWS metrics can be delayed or unavailable. This page limits CloudWatch requests "
            "and does not expose credentials, environment variables, or resource user data."
        )

    monitoring_panel()
