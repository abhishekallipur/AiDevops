"""Docker Engine monitoring and management, isolated from preview resources."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import docker
from docker.errors import APIError, DockerException, NotFound

from ..errors import PolicyError
from ..logging_config import get_logger
from ..privacy import redact

log = get_logger("aidevops.docker")
_CONTAINER_ID = re.compile(r"^[a-fA-F0-9]{12,64}$")
class DockerManagementError(Exception):
    """A safe, user-facing Docker operation failure."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict[str, str]:
        return {"error": self.code, "message": self.message}


class DockerManagementService:
    """Manages arbitrary local containers through the Docker Engine API."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        client: Any | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._client = client
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS docker_management_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at TEXT NOT NULL,
                    username TEXT NOT NULL,
                    action TEXT NOT NULL,
                    container_id TEXT NOT NULL,
                    outcome TEXT NOT NULL
                )
                """
            )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _engine(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            self._client = docker.from_env(timeout=5)
            self._client.ping()
        except DockerException as exc:
            self._client = None
            raise DockerManagementError(
                503,
                "docker_unavailable",
                "Docker Engine is unavailable. Start Docker and try again.",
            ) from exc
        return self._client

    @staticmethod
    def validate_container_id(container_id: str) -> str:
        if not _CONTAINER_ID.fullmatch(container_id):
            raise DockerManagementError(
                422,
                "invalid_container_id",
                "Container IDs must be 12-64 hexadecimal characters.",
            )
        return container_id

    @staticmethod
    def _parse_time(value: str | None) -> datetime | None:
        if not value or value.startswith("0001-01-01"):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed

    @classmethod
    def _uptime_seconds(cls, state: dict[str, Any], status: str) -> int | None:
        if status != "running":
            return None
        started = cls._parse_time(state.get("StartedAt"))
        if started is None:
            return None
        return max(0, int((datetime.now(timezone.utc) - started).total_seconds()))

    @staticmethod
    def _ports(attrs: dict[str, Any]) -> list[str]:
        port_map = attrs.get("NetworkSettings", {}).get("Ports") or {}
        result: list[str] = []
        for container_port, bindings in port_map.items():
            if not bindings:
                result.append(container_port)
                continue
            for binding in bindings:
                host_ip = binding.get("HostIp") or "0.0.0.0"
                host_port = binding.get("HostPort")
                result.append(
                    f"{host_ip}:{host_port}->{container_port}" if host_port else container_port
                )
        return sorted(set(result))

    @classmethod
    def serialize_container(cls, container: Any) -> dict[str, Any]:
        attrs = getattr(container, "attrs", None) or {}
        state = attrs.get("State") or {}
        status = state.get("Status") or getattr(container, "status", "unknown")
        image = attrs.get("Config", {}).get("Image")
        if not image:
            image_object = getattr(container, "image", None)
            tags = getattr(image_object, "tags", None) or []
            image = tags[0] if tags else getattr(image_object, "short_id", "unknown")
        health = (state.get("Health") or {}).get("Status")
        created_at = cls._parse_time(attrs.get("Created"))
        started_at = cls._parse_time(state.get("StartedAt"))
        return {
            "id": container.id,
            "name": container.name,
            "image": str(image or "unknown"),
            "status": status,
            "created_at": created_at.isoformat() if created_at else attrs.get("Created"),
            "started_at": started_at.isoformat() if started_at else None,
            "uptime_seconds": cls._uptime_seconds(state, status),
            "ports": cls._ports(attrs),
            "health_status": health,
        }

    @staticmethod
    def calculate_stats(stats: dict[str, Any]) -> dict[str, float | int | None]:
        cpu = stats.get("cpu_stats") or {}
        previous_cpu = stats.get("precpu_stats") or {}
        cpu_usage = cpu.get("cpu_usage") or {}
        previous_usage = previous_cpu.get("cpu_usage") or {}
        current_cpu = cpu_usage.get("total_usage")
        prior_cpu = previous_usage.get("total_usage")
        current_system = cpu.get("system_cpu_usage")
        prior_system = previous_cpu.get("system_cpu_usage")
        cpu_delta = current_cpu - prior_cpu if current_cpu is not None and prior_cpu is not None else 0
        system_delta = (
            current_system - prior_system
            if current_system is not None and prior_system is not None
            else 0
        )
        online_cpus = cpu.get("online_cpus") or len(cpu_usage.get("percpu_usage") or []) or 1
        cpu_percent = (
            round(cpu_delta / system_delta * online_cpus * 100, 2)
            if cpu_delta > 0 and system_delta > 0 and online_cpus > 0
            else None
        )

        memory = stats.get("memory_stats") or {}
        memory_usage = memory.get("usage")
        memory_limit = memory.get("limit")
        memory_stats = memory.get("stats") or {}
        cache = memory_stats.get("cache", memory_stats.get("inactive_file", 0)) or 0
        used_memory = (
            max(0, memory_usage - cache)
            if isinstance(memory_usage, (int, float))
            else None
        )
        memory_percent = (
            round(used_memory / memory_limit * 100, 2)
            if used_memory is not None and memory_limit
            else None
        )

        networks = stats.get("networks")
        network_rx = network_tx = None
        if isinstance(networks, dict) and networks:
            network_rx = sum(int(item.get("rx_bytes", 0)) for item in networks.values())
            network_tx = sum(int(item.get("tx_bytes", 0)) for item in networks.values())

        block_io = (stats.get("blkio_stats") or {}).get("io_service_bytes_recursive")
        block_read = block_write = None
        if isinstance(block_io, list):
            block_read = sum(
                int(item.get("value", 0))
                for item in block_io
                if str(item.get("op", "")).lower() == "read"
            )
            block_write = sum(
                int(item.get("value", 0))
                for item in block_io
                if str(item.get("op", "")).lower() == "write"
            )

        return {
            "cpu_percent": cpu_percent,
            "memory_usage_bytes": used_memory,
            "memory_limit_bytes": memory_limit,
            "memory_percent": memory_percent,
            "network_rx_bytes": network_rx,
            "network_tx_bytes": network_tx,
            "block_read_bytes": block_read,
            "block_write_bytes": block_write,
        }

    @staticmethod
    def _map_engine_error(exc: Exception) -> DockerManagementError:
        if isinstance(exc, NotFound):
            return DockerManagementError(404, "container_not_found", "Container was not found.")
        if isinstance(exc, APIError):
            status = getattr(exc, "status_code", None)
            if status == 403:
                return DockerManagementError(
                    403, "docker_permission_denied", "Docker Engine denied this operation."
                )
            if status in {304, 409}:
                return DockerManagementError(
                    409, "container_state_conflict", "The container is already in that state or cannot be changed now."
                )
            if status == 404:
                return DockerManagementError(404, "container_not_found", "Container was not found.")
        if isinstance(exc, DockerException):
            return DockerManagementError(
                503,
                "docker_unavailable",
                "Docker Engine is unavailable. Start Docker and try again.",
            )
        return DockerManagementError(502, "docker_operation_failed", "Docker could not complete the operation.")

    def _get_container(self, container_id: str) -> Any:
        self.validate_container_id(container_id)
        try:
            return self._engine().containers.get(container_id)
        except (DockerException, APIError) as exc:
            raise self._map_engine_error(exc) from exc

    def list_containers(self) -> list[dict[str, Any]]:
        try:
            containers = self._engine().containers.list(all=True)
            return [self.serialize_container(container) for container in containers]
        except (DockerException, APIError) as exc:
            raise self._map_engine_error(exc) from exc

    def get_container(self, container_id: str) -> dict[str, Any]:
        return self.serialize_container(self._get_container(container_id))

    def get_stats(self, container_id: str) -> dict[str, Any]:
        container = self._get_container(container_id)
        try:
            raw_stats = container.stats(stream=False)
        except (DockerException, APIError) as exc:
            raise self._map_engine_error(exc) from exc
        return {"container_id": container_id, **self.calculate_stats(raw_stats)}

    def get_logs(self, container_id: str, tail: int = 100) -> dict[str, str]:
        container = self._get_container(container_id)
        try:
            raw = container.logs(tail=tail, timestamps=True)
        except (DockerException, APIError) as exc:
            raise self._map_engine_error(exc) from exc
        content = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        try:
            content = redact(content)
        except PolicyError:
            content = "[Log output withheld because it may contain a private key.]"
        return {"container_id": container_id, "logs": content[-100_000:]}

    def _audit(self, username: str, action: str, container_id: str, outcome: str) -> None:
        occurred_at = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.execute(
                """
                INSERT INTO docker_management_audit
                    (occurred_at, username, action, container_id, outcome)
                VALUES (?, ?, ?, ?, ?)
                """,
                (occurred_at, username, action, container_id, outcome),
            )

    def _manage(
        self,
        username: str,
        container_id: str,
        action: str,
    ) -> dict[str, Any]:
        self.validate_container_id(container_id)
        self._audit(username, action, container_id, "started")
        try:
            container = self._get_container(container_id)
            if action == "start":
                if container.status == "running":
                    raise DockerManagementError(
                        409, "container_already_running", "Container is already running."
                    )
                container.start()
            elif action == "stop":
                if container.status != "running":
                    raise DockerManagementError(
                        409, "container_already_stopped", "Container is already stopped."
                    )
                container.stop()
            elif action == "restart":
                container.restart()
            elif action == "remove":
                container.remove(force=False)
            else:
                raise ValueError(f"Unsupported Docker management action: {action}")
        except DockerManagementError:
            self._audit(username, action, container_id, "failed")
            raise
        except (DockerException, APIError) as exc:
            self._audit(username, action, container_id, "failed")
            raise self._map_engine_error(exc) from exc
        if action != "remove":
            try:
                container.reload()
            except (DockerException, APIError) as exc:
                self._audit(username, action, container_id, "failed")
                raise self._map_engine_error(exc) from exc
        self._audit(username, action, container_id, "succeeded")
        log.info(
            "Docker container management action completed",
            extra={"event": "docker_management", "tool": action},
        )
        if action == "remove":
            return {"container_id": container_id, "action": action, "status": "removed"}
        return self.serialize_container(container)

    def start_container(self, username: str, container_id: str) -> dict[str, Any]:
        return self._manage(username, container_id, "start")

    def stop_container(self, username: str, container_id: str) -> dict[str, Any]:
        return self._manage(username, container_id, "stop")

    def restart_container(self, username: str, container_id: str) -> dict[str, Any]:
        return self._manage(username, container_id, "restart")

    def remove_container(self, username: str, container_id: str) -> dict[str, Any]:
        return self._manage(username, container_id, "remove")
