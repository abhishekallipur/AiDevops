"""Opt-in smoke coverage against the developer's local Docker Engine."""

from __future__ import annotations

import os

import pytest

from aidevops.services.docker_manager import DockerManagementService

pytestmark = pytest.mark.skipif(
    os.getenv("AIDEVOPS_DOCKER_INTEGRATION") != "1",
    reason="set AIDEVOPS_DOCKER_INTEGRATION=1 to use the local Docker Engine",
)


def test_local_engine_container_listing(tmp_path):
    service = DockerManagementService(tmp_path / "docker-integration.db")
    try:
        containers = service.list_containers()
    finally:
        service.close()

    assert isinstance(containers, list)
    for container in containers:
        assert {"id", "name", "image", "status", "ports", "health_status"} <= set(container)
