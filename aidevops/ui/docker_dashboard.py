"""Streamlit Docker monitoring and management page."""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime
from typing import Any

import streamlit as st

from aidevops.auth import SESSION_COOKIE

_SESSION_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
_HISTORY_LIMIT = 30


def _docker_api(api, session_cookie: str | None, method: str, path: str, **kwargs):
    if not isinstance(session_cookie, str) or not _SESSION_TOKEN.fullmatch(session_cookie):
        return None, "Sign in with the configured administrator account to manage Docker."
    headers = dict(kwargs.pop("headers", {}))
    headers["Cookie"] = f"{SESSION_COOKIE}={session_cookie}"
    return api(method, path, headers=headers, **kwargs)


def _sync_session_cache(session_cookie: str | None) -> None:
    fingerprint = (
        hashlib.sha256(session_cookie.encode("ascii")).hexdigest()
        if isinstance(session_cookie, str) and _SESSION_TOKEN.fullmatch(session_cookie)
        else None
    )
    previous = st.session_state.get("docker_session_fingerprint")
    if "docker_session_fingerprint" in st.session_state and previous != fingerprint:
        for key in (
            "docker_container_cache",
            "docker_container_error",
            "docker_container_cache_at",
            "docker_detail_cache",
            "docker_stats_cache",
            "docker_logs_cache",
            "docker_metric_history",
        ):
            st.session_state.pop(key, None)
    st.session_state["docker_session_fingerprint"] = fingerprint


def _bytes(value: int | None) -> str:
    if value is None:
        return "Unavailable"
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TiB"


def _format_metric(value: float | int | None, suffix: str = "") -> str:
    return f"{value:.1f}{suffix}" if isinstance(value, (int, float)) else "Unavailable"


def _uptime(seconds: int | None) -> str:
    if seconds is None:
        return "Not running"
    days, remaining = divmod(seconds, 86_400)
    hours, remaining = divmod(remaining, 3_600)
    minutes = remaining // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def _load_containers(
    api,
    cookie: str | None,
    *,
    force: bool = False,
) -> tuple[list[dict[str, Any]], str | None]:
    should_load = (
        force
        or "docker_container_cache" not in st.session_state
        or st.session_state.get("docker_container_error") is not None
    )
    if should_load:
        containers, error = _docker_api(api, cookie, "GET", "/api/docker/containers")
        st.session_state["docker_container_cache"] = (
            containers if isinstance(containers, list) else []
        )
        st.session_state["docker_container_error"] = error
        st.session_state["docker_container_cache_at"] = time.monotonic()
    return (
        st.session_state["docker_container_cache"],
        st.session_state.get("docker_container_error"),
    )


def _load_details(
    api,
    cookie: str | None,
    container_id: str,
    *,
    force: bool,
) -> tuple[dict[str, Any] | None, str | None]:
    cached = st.session_state.get("docker_detail_cache")
    if not force and cached and cached.get("container_id") == container_id:
        return cached.get("details"), cached.get("error")

    details, error = _docker_api(
        api, cookie, "GET", f"/api/docker/containers/{container_id}"
    )
    st.session_state["docker_detail_cache"] = {
        "container_id": container_id,
        "details": details,
        "error": error,
    }
    return details, error


