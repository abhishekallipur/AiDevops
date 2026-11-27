"""Administrator-only AWS instance, cost, audit, and SSM management dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st

from aidevops.ui.aws_dashboard import _aws_api

def _request(api, session_cookie, method, path, **kwargs):
    return _aws_api(api, session_cookie, method, path, **kwargs)


def _show_error(error: str | None) -> None:
    if error:
        st.error(error)


def _render_instance_creation(api, session_cookie) -> None:
    with st.expander("Create an EC2 instance"):
        st.caption(
            "Creates exactly one instance using your selected subnet, security groups, "
            "and optional instance profile. AWS charges may apply."
        )
        with st.form("aws_create_instance"):
            first, second = st.columns(2)
            ami_id = first.text_input("AMI ID", placeholder="ami-0123456789abcdef0")
            instance_type = second.selectbox(
                "Instance type",
                ["t3.micro", "t3.small", "t3.medium", "t4g.micro", "t4g.small"],
            )
            subnet_id = first.text_input("Subnet ID", placeholder="subnet-0123456789abcdef0")
            security_groups = second.text_input(
                "Security group IDs (comma-separated)", placeholder="sg-0123456789abcdef0"
            )
            name = first.text_input("Instance name", max_chars=128)
            profile_arn = second.text_input(
                "Instance profile ARN (recommended for SSM)", max_chars=512
            )
            key_name = first.text_input("EC2 key pair name (optional)", max_chars=255)
            associate_public_ip = second.checkbox("Associate a public IPv4 address")
            bootstrap_docker = st.checkbox("Install and start Docker on first boot")
            dry_run = st.checkbox("Validate only (AWS dry run; do not create)")
            confirmed = st.checkbox("I approve creating this EC2 instance and its charges")
            public_access_confirmed = st.checkbox(
                "I understand the instance may be reachable through its public IP/security group"
            )
            submitted = st.form_submit_button("Validate / create instance", type="primary")
        if submitted:
            body = {
                "ami_id": ami_id.strip(),
                "instance_type": instance_type,
                "subnet_id": subnet_id.strip(),
                "security_group_ids": [
                    group.strip() for group in security_groups.split(",") if group.strip()
                ],
                "name": name.strip(),
                "instance_profile_arn": profile_arn.strip() or None,
                "key_name": key_name.strip() or None,
                "associate_public_ip": associate_public_ip,
                "public_access_confirmed": public_access_confirmed,
                "bootstrap_docker": bootstrap_docker,
                "dry_run": dry_run,
                "confirmed": confirmed,
            }
            result, error = _request(
                api, session_cookie, "POST", "/api/aws/infra/instances", json=body
            )
            if error:
                _show_error(error)
            elif result.get("dry_run"):
                st.success("AWS accepted the dry run. No instance was created.")
            else:
                st.success(
                    f"EC2 instance created: {result.get('instance_id') or 'ID pending'}"
                )
                st.json(result)


def _render_instance_actions(api, session_cookie, instance) -> None:
    instance_id = instance["instance_id"]
    state = instance.get("state")
    st.subheader("Instance actions")
    columns = st.columns(4)
    if columns[0].button("Start", disabled=state != "stopped", key=f"start_{instance_id}"):
        result, error = _request(
            api,
            session_cookie,
            "POST",
            f"/api/aws/infra/instances/{instance_id}/actions/start",
            json={},
        )
        _show_error(error)
        if result:
            st.success(result.get("message", "Start request accepted."))
    if columns[1].button("Stop", disabled=state != "running", key=f"stop_{instance_id}"):
        result, error = _request(
            api,
            session_cookie,
            "POST",
            f"/api/aws/infra/instances/{instance_id}/actions/stop",
            json={},
        )
        _show_error(error)
        if result:
            st.success(result.get("message", "Stop request accepted."))
    if columns[2].button("Reboot", disabled=state != "running", key=f"reboot_{instance_id}"):
        result, error = _request(
            api,
            session_cookie,
            "POST",
            f"/api/aws/infra/instances/{instance_id}/actions/reboot",
            json={},
        )
        _show_error(error)
        if result:
            st.success(result.get("message", "Reboot request accepted."))

    with st.expander("Terminate instance (permanent)"):
        st.warning("Termination is permanent. Confirm by typing the exact phrase below.")
        expected = f"terminate {instance_id}"
        confirmation = st.text_input(
            f'Type "{expected}" to confirm',
            key=f"terminate_confirmation_{instance_id}",
        )
        if st.button(
            "Terminate instance",
            disabled=confirmation != expected,
            key=f"terminate_{instance_id}",
        ):
            result, error = _request(
                api,
                session_cookie,
                "POST",
                f"/api/aws/infra/instances/{instance_id}/actions/terminate",
                json={"confirmation": confirmation},
            )
            _show_error(error)
            if result:
                st.success(result.get("message", "Termination request accepted."))


def _render_metrics(api, session_cookie, instance_id) -> None:
    st.subheader("CloudWatch metrics")
    cache_key = f"aws_metrics_{instance_id}"
    if st.button("Refresh metrics", key=f"refresh_metrics_{instance_id}"):
        metrics, error = _request(
            api, session_cookie, "GET", f"/api/aws/infra/instances/{instance_id}/metrics"
        )
        if error:
            _show_error(error)
        else:
            st.session_state[cache_key] = metrics
    metrics = st.session_state.get(cache_key)
    if not metrics:
        st.caption("Metrics load only when you request them; no background polling is used.")
        return
    columns = st.columns(4)
    for column, label, key, suffix in [
        (columns[0], "CPU", "cpu_percent", "%"),
        (columns[1], "Memory", "memory_percent", "%"),
        (columns[2], "Network in", "network_in_bytes", " bytes"),
        (columns[3], "Network out", "network_out_bytes", " bytes"),
    ]:
        value = metrics.get(key)
        column.metric(label, "Unavailable" if value is None else f"{value}{suffix}")
    charts = [
        (
            "CPU and memory utilization (%)",
            [("CPU", "cpu_percent"), ("Memory", "memory_percent")],
        ),
        (
            "Network I/O (latest five-minute sum, bytes)",
            [("In", "network_in_bytes"), ("Out", "network_out_bytes")],
        ),
        (
            "Block I/O (latest five-minute sum, bytes)",
            [("EBS read", "ebs_read_bytes"), ("EBS write", "ebs_write_bytes")],
        ),
    ]
    for title, series in charts:
        rows = [
            {"Metric": label, "Value": metrics[key]}
            for label, key in series
            if metrics.get(key) is not None
        ]
        if rows:
            st.markdown(f"**{title}**")
            st.bar_chart(rows, x="Metric", y="Value", height=180)
    st.caption(metrics.get("message") or "CloudWatch datapoints may be delayed.")


def _render_remote_docker(api, session_cookie, instance_id) -> None:
    st.subheader("Remote Docker via Systems Manager")
    st.caption(
        "Commands use SSM Run Command with a fixed Docker allowlist. Arbitrary shell input, "
        "container environment variables, and Docker socket access are not exposed."
    )
    with st.form(f"remote_docker_{instance_id}"):
        action = st.selectbox(
            "Docker action",
            ["list", "logs", "start", "stop", "restart", "remove", "deploy"],
            key=f"docker_action_{instance_id}",
        )
        container_id = st.text_input(
            "Container ID (not needed for list)", max_chars=64, key=f"docker_id_{instance_id}"
        )
        tail = st.number_input(
            "Log lines", min_value=1, max_value=1000, value=100, key=f"docker_tail_{instance_id}"
        )
        image = st.text_input("ECR image URI (deploy only)", key=f"docker_image_{instance_id}")
        container_name = st.text_input(
            "New container name (deploy only)", max_chars=63, key=f"docker_name_{instance_id}"
        )
        left, right = st.columns(2)
        container_port = left.number_input(
            "Container port", min_value=1, max_value=65535, value=80,
            key=f"container_port_{instance_id}",
        )
        host_port = right.number_input(
            "EC2 host port", min_value=1, max_value=65535, value=80,
            key=f"host_port_{instance_id}",
        )
        confirmation = st.text_input(
            "Removal confirmation (type remove <container ID>)",
            key=f"docker_confirm_{instance_id}",
        )
        confirmed = st.checkbox(
            "I approve starting the selected remote Docker action",
            key=f"docker_approved_{instance_id}",
        )
        public_access_confirmed = st.checkbox(
            "For deploy: I understand the mapped port may be reachable through the EC2 security group",
            key=f"docker_public_confirmed_{instance_id}",
        )
        submitted = st.form_submit_button("Submit Docker action", type="primary")
    if submitted:
        body = {
            "action": action,
            "container_id": container_id.strip() or None,
            "confirmation": confirmation.strip() or None,
            "tail": int(tail),
            "image": image.strip() or None,
            "container_name": container_name.strip() or None,
            "container_port": int(container_port) if action == "deploy" else None,
            "host_port": int(host_port) if action == "deploy" else None,
            "confirmed": confirmed,
            "public_access_confirmed": public_access_confirmed,
        }
        result, error = _request(
            api,
            session_cookie,
            "POST",
            f"/api/aws/infra/instances/{instance_id}/docker/actions",
            json=body,
        )
        if error:
            _show_error(error)
        elif result:
            st.success(
                f"SSM accepted command {result.get('command_id')} "
                f"({result.get('status', 'pending')})."
            )
            st.session_state[f"last_ssm_{instance_id}"] = result.get("command_id")

    command_id = st.session_state.get(f"last_ssm_{instance_id}")
    if command_id:
        st.caption(f"Latest SSM command: `{command_id}`")
        if st.button("Check command status", key=f"poll_ssm_{instance_id}"):
            result, error = _request(
                api,
                session_cookie,
                "GET",
                f"/api/aws/infra/instances/{instance_id}/commands/{command_id}",
            )
            if error:
                _show_error(error)
            elif result:
                st.write(f"Status: **{result.get('status')}**")
                if result.get("stdout"):
                    st.code(result["stdout"])
                if result.get("stderr"):
                    st.warning(result["stderr"])


def _render_costs(api, session_cookie) -> None:
    st.subheader("Cost Explorer")
    today = datetime.now(timezone.utc).date()
    with st.form("aws_cost_report"):
        columns = st.columns(3)
        start = columns[0].date_input("Start date", today - timedelta(days=8))
        end = columns[1].date_input("End date (exclusive)", today - timedelta(days=1))
        granularity = columns[2].selectbox("Granularity", ["DAILY", "MONTHLY"])
        submitted = st.form_submit_button("Load Cost Explorer costs")
    if submitted:
        report, error = _request(
            api,
            session_cookie,
            "GET",
            "/api/aws/infra/costs",
            params={
                "start": start.isoformat(),
                "end": end.isoformat(),
                "granularity": granularity,
            },
        )
        if error:
            _show_error(error)
        elif report:
            buckets = report.get("buckets", [])
            st.metric(
                "Unblended cost in selected range",
                f"{sum(row.get('amount', 0) for row in buckets):.2f} {report.get('currency', 'USD')}",
            )
            services = [
                {"Date": row.get("start"), "Service": service.get("service"), "Cost": service.get("amount")}
                for row in buckets
                for service in row.get("services", [])
            ]
            if services:
                st.dataframe(services, use_container_width=True, hide_index=True)
            st.caption(report.get("disclaimer", "Cost Explorer data may be delayed."))


def render(api, session_cookie=None) -> None:
    st.title("AWS management")
    st.caption(
        "Manage EC2 instances and allowlisted remote Docker actions through authenticated "
        "FastAPI endpoints. AWS changes may incur charges."
    )
    st.button("Refresh AWS resources")

    state_filter = st.selectbox(
        "Instance state",
        [
            "All",
            "running",
            "stopped",
            "pending",
            "stopping",
            "shutting-down",
            "terminated",
        ],
        key="aws_instance_state_filter",
    )
    params = {} if state_filter == "All" else {"state": state_filter}
    payload, error = _request(
        api, session_cookie, "GET", "/api/aws/infra/instances", params=params
    )
    if error:
        _show_error(error)
        st.info("Sign in as the configured administrator to use AWS management.")
        return

    instances = payload.get("instances", [])
    running = sum(item.get("state") == "running" for item in instances)
    stopped = sum(item.get("state") == "stopped" for item in instances)
    columns = st.columns(4)
    columns[0].metric("Instances shown", len(instances))
    columns[1].metric("Running", running)
    columns[2].metric("Stopped", stopped)
    columns[3].metric("Other states", len(instances) - running - stopped)
    if payload.get("truncated"):
        st.warning("The instance list is limited to 100 results. Apply a state filter.")

    if instances:
        st.dataframe(
            [
                {
                    "Name": item.get("name"),
                    "Instance ID": item.get("instance_id"),
                    "State": item.get("state"),
                    "Type": item.get("instance_type"),
                    "Public IP": item.get("public_ip") or "—",
                    "AMI": item.get("ami_id"),
                }
                for item in instances
            ],
            use_container_width=True,
            hide_index=True,
        )
        selected_id = st.selectbox(
            "Selected instance",
            [item["instance_id"] for item in instances],
            format_func=lambda value: next(
                (
                    f"{item.get('name')} · {value} · {item.get('state')}"
                    for item in instances
                    if item["instance_id"] == value
                ),
                value,
            ),
        )
        details, detail_error = _request(
            api,
            session_cookie,
            "GET",
            f"/api/aws/infra/instances/{selected_id}",
        )
        _show_error(detail_error)
        if details:
            with st.expander("Selected instance details", expanded=True):
                st.json(details)
            _render_instance_actions(api, session_cookie, details)
            _render_metrics(api, session_cookie, selected_id)
            _render_remote_docker(api, session_cookie, selected_id)
    else:
        st.info("No EC2 instances match the selected state.")

    _render_instance_creation(api, session_cookie)
    _render_costs(api, session_cookie)
    with st.expander("Management audit log"):
        if st.button("Load recent management activity", key="load_aws_audit"):
            events, audit_error = _request(
                api, session_cookie, "GET", "/api/aws/infra/audit", params={"limit": 100}
            )
            _show_error(audit_error)
            if events:
                st.dataframe(events, use_container_width=True, hide_index=True)
