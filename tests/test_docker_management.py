"""Mocked Docker Engine tests for monitoring and management."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import docker
import pytest

from aidevops.services.docker_manager import (
    DockerManagementError,
    DockerManagementService,
)

CONTAINER_ID = "a" * 64


class FakeImage:
    tags = ["web:latest"]
    short_id = "sha256:example"


class FakeContainer:
    def __init__(self, status: str = "running") -> None:
        started = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        self.id = CONTAINER_ID if status == "running" else "b" * 64
        self.name = "web" if status == "running" else "worker"
        self.status = status
        self.image = FakeImage()
        self.attrs = {
            "Id": self.id,
            "Name": "/web",
            "Created": "2026-01-01T00:00:00Z",
            "Config": {"Image": "web:latest", "Env": ["PASSWORD=must-not-be-returned"]},
            "State": {
                "Status": status,
                "StartedAt": started if status == "running" else "0001-01-01T00:00:00Z",
                "Health": {"Status": "healthy"},
            },
            "NetworkSettings": {
                "Ports": {"80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]}
            },
        }
        self.started = False
        self.stopped = False
        self.restarted = False
        self.removed = False
        self.last_logs_tail = None

    def reload(self) -> None:
        self.attrs["State"]["Status"] = self.status

    def start(self) -> None:
        self.started = True
        self.status = "running"

    def stop(self) -> None:
        self.stopped = True
        self.status = "exited"

    def restart(self) -> None:
        self.restarted = True
        self.status = "running"

    def remove(self, *, force: bool) -> None:
        assert force is False
        self.removed = True

    def stats(self, *, stream: bool) -> dict:
        assert stream is False
        return {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 150, "percpu_usage": [1, 1]},
                "system_cpu_usage": 300,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 200,
            },
            "memory_stats": {
                "usage": 1000,
                "limit": 2000,
                "stats": {"cache": 200},
            },
            "networks": {
                "eth0": {"rx_bytes": 100, "tx_bytes": 200},
                "eth1": {"rx_bytes": 50, "tx_bytes": 25},
            },
            "blkio_stats": {
                "io_service_bytes_recursive": [
                    {"op": "Read", "value": 500},
                    {"op": "Write", "value": 700},
                    {"op": "Sync", "value": 900},
                ]
            },
        }

    def logs(self, *, tail: int, timestamps: bool) -> bytes:
        assert timestamps is True
        self.last_logs_tail = tail
        return b"2026-01-01T00:00:00Z password=topsecret\n"


class FakeContainers:
    def __init__(self, *containers: FakeContainer) -> None:
        self.items = {container.id: container for container in containers}

    def list(self, *, all: bool) -> list[FakeContainer]:
        assert all is True
        return list(self.items.values())

    def get(self, identity: str) -> FakeContainer:
        try:
            return self.items[identity]
        except KeyError as exc:
            raise docker.errors.NotFound("missing") from exc


class FakeDockerClient:
    def __init__(self, *containers: FakeContainer) -> None:
        self.containers = FakeContainers(*containers)
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def docker_service(tmp_path):
    running = FakeContainer("running")
    stopped = FakeContainer("exited")
    return DockerManagementService(
        tmp_path / "docker.db",
        client=FakeDockerClient(running, stopped),
    )


def test_list_includes_running_and_stopped_without_inspection_secrets(docker_service):
    results = docker_service.list_containers()

    assert {item["status"] for item in results} == {"running", "exited"}
    running = next(item for item in results if item["status"] == "running")
    assert running["name"] == "web"
    assert running["image"] == "web:latest"
    assert running["health_status"] == "healthy"
    assert running["ports"] == ["127.0.0.1:8080->80/tcp"]
    assert running["uptime_seconds"] >= 0
    assert "must-not-be-returned" not in repr(results)


def test_container_inspection_and_not_found(docker_service):
    assert docker_service.get_container(CONTAINER_ID)["id"] == CONTAINER_ID
    with pytest.raises(DockerManagementError) as error:
        docker_service.get_container("c" * 64)
    assert error.value.status_code == 404


def test_stats_calculation_uses_engine_counter_deltas(docker_service):
    stats = docker_service.get_stats(CONTAINER_ID)

    assert stats["cpu_percent"] == 100
    assert stats["memory_usage_bytes"] == 800
    assert stats["memory_limit_bytes"] == 2000
    assert stats["memory_percent"] == 40
    assert stats["network_rx_bytes"] == 150
    assert stats["network_tx_bytes"] == 225
    assert stats["block_read_bytes"] == 500
    assert stats["block_write_bytes"] == 700


def test_unsupported_metrics_are_reported_as_unavailable():
    stats = DockerManagementService.calculate_stats({})

    assert stats == {
        "cpu_percent": None,
        "memory_usage_bytes": None,
        "memory_limit_bytes": None,
        "memory_percent": None,
        "network_rx_bytes": None,
        "network_tx_bytes": None,
        "block_read_bytes": None,
        "block_write_bytes": None,
    }


def test_logs_are_bounded_and_redacted(docker_service):
    result = docker_service.get_logs(CONTAINER_ID, tail=25)

    assert "password=[REDACTED]" in result["logs"]
    assert "topsecret" not in result["logs"]
    assert docker_service._client.containers.items[CONTAINER_ID].last_logs_tail == 25


def test_start_stop_restart_remove_and_audit_log(docker_service, tmp_path):
    service = docker_service
    stopped_id = "b" * 64
    service._client.containers.items[stopped_id] = FakeContainer("exited")

    assert service.start_container("admin", stopped_id)["status"] == "running"
    assert service.stop_container("admin", CONTAINER_ID)["status"] == "exited"
    assert service.restart_container("admin", CONTAINER_ID)["status"] == "running"
    assert service.remove_container("admin", CONTAINER_ID)["status"] == "removed"
    assert service._client.containers.items[CONTAINER_ID].started is False
    assert service._client.containers.items[stopped_id].started is True
    assert service._client.containers.items[CONTAINER_ID].stopped is True
    assert service._client.containers.items[CONTAINER_ID].restarted is True
    assert service._client.containers.items[CONTAINER_ID].removed is True

    with sqlite3.connect(tmp_path / "docker.db") as conn:
        rows = conn.execute(
            "SELECT username, action, outcome FROM docker_management_audit "
            "ORDER BY id"
        ).fetchall()
    assert rows == [
        ("admin", "start", "started"),
        ("admin", "start", "succeeded"),
        ("admin", "stop", "started"),
        ("admin", "stop", "succeeded"),
        ("admin", "restart", "started"),
        ("admin", "restart", "succeeded"),
        ("admin", "remove", "started"),
        ("admin", "remove", "succeeded"),
    ]


def test_invalid_container_id_is_rejected(docker_service):
    with pytest.raises(DockerManagementError) as error:
        docker_service.get_container("not-a-container")
    assert error.value.status_code == 422
    assert error.value.code == "invalid_container_id"


def test_docker_engine_unavailable(monkeypatch, tmp_path):
    def unavailable(**kwargs):
        raise docker.errors.DockerException("private engine detail")

    monkeypatch.setattr(docker, "from_env", unavailable)
    service = DockerManagementService(tmp_path / "docker.db")

    with pytest.raises(DockerManagementError) as error:
        service.list_containers()
    assert error.value.status_code == 503
    assert "private engine detail" not in error.value.message


def test_docker_api_requires_admin_and_confirms_destructive_actions(client):
    assert client.get("/api/docker/containers").status_code == 401

    assert client.post(
        "/api/auth/register",
        json={"username": "viewer", "password": "viewer-password"},
    ).status_code == 201
    assert client.post(
        "/api/auth/login",
        json={"username": "viewer", "password": "viewer-password"},
    ).status_code == 200
    forbidden = client.get("/api/docker/containers")
    assert forbidden.status_code == 403
    assert "viewer" in forbidden.json()["detail"]
    assert "admin" in forbidden.json()["detail"]

    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    ).status_code == 200
    service = client.app.state.docker_service
    service._client = FakeDockerClient(FakeContainer())

    listing = client.get("/api/docker/containers")
    assert listing.status_code == 200
    assert listing.json()[0]["name"] == "web"

    detail = client.get(f"/api/docker/containers/{CONTAINER_ID}")
    assert detail.status_code == 200
    assert detail.json()["id"] == CONTAINER_ID

    stats = client.get(f"/api/docker/containers/{CONTAINER_ID}/stats")
    assert stats.status_code == 200
    assert stats.json()["cpu_percent"] == 100

    assert client.post(
        f"/api/docker/containers/{CONTAINER_ID}/restart",
        json={"confirmed": False},
    ).status_code == 400
    assert client.request(
        "DELETE",
        f"/api/docker/containers/{CONTAINER_ID}",
        json={"confirmed": False},
    ).status_code == 400


def test_docker_api_rejects_malformed_container_id(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    response = client.get("/api/docker/containers/not-an-id")

    assert response.status_code == 422