def _load_stats(
    api,
    cookie: str | None,
    container_id: str,
    *,
    force: bool,
) -> tuple[dict[str, Any] | None, str | None]:
    cache = st.session_state.setdefault("docker_stats_cache", {})
    cached = cache.get(container_id)
    if not force and cached:
        return cached.get("stats"), cached.get("error")

    stats, error = _docker_api(
        api, cookie, "GET", f"/api/docker/containers/{container_id}/stats"
    )
    cache[container_id] = {"stats": stats, "error": error}
    if stats:
        history = st.session_state.setdefault("docker_metric_history", {})
        samples = history.setdefault(container_id, [])
        samples.append(
            {
                "sample": int(time.time()),
                "CPU (%)": stats.get("cpu_percent"),
                "Memory (%)": stats.get("memory_percent"),
                "Received (MiB)": (
                    stats["network_rx_bytes"] / 1_048_576
                    if stats.get("network_rx_bytes") is not None
                    else None
                ),
                "Sent (MiB)": (
                    stats["network_tx_bytes"] / 1_048_576
                    if stats.get("network_tx_bytes") is not None
                    else None
                ),
                "Read (MiB)": (
                    stats["block_read_bytes"] / 1_048_576
                    if stats.get("block_read_bytes") is not None
                    else None
                ),
                "Written (MiB)": (
                    stats["block_write_bytes"] / 1_048_576
                    if stats.get("block_write_bytes") is not None
                    else None
                ),
            }
        )
        del samples[:-_HISTORY_LIMIT]
    return stats, error


def _load_logs(api, cookie: str | None, container_id: str) -> None:
    logs, error = _docker_api(
        api,
        cookie,
        "GET",
        f"/api/docker/containers/{container_id}/logs",
        params={"tail": 100},
    )
    st.session_state["docker_logs_cache"] = {
        "container_id": container_id,
        "logs": logs,
        "error": error,
    }


def _action(
    api,
    cookie: str | None,
    method: str,
    path: str,
    *,
    reset_confirmation: bool = False,
    **kwargs,
) -> None:
    _, error = _docker_api(api, cookie, method, path, **kwargs)
    if error:
        st.error(error)
        return
    for key in (
        "docker_container_cache",
        "docker_detail_cache",
        "docker_stats_cache",
        "docker_logs_cache",
    ):
        st.session_state.pop(key, None)
    if reset_confirmation:
        st.session_state["docker_confirmation_revision"] = (
            st.session_state.get("docker_confirmation_revision", 0) + 1
        )
    st.rerun()


def _render_charts(container_id: str) -> None:
    history = st.session_state.get("docker_metric_history", {}).get(container_id, [])
    if not history:
        st.info("Charts will appear after the first resource sample.")
        return

    usage_tab, traffic_tab = st.tabs(["Usage", "Network & disk"])
    with usage_tab:
        st.caption("CPU and memory utilization · recent samples")
        st.line_chart(history, x="sample", y=["CPU (%)", "Memory (%)"], height=220)
    with traffic_tab:
        network, block = st.columns(2)
        with network:
            st.caption("Network traffic · cumulative MiB")
            st.line_chart(
                history,
                x="sample",
                y=["Received (MiB)", "Sent (MiB)"],
                height=220,
            )
        with block:
            st.caption("Block I/O · cumulative MiB")
            st.line_chart(
                history,
                x="sample",
                y=["Read (MiB)", "Written (MiB)"],
                height=220,
            )


