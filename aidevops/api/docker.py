"""Authenticated FastAPI routes for Docker Engine monitoring and management."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from .authz import require_admin
from ..services.docker_manager import DockerManagementService

router = APIRouter(prefix="/api/docker", tags=["docker"])
_CONTAINER_ID = r"^[a-fA-F0-9]{12,64}$"


class ContainerSummary(BaseModel):
    id: str
    name: str
    image: str
    status: str
    created_at: str | None
    started_at: str | None
    uptime_seconds: int | None
    ports: list[str]
    health_status: str | None


class ContainerStats(BaseModel):
    container_id: str
    cpu_percent: float | None
    memory_usage_bytes: int | None
    memory_limit_bytes: int | None
    memory_percent: float | None
    network_rx_bytes: int | None
    network_tx_bytes: int | None
    block_read_bytes: int | None
    block_write_bytes: int | None


class ContainerLogs(BaseModel):
    container_id: str
    logs: str


class ConfirmationRequest(BaseModel):
    confirmed: bool = Field(description="Must be true to perform this operation.")


class ActionResult(BaseModel):
    container_id: str
    action: str
    status: str


def require_docker_admin(request: Request) -> str:
    return require_admin(request, "Docker management")


def get_docker_service(request: Request) -> DockerManagementService:
    service = getattr(request.app.state, "docker_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Docker management is unavailable.")
    return service


@router.get("/containers", response_model=list[ContainerSummary])
def list_containers(
    _: str = Depends(require_docker_admin),
    service: DockerManagementService = Depends(get_docker_service),
) -> list[dict[str, Any]]:
    return service.list_containers()


@router.get("/containers/{container_id}", response_model=ContainerSummary)
def get_container(
    container_id: str = Path(pattern=_CONTAINER_ID),
    _: str = Depends(require_docker_admin),
    service: DockerManagementService = Depends(get_docker_service),
) -> dict[str, Any]:
    return service.get_container(container_id)


@router.get("/containers/{container_id}/stats", response_model=ContainerStats)
def get_stats(
    container_id: str = Path(pattern=_CONTAINER_ID),
    _: str = Depends(require_docker_admin),
    service: DockerManagementService = Depends(get_docker_service),
) -> dict[str, Any]:
    return service.get_stats(container_id)


@router.get("/containers/{container_id}/logs", response_model=ContainerLogs)
def get_logs(
    container_id: str = Path(pattern=_CONTAINER_ID),
    tail: int = Query(default=100, ge=1, le=1000),
    _: str = Depends(require_docker_admin),
    service: DockerManagementService = Depends(get_docker_service),
) -> dict[str, str]:
    return service.get_logs(container_id, tail)


@router.post("/containers/{container_id}/start", response_model=ContainerSummary)
def start_container(
    container_id: str = Path(pattern=_CONTAINER_ID),
    username: str = Depends(require_docker_admin),
    service: DockerManagementService = Depends(get_docker_service),
) -> dict[str, Any]:
    return service.start_container(username, container_id)


@router.post("/containers/{container_id}/stop", response_model=ContainerSummary)
def stop_container(
    container_id: str = Path(pattern=_CONTAINER_ID),
    username: str = Depends(require_docker_admin),
    service: DockerManagementService = Depends(get_docker_service),
) -> dict[str, Any]:
    return service.stop_container(username, container_id)


@router.post("/containers/{container_id}/restart", response_model=ContainerSummary)
def restart_container(
    body: ConfirmationRequest,
    container_id: str = Path(pattern=_CONTAINER_ID),
    username: str = Depends(require_docker_admin),
    service: DockerManagementService = Depends(get_docker_service),
) -> dict[str, Any]:
    if not body.confirmed:
        raise HTTPException(status_code=400, detail="Restart requires explicit confirmation.")
    return service.restart_container(username, container_id)


@router.delete("/containers/{container_id}", response_model=ActionResult)
def remove_container(
    body: ConfirmationRequest,
    container_id: str = Path(pattern=_CONTAINER_ID),
    username: str = Depends(require_docker_admin),
    service: DockerManagementService = Depends(get_docker_service),
) -> dict[str, str]:
    if not body.confirmed:
        raise HTTPException(status_code=400, detail="Removal requires explicit confirmation.")
    return service.remove_container(username, container_id)
