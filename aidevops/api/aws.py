"""Administrator-only AWS monitoring and deployment API."""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .authz import require_admin
from ..services.aws_manager import AwsManagementError, AwsManagementService

router = APIRouter(prefix="/api/aws", tags=["aws"])
_PREVIEW_ID = re.compile(r"^preview_[a-f0-9]{16}$")


class DeployRequest(BaseModel):
    target: Literal["s3", "ec2"]
    approved: bool = False
    public_access_confirmed: bool = False


def get_aws_service(request: Request) -> AwsManagementService:
    service = getattr(request.app.state, "aws_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="AWS management is unavailable.")
    return service


def require_aws_admin(request: Request) -> str:
    return require_admin(request, "AWS management")


@router.get("/status")
def aws_status(
    _: str = Depends(require_aws_admin),
    service: AwsManagementService = Depends(get_aws_service),
) -> dict:
    return service.status()


@router.get("/overview")
def aws_overview(
    _: str = Depends(require_aws_admin),
    service: AwsManagementService = Depends(get_aws_service),
) -> dict:
    return service.overview()


@router.get("/deployments")
def aws_deployments(
    _: str = Depends(require_aws_admin),
    service: AwsManagementService = Depends(get_aws_service),
) -> list[dict]:
    return service.list_deployments()


@router.get("/previews/{identity}/recommendation")
def aws_recommendation(
    identity: str,
    _: str = Depends(require_aws_admin),
    service: AwsManagementService = Depends(get_aws_service),
) -> dict:
    if not _PREVIEW_ID.fullmatch(identity):
        raise HTTPException(status_code=422, detail="Invalid preview identity")
    return service.recommendation(identity)


@router.post("/previews/{identity}/deploy", status_code=201)
def aws_deploy(
    identity: str,
    body: DeployRequest,
    username: str = Depends(require_aws_admin),
    service: AwsManagementService = Depends(get_aws_service),
) -> dict:
    if not _PREVIEW_ID.fullmatch(identity):
        raise HTTPException(status_code=422, detail="Invalid preview identity")
    try:
        return service.deploy(
            username,
            identity,
            body.target,
            approved=body.approved,
            public_access_confirmed=body.public_access_confirmed,
        )
    except AwsManagementError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