def _render_live_panel(
    api,
    cookie: str | None,
    refresh_seconds: int,
    force_details: bool,
    force_stats: bool,
) -> None:
    containers, error = _load_containers(api, cookie)
    if error:
        st.error(error)
        if "authenticated" in error.lower() or "administrator" in error.lower():
            st.info(
                "Sign out, then sign in as the configured administrator on the same "
                "host name. Reload this page after signing in."
            )
        return

    running_count = sum(item.get("status") == "running" for item in containers)
    stopped_count = len(containers) - running_count
    unhealthy_count = sum(item.get("health_status") == "unhealthy" for item in containers)

    total, running, stopped, unhealthy = st.columns(4)
    total.metric("Containers", len(containers))
    running.metric("Running", running_count)
    stopped.metric("Stopped", stopped_count)
    unhealthy.metric("Unhealthy", unhealthy_count)

    filter_choice = st.radio(
        "Show",
        ["All", "Running", "Stopped"],
        horizontal=True,
        label_visibility="collapsed",
        key="docker_container_filter",
    )
    filtered = containers
    if filter_choice == "Running":
        filtered = [item for item in containers if item.get("status") == "running"]
    elif filter_choice == "Stopped":
        filtered = [item for item in containers if item.get("status") != "running"]

    if not filtered:
        st.info("No containers match this filter.")
        return

    options = [item["id"] for item in filtered]
    labels = {
        item["id"]: f"{item.get('name') or '(unnamed)'} · {item.get('status')}"
        for item in filtered
    }
    if st.session_state.get("docker_selected_container") not in options:
        st.session_state["docker_selected_container"] = options[0]
    selected_id = st.selectbox(
        "Container",
        options,
        format_func=lambda value: labels[value],
        key="docker_selected_container",
    )
    selected_item = next(item for item in filtered if item["id"] == selected_id)
    detail_cache = st.session_state.get("docker_detail_cache") or {}
    selection_changed = detail_cache.get("container_id") != selected_id
    if selection_changed:
        st.session_state.setdefault("docker_stats_cache", {}).clear()
        st.session_state.setdefault("docker_metric_history", {}).clear()
    details, detail_error = _load_details(
        api,
        cookie,
        selected_id,
        force=selection_changed or force_details,
    )
    if detail_error:
        st.error(detail_error)
        return

    stats = None
    stats_error = None
    if selected_item.get("status") == "running":
        stats, stats_error = _load_stats(
            api,
            cookie,
            selected_id,
            force=refresh_seconds > 0 or selection_changed or force_stats,
        )

    rows = []
    stats_cache = st.session_state.get("docker_stats_cache", {})
    for item in filtered:
        item_stats = stats_cache.get(item["id"], {}).get("stats") or {}
        if item.get("status") != "running":
            item_stats = {}
        rows.append(
            {
                "Container": item.get("name") or item["id"][:12],
                "Image": item.get("image"),
                "Status": item.get("status"),
                "CPU": (
                    _format_metric(item_stats.get("cpu_percent"), "%")
                    if item["id"] == selected_id
                    else "—"
                ),
                "Memory": (
                    _bytes(item_stats.get("memory_usage_bytes"))
                    if item["id"] == selected_id
                    else "—"
                ),
                "Health": item.get("health_status") or "—",
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)

    if details is None:
        st.warning("Container details are unavailable.")
        return

    st.markdown(f"### {details.get('name') or selected_id[:12]}")
    st.caption(
        f"{details.get('image')} · {selected_item.get('status')} · "
        f"{selected_item.get('health_status') or 'No health check'}"
    )
    cpu_col, memory_col, network_col, disk_col = st.columns(4)
    if stats:
        cpu_col.metric("CPU", _format_metric(stats.get("cpu_percent"), "%"))
        memory_col.metric(
            "Memory",
            _bytes(stats.get("memory_usage_bytes")),
            f"of {_bytes(stats.get('memory_limit_bytes'))}",
        )
        network_col.metric(
            "Network",
            f"↓ {_bytes(stats.get('network_rx_bytes'))}",
            f"↑ {_bytes(stats.get('network_tx_bytes'))}",
        )
        disk_col.metric(
            "Block I/O",
            f"Read {_bytes(stats.get('block_read_bytes'))}",
            f"Write {_bytes(stats.get('block_write_bytes'))}",
        )
        _render_charts(selected_id)
    elif stats_error:
        st.info(stats_error)
    else:
        st.info("Resource metrics are available while the container is running.")

    is_running = selected_item.get("status") == "running"
    start_col, stop_col, _ = st.columns([1, 1, 4])
    with start_col:
        if st.button("Start", disabled=is_running, key="docker_start_" + selected_id):
            _action(api, cookie, "POST", f"/api/docker/containers/{selected_id}/start")
    with stop_col:
        if st.button("Stop", disabled=not is_running, key="docker_stop_" + selected_id):
            _action(api, cookie, "POST", f"/api/docker/containers/{selected_id}/stop")

    with st.expander("Container information"):
        st.write(f"**ID:** `{details.get('id')}`")
        st.write(f"**Created:** {details.get('created_at') or 'Unavailable'}")
        st.write(f"**Uptime:** {_uptime(details.get('uptime_seconds'))}")
        st.write(f"**Ports:** {', '.join(details.get('ports') or []) or 'None'}")

    with st.expander("Recent logs"):
        logs_cache = st.session_state.get("docker_logs_cache") or {}
        if logs_cache.get("container_id") != selected_id:
            logs_cache = {}
        if st.button("Load recent logs", key="docker_load_logs_" + selected_id):
            _load_logs(api, cookie, selected_id)
            logs_cache = st.session_state["docker_logs_cache"]
        if logs_cache.get("error"):
            st.info(logs_cache["error"])
        elif logs_cache.get("logs"):
            st.code(logs_cache["logs"].get("logs") or "No recent logs.", language="text")
        else:
            st.caption("Logs are loaded only when requested.")

    with st.expander("More actions"):
        revision = st.session_state.get("docker_confirmation_revision", 0)
        restart_key = f"docker_confirm_restart_{selected_id}_{revision}"
        remove_key = f"docker_confirm_remove_{selected_id}_{revision}"
        restart_confirm = st.checkbox("Confirm restart", key=restart_key)
        if st.button(
            "Restart container",
            disabled=not restart_confirm,
            key="docker_restart_" + selected_id,
        ):
            _action(
                api,
                cookie,
                "POST",
                f"/api/docker/containers/{selected_id}/restart",
                json={"confirmed": True},
                reset_confirmation=True,
            )
        remove_confirm = st.checkbox("Confirm removal", key=remove_key)
        if st.button(
            "Remove stopped container",
            disabled=not remove_confirm or is_running,
            key="docker_remove_" + selected_id,
        ):
            _action(
                api,
                cookie,
                "DELETE",
                f"/api/docker/containers/{selected_id}",
                json={"confirmed": True},
                reset_confirmation=True,
            )
        if is_running:
            st.caption("Stop the container before removing it.")
    st.caption(
        f"Updated {datetime.now().strftime('%H:%M:%S')} · "
        f"{f'auto-refresh every {refresh_seconds}s' if refresh_seconds else 'auto-refresh off'}"
    )


def render(api, session_cookie: str | None = None) -> None:
    _sync_session_cache(session_cookie)
    st.markdown(
        '<div class="aid-topbar"><span>Workspace <span class="aid-slash">/</span> Docker</span>'
        '<span class="aid-connected">● Docker Engine</span></div>',
        unsafe_allow_html=True,
    )
    title_col, refresh_col = st.columns([4, 1])
    with title_col:
        st.title("Docker overview")
        st.caption("Container health and resource usage at a glance.")
    with refresh_col:
        refresh_seconds = st.selectbox(
            "Live refresh",
            [5, 15, 30, 0],
            index=0,
            format_func=lambda value: f"Every {value}s" if value else "Off",
            key="docker_refresh_interval",
        )
        refresh_clicked = st.button("Refresh now", use_container_width=True)
        if refresh_clicked:
            st.session_state["docker_refresh_requested"] = True

    containers, error = _load_containers(
        api,
        session_cookie,
        force=st.session_state.get("docker_container_error") is not None,
    )
    if error:
        st.error(error)
        if "authenticated" in error.lower() or "administrator" in error.lower():
            st.info(
                "Sign out, then sign in as the configured administrator on the same "
                "host name. Reload this page after signing in."
            )
        return

    @st.fragment(run_every=refresh_seconds or None)
    def live_panel() -> None:
        refresh_requested = st.session_state.pop("docker_refresh_requested", False)
        cache_age = time.monotonic() - st.session_state.get(
            "docker_container_cache_at", 0
        )
        auto_refresh_due = (
            refresh_seconds > 0 and cache_age >= refresh_seconds
        )
        refresh_list = refresh_requested or auto_refresh_due
        if refresh_list:
            _load_containers(api, session_cookie, force=True)
        _render_live_panel(
            api,
            session_cookie,
            refresh_seconds,
            force_details=refresh_requested,
            force_stats=refresh_requested or auto_refresh_due,
        )

    live_panel()
