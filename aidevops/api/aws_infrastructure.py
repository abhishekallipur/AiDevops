"""Administrator-only AWS instance, SSM, cost, and audit endpoints."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from .authz import require_admin
from ..services.aws_infrastructure import (
    AwsInfrastructureError,
    AwsInfrastructureService,
)

router = APIRouter(prefix="/api/aws/infra", tags=["aws-infrastructure"])
InstanceState = Literal[
    "pending", "running", "shutting-down", "terminated", "stopping", "stopped"
]
InstanceAction = Literal["start", "stop", "reboot", "terminate"]
DockerAction = Literal["list", "logs", "start", "stop", "restart", "remove", "deploy"]


class InstanceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ami_id: str = Field(pattern=r"^ami-[a-f0-9]{8,17}$")
    instance_type: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{1,31}$")
    subnet_id: str = Field(pattern=r"^subnet-[a-f0-9]{8,17}$")
    security_group_ids: list[str] = Field(min_length=1, max_length=5)
    name: str = Field(min_length=1, max_length=128)
    instance_profile_arn: str | None = None
    key_name: str | None = Field(default=None, max_length=255)
    associate_public_ip: bool = False
    public_access_confirmed: bool = False
    bootstrap_docker: bool = False
    tags: dict[str, str] = Field(default_factory=dict)
    dry_run: bool = False
    confirmed: bool = False


class InstanceActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: str | None = Field(default=None, max_length=100)
    dry_run: bool = False


class DockerActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: DockerAction
    container_id: str | None = Field(default=None, max_length=64)
    confirmation: str | None = Field(default=None, max_length=100)
    tail: int = Field(default=100, ge=1, le=1000)
    image: str | None = Field(default=None, max_length=512)
    container_name: str | None = Field(default=None, max_length=63)
    container_port: int | None = Field(default=None, ge=1, le=65535)
    host_port: int | None = Field(default=None, ge=1, le=65535)
    confirmed: bool = False
    public_access_confirmed: bool = False


def get_infrastructure_service(request: Request) -> AwsInfrastructureService:
    service = getattr(request.app.state, "aws_infrastructure_service", None)
    if service is None:
        raise HTTPException(
            status_code=503, detail="AWS infrastructure management is unavailable."
        )
    return service


def require_infrastructure_admin(request: Request) -> str:
    return require_admin(request, "AWS infrastructure management")


def _call(callback):
    try:
        return callback()
    except AwsInfrastructureError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/instances")
def list_instances(
    state: InstanceState | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    _: str = Depends(require_infrastructure_admin),
    service: AwsInfrastructureService = Depends(get_infrastructure_service),
) -> dict:
    return _call(lambda: service.list_instances(state=state, limit=limit))


@router.get("/instances/{instance_id}")
def get_instance(
    instance_id: str,
    _: str = Depends(require_infrastructure_admin),
    service: AwsInfrastructureService = Depends(get_infrastructure_service),
) -> dict:
    return _call(lambda: service.get_instance(instance_id))


@router.post("/instances")
def create_instance(
    body: InstanceCreateRequest,
    username: str = Depends(require_infrastructure_admin),
    service: AwsInfrastructureService = Depends(get_infrastructure_service),
) -> dict:
    return _call(
        lambda: service.create_instance(username, **body.model_dump())
    )


@router.post("/instances/{instance_id}/actions/{action}")
def manage_instance(
    instance_id: str,
    action: InstanceAction,
    body: InstanceActionRequest,
    username: str = Depends(require_infrastructure_admin),
    service: AwsInfrastructureService = Depends(get_infrastructure_service),
) -> dict:
    return _call(
        lambda: service.manage_instance(
            username,
            instance_id,
            action,
            confirmation=body.confirmation,
            dry_run=body.dry_run,
        )
    )


@router.get("/instances/{instance_id}/metrics")
def get_instance_metrics(
    instance_id: str,
    _: str = Depends(require_infrastructure_admin),
    service: AwsInfrastructureService = Depends(get_infrastructure_service),
) -> dict:
    return _call(lambda: service.get_instance_metrics(instance_id))


@router.post("/instances/{instance_id}/docker/actions", status_code=202)
def send_docker_action(
    instance_id: str,
    body: DockerActionRequest,
    username: str = Depends(require_infrastructure_admin),
    service: AwsInfrastructureService = Depends(get_infrastructure_service),
) -> dict:
    return _call(
        lambda: service.send_docker_command(
            username,
            instance_id,
            body.action,
            container_id=body.container_id,
            confirmation=body.confirmation,
            tail=body.tail,
            image=body.image,
            container_name=body.container_name,
            container_port=body.container_port,
            host_port=body.host_port,
            confirmed=body.confirmed,
            public_access_confirmed=body.public_access_confirmed,
        )
    )


@router.get("/instances/{instance_id}/commands/{command_id}")
def get_ssm_command(
    instance_id: str,
    command_id: str,
    username: str = Depends(require_infrastructure_admin),
    service: AwsInfrastructureService = Depends(get_infrastructure_service),
) -> dict:
    return _call(lambda: service.get_ssm_command(username, instance_id, command_id))


@router.get("/costs")
def get_cost_report(
    start: date,
    end: date,
    granularity: Literal["DAILY", "MONTHLY"] = "DAILY",
    _: str = Depends(require_infrastructure_admin),
    service: AwsInfrastructureService = Depends(get_infrastructure_service),
) -> dict:
    return _call(lambda: service.get_cost_report(start, end, granularity))


@router.get("/audit")
def get_audit_events(
    limit: int = Query(default=100, ge=1, le=500),
    _: str = Depends(require_infrastructure_admin),
    service: AwsInfrastructureService = Depends(get_infrastructure_service),
) -> list[dict]:
    return _call(lambda: service.audit_events(limit))
