"""Approval-gated AWS deployment and read-only monitoring.

The default mode targets LocalStack with dummy credentials. Real AWS access
requires an explicit ``AIDEVOPS_AWS_MODE=aws`` setting and follows the normal
AWS SDK credential chain.
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import io
import json
import mimetypes
from pathlib import PurePosixPath
import re
import sqlite3
import tempfile
import tarfile
from typing import Any, BinaryIO
import uuid
from contextlib import closing
from urllib.parse import urlsplit

from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from ..config import Settings
from ..db import JobStore
from ..errors import NotFoundError, PolicyError, ValidationError
from ..logging_config import get_logger
from ..models import JobRecord
from .preview import PreviewService

log = get_logger("aidevops.aws")
_PREVIEW_ID = re.compile(r"^preview_[a-f0-9]{16}$")
_AMI_ID = re.compile(r"ami-[a-f0-9]{8,17}")
_INSTANCE_PROFILE_ARN = re.compile(
    r"arn:(?:aws|aws-us-gov|aws-cn):iam::\d{12}:instance-profile/[A-Za-z0-9+=,.@_-]+"
)
_MAX_STATIC_FILES = 5000
_MAX_STATIC_BYTES = 100 * 1024 * 1024
_STATIC_PATH = "/usr/share/nginx/html"


class AwsManagementError(Exception):
    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code

    def to_dict(self) -> dict[str, str]:
        return {"error": "aws_management_error", "message": self.message}


class AwsManagementService:
    """Owns AWS access, deployment records, and audit events."""

    def __init__(
        self, settings: Settings, previews: PreviewService, jobs: JobStore
    ) -> None:
        self.settings = settings
        self.previews = previews
        self.jobs = jobs
        self.db_path = settings.data_dir / "aws_management.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path, timeout=30)) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS aws_deployments (
                    id TEXT PRIMARY KEY,
                    preview_id TEXT NOT NULL,
                    target TEXT NOT NULL,
                    region TEXT NOT NULL,
                    state TEXT NOT NULL,
                    resource_id TEXT,
                    url TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS aws_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    target TEXT NOT NULL,
                    resource_id TEXT,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_aws_active_preview
                ON aws_deployments(preview_id)
                WHERE state IN ('DEPLOYING', 'DEPLOYED');
                """
            )
            conn.commit()

    def _client(self, service: str) -> Any:
        if not re.fullmatch(r"[a-z0-9-]{3,32}", self.settings.aws_region):
            raise AwsManagementError("The configured AWS region is invalid.", status_code=503)
        try:
            import boto3
        except ImportError as exc:
            raise AwsManagementError(
                "AWS support is not installed. Install the application dependencies and restart."
            ) from exc

        options = {
            "region_name": self.settings.aws_region,
            "config": Config(
                connect_timeout=3,
                read_timeout=10,
                retries={"mode": "standard", "total_max_attempts": 2},
            ),
        }
        if self.settings.aws_mode == "localstack":
            endpoint = self.settings.aws_endpoint_url or "http://localhost:4566"
            parsed = urlsplit(endpoint)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise AwsManagementError(
                    "The LocalStack endpoint must be an HTTP(S) URL without embedded credentials or query values.",
                    status_code=503,
                )
            try:
                parsed.port
            except ValueError as exc:
                raise AwsManagementError("The LocalStack endpoint port is invalid.", status_code=503) from exc
            options.update(
                endpoint_url=endpoint,
                aws_access_key_id="test",
                aws_secret_access_key="test",
            )
        elif self.settings.aws_mode != "aws":
            raise AwsManagementError("AWS mode is invalid; choose LocalStack or AWS.", status_code=503)
        try:
            return boto3.client(service, **options)
        except (BotoCoreError, ValueError) as exc:
            raise AwsManagementError("The AWS client could not be configured.", status_code=503) from exc

    def _endpoint_display(self) -> str | None:
        if self.settings.aws_mode != "localstack":
            return None
        endpoint = self.settings.aws_endpoint_url or "http://localhost:4566"
        try:
            parsed = urlsplit(endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                return "Configured LocalStack endpoint"
            port = f":{parsed.port}" if parsed.port else ""
            return f"{parsed.scheme}://{parsed.hostname}{port}"
        except ValueError:
            return "Configured LocalStack endpoint"

    def _deployment(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            with closing(sqlite3.connect(self.db_path, timeout=30)) as conn:
                conn.execute(
                    "INSERT INTO aws_deployments "
                    "(id, preview_id, target, region, state, resource_id, url, error, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        record["id"], record["preview_id"], record["target"], record["region"],
                        record["state"], record.get("resource_id"), record.get("url"),
                        record.get("error"), record["created_at"],
                    ),
                )
                conn.commit()
        except sqlite3.IntegrityError as exc:
            raise ValidationError(
                "This preview already has an active or completed AWS deployment"
            ) from exc
        return record

    def _update_deployment(self, identity: str, **fields: Any) -> dict[str, Any]:
        allowed = {"state", "resource_id", "url", "error"}
        if set(fields) - allowed:
            raise ValueError("Invalid deployment fields")
        with closing(sqlite3.connect(self.db_path, timeout=30)) as conn:
            row = conn.execute(
                "SELECT id, preview_id, target, region, state, resource_id, url, error, created_at "
                "FROM aws_deployments WHERE id = ?",
                (identity,),
            ).fetchone()
            if row is None:
                raise NotFoundError("Deployment not found")
            record = dict(zip(
                ("id", "preview_id", "target", "region", "state", "resource_id", "url", "error", "created_at"),
                row,
            ))
            record.update(fields)
            conn.execute(
                "UPDATE aws_deployments SET state=?, resource_id=?, url=?, error=? WHERE id=?",
                (record["state"], record.get("resource_id"), record.get("url"),
                 record.get("error"), identity),
            )
            conn.commit()
        return record

    def _audit(
        self,
        username: str,
        operation: str,
        target: str,
        resource_id: str | None,
        state: str,
    ) -> None:
        with closing(sqlite3.connect(self.db_path, timeout=30)) as conn:
            conn.execute(
                "INSERT INTO aws_audit(username, operation, target, resource_id, state, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (username, operation, target, resource_id, state, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()

    @staticmethod
    def _preview_id(identity: str) -> str:
        if not _PREVIEW_ID.fullmatch(identity):
            raise ValidationError("Invalid preview identity")
        return identity

    def _verified_preview(self, identity: str) -> tuple[dict[str, Any], JobRecord]:
        identity = self._preview_id(identity)
        preview = self.previews.get(identity)
        if (
            preview.get("state") not in {"BUILT", "READY", "STOPPED", "START_FAILED", "EXPIRED"}
            or not preview.get("image_id")
        ):
            raise ValidationError("Build and verify the Docker image before requesting deployment")
        job = self.jobs.get(preview["job_id"])
        if not job.profile:
            raise ValidationError("Project analysis is missing; create a new project review")
        return preview, job

    def recommendation(self, identity: str) -> dict[str, Any]:
        preview, job = self._verified_preview(identity)
        profile = job.profile
        is_static = (
            profile.project_type.value == "static"
            or (
                profile.project_type.value == "node"
                and profile.web_build_tool in {"cra", "vite"}
            )
        )
        if is_static:
            target = "s3"
            reason = (
                "The detected app builds to browser assets, so S3 static website hosting "
                "fits better than running a container."
            )
            requirements = ["The built image must contain /usr/share/nginx/html/index.html."]
        else:
            target = "ec2"
            reason = (
                "This app needs a server process, so EC2 can run the verified container image. "
                "The image is published to ECR for the instance to pull."
            )
            requirements = []
            if not _AMI_ID.fullmatch(self.settings.aws_ec2_ami_id or ""):
                requirements.append(
                    "A region-compatible AMI is required (configure AIDEVOPS_AWS_EC2_AMI_ID)."
                )
            if not _INSTANCE_PROFILE_ARN.fullmatch(
                self.settings.aws_ec2_instance_profile_arn or ""
            ):
                requirements.append(
                    "An EC2 instance profile with ECR pull access is required."
                )
            if self.settings.aws_mode == "localstack":
                requirements.append(
                    "LocalStack EC2 deployments require ECR support in the active license."
                )
        existing = self._deployment_for_preview(preview["id"])
        return {
            "preview_id": preview["id"],
            "project_type": profile.project_type.value,
            "target": target,
            "reason": reason,
            "requirements": requirements,
            "existing_deployment": existing,
            "public_access_confirmation_required": True,
            "cost_warning": (
                "AWS deployment can incur charges. EC2 instances continue running until stopped "
                "in the AWS console; Aidevops does not currently stop or delete cloud resources."
            ),
        }

    def status(self) -> dict[str, Any]:
        mode = self.settings.aws_mode
        endpoint = self._endpoint_display()
        try:
            identity = self._client("sts").get_caller_identity()
        except AwsManagementError as exc:
            return {
                "available": False,
                "mode": mode,
                "endpoint": endpoint,
                "region": self.settings.aws_region,
                "account_id": None,
                "message": exc.message,
            }
        except (ClientError, BotoCoreError, OSError) as exc:
            return {
                "available": False,
                "mode": mode,
                "endpoint": endpoint,
                "region": self.settings.aws_region,
                "account_id": None,
                "message": self._connection_failure_message(exc, mode),
            }
        return {
            "available": True,
            "mode": mode,
            "endpoint": endpoint,
            "region": self.settings.aws_region,
            "account_id": identity.get("Account"),
            "message": "Connected",
        }

    @staticmethod
    def _connection_failure_message(exc: Exception, mode: str) -> str:
        if mode == "localstack":
            return "Could not connect to LocalStack. Start it and verify AIDEVOPS_AWS_ENDPOINT_URL."
        if isinstance(exc, ClientError):
            code = str((exc.response.get("Error") or {}).get("Code") or "")
            if code in {
                "ExpiredToken",
                "ExpiredTokenException",
                "InvalidClientTokenId",
                "UnrecognizedClientException",
            }:
                return (
                    "AWS credentials are expired or invalid. Refresh the configured credentials; "
                    "for AWS IAM Identity Center, run `aws sso login --profile <profile-name>` "
                    "on the backend host, then retry."
                )
        if type(exc).__name__ in {
            "TokenRetrievalError",
            "SSOTokenLoadError",
            "UnauthorizedSSOTokenError",
        }:
            return (
                "The AWS IAM Identity Center session is missing or expired. On the backend host, "
                "run `aws sso login --profile <profile-name>` using the profile in AWS_PROFILE, "
                "then check the connection again."
            )
        if type(exc).__name__ in {"NoCredentialsError", "ProfileNotFound"}:
            return (
                "AWS credentials are unavailable to the backend. Configure the AWS profile or "
                "credential source for the account running FastAPI, then retry."
            )
        return "Could not connect to AWS using the configured region and credentials."

    def overview(self, *, include_memory: bool = False) -> dict[str, Any]:
        status = self.status()
        if not status["available"]:
            raise AwsManagementError(status["message"], status_code=503)
        try:
            ec2 = self._client("ec2")
            s3 = self._client("s3")
            instances = []
            paginator = ec2.get_paginator("describe_instances")
            metric_count = 0
            for page in paginator.paginate():
                for reservation in page.get("Reservations", []):
                    for instance in reservation.get("Instances", []):
                        state = instance.get("State", {}).get("Name", "unknown")
                        instance_id = instance.get("InstanceId")
                        include_metrics = (
                            state == "running"
                            and bool(instance_id)
                            and metric_count < 10
                        )
                        instances.append(
                            {
                                "id": instance_id,
                                "name": next(
                                    (tag.get("Value") for tag in instance.get("Tags", [])
                                     if tag.get("Key") == "Name"),
                                    "Unnamed instance",
                                ),
                                "state": state,
                                "type": instance.get("InstanceType"),
                                "public_ip": instance.get("PublicIpAddress"),
                                "launch_time": (
                                    instance["LaunchTime"].isoformat()
                                    if instance.get("LaunchTime") else None
                                ),
                                "cpu_percent": (
                                    self._cpu_metric(instance_id) if include_metrics else None
                                ),
                                "memory_percent": (
                                    self._memory_metric(instance_id)
                                    if include_memory and include_metrics else None
                                ),
                            }
                        )
                        if include_metrics:
                            metric_count += 1
                        if len(instances) >= 100:
                            break
                    if len(instances) >= 100:
                        break
                if len(instances) >= 100:
                    break
            buckets = [
                {"name": bucket["Name"], "created_at": bucket.get("CreationDate").isoformat()
                 if bucket.get("CreationDate") else None}
                for bucket in s3.list_buckets().get("Buckets", [])[:100]
            ]
        except (ClientError, BotoCoreError, OSError):
            raise AwsManagementError("AWS resources could not be loaded. Verify service access and try again.")
        return {
            **status,
            "instances": instances,
            "buckets": buckets,
            "deployments": self.list_deployments(),
        }

    def _cpu_metric(self, instance_id: str) -> float | None:
        try:
            end = datetime.now(timezone.utc)
            response = self._client("cloudwatch").get_metric_statistics(
                Namespace="AWS/EC2",
                MetricName="CPUUtilization",
                Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                StartTime=end - timedelta(minutes=30),
                EndTime=end,
                Period=300,
                Statistics=["Average"],
            )
            points = response.get("Datapoints", [])
            latest = max(points, key=lambda point: point["Timestamp"]) if points else None
            return round(latest["Average"], 2) if latest else None
        except (ClientError, BotoCoreError, OSError):
            return None

    def _memory_metric(self, instance_id: str) -> float | None:
        try:
            end = datetime.now(timezone.utc)
            response = self._client("cloudwatch").get_metric_statistics(
                Namespace="CWAgent",
                MetricName="mem_used_percent",
                Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                StartTime=end - timedelta(minutes=30),
                EndTime=end,
                Period=300,
                Statistics=["Average"],
            )
            points = response.get("Datapoints", [])
            latest = max(points, key=lambda point: point["Timestamp"]) if points else None
            return round(latest["Average"], 2) if latest else None
        except (ClientError, BotoCoreError, OSError):
            return None

    def list_deployments(self) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.db_path, timeout=30)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, preview_id, target, region, state, resource_id, url, error, created_at "
                "FROM aws_deployments ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        return [dict(row) for row in rows]

    def _deployment_for_preview(self, preview_id: str) -> dict[str, Any] | None:
        with closing(sqlite3.connect(self.db_path, timeout=30)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, preview_id, target, region, state, resource_id, url, error, created_at "
                "FROM aws_deployments WHERE preview_id = ? AND "
                "(state IN ('DEPLOYING', 'DEPLOYED') OR "
                "(state = 'FAILED' AND error LIKE '%cleanup may be incomplete%')) "
                "ORDER BY created_at DESC LIMIT 1",
                (preview_id,),
            ).fetchone()
        return dict(row) if row else None

    def deploy(
        self,
        username: str,
        identity: str,
        target: str,
        *,
        approved: bool,
        public_access_confirmed: bool,
    ) -> dict[str, Any]:
        if not approved:
            raise ValidationError("Deployment requires explicit approval")
        if not public_access_confirmed:
            raise ValidationError(
                "Public access requires a separate confirmation because the deployed website will be internet-accessible"
            )
        if target not in {"s3", "ec2"}:
            raise ValidationError("Target must be 's3' or 'ec2'")
        preview, job = self._verified_preview(identity)
        if self._deployment_for_preview(preview["id"]):
            raise ValidationError("This preview already has an active or completed AWS deployment")
        suggested = self.recommendation(identity)["target"]
        if target != suggested:
            raise ValidationError(
                f"This project is recommended for {suggested}; review its packaging requirements before overriding the recommendation"
            )

        record = self._deployment(
            {
                "id": "aws_" + uuid.uuid4().hex[:16],
                "preview_id": preview["id"],
                "target": target,
                "region": self.settings.aws_region,
                "state": "DEPLOYING",
                "resource_id": None,
                "url": None,
                "error": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._audit(username, "deploy", target, record["id"], "started")
        try:
            result = self._deploy_s3(preview, record) if target == "s3" else self._deploy_ec2(preview, job, record)
            record = self._update_deployment(
                record["id"], state="DEPLOYED",
                resource_id=result["resource_id"], url=result.get("url"), error=None,
            )
            self._audit(username, "deploy", target, record["id"], "succeeded")
            return record
        except (AwsManagementError, PolicyError, ValidationError) as exc:
            record = self._update_deployment(record["id"], state="FAILED", error=str(exc))
            self._audit(username, "deploy", target, record["id"], "failed")
            raise
        except (ClientError, BotoCoreError, OSError) as exc:
            error_message = self._deployment_failure_message(exc, target)
            record = self._update_deployment(
                record["id"], state="FAILED", error=error_message
            )
            self._audit(username, "deploy", target, record["id"], "failed")
            log.warning("AWS deployment failed", extra={"event": "aws_deploy_failed", "target": target})
            raise AwsManagementError(
                error_message,
                status_code=403 if self._is_access_denied(exc) else 502,
            ) from exc
        except Exception as exc:
            self._update_deployment(
                record["id"], state="FAILED",
                error="Deployment failed unexpectedly; no success was recorded.",
            )
            self._audit(username, "deploy", target, record["id"], "failed")
            log.warning(
                "AWS deployment failed unexpectedly",
                extra={"event": "aws_deploy_failed", "target": target},
            )
            raise AwsManagementError(
                "Deployment failed unexpectedly. Check the service log for the operation name."
            ) from exc

    def _deployment_failure_message(self, exc: Exception, target: str) -> str:
        if isinstance(exc, ClientError):
            error = exc.response.get("Error") or {}
            code = str(error.get("Code") or "")
            details = str(error.get("Message") or "").casefold()
            if (
                target == "ec2"
                and self.settings.aws_mode == "localstack"
                and "ecr" in details
                and "not included within your localstack license" in details
            ):
                return (
                    "EC2 deployment requires ECR, but the active LocalStack license does not "
                    "include ECR. Use a LocalStack license with ECR support or switch to real "
                    "AWS mode with ECR permissions."
                )
            if code in {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"}:
                operation = exc.operation_name or "AWS operation"
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,63}", operation):
                    operation = "AWS operation"
                if target == "ec2":
                    permissions = (
                        "grant the backend role the required EC2 launch/security-group and ECR "
                        "image-push permissions; RunInstances also requires iam:PassRole for the "
                        "configured instance-profile role"
                    )
                else:
                    permissions = (
                        "grant the backend role the required S3 bucket, object, website, and policy "
                        "permissions, and check account-level S3 Block Public Access settings"
                    )
                return f"AWS denied {operation}. Check that you {permissions}."
        return (
            "Deployment failed. Verify service availability and AWS permissions; "
            "no success was recorded."
        )

    @staticmethod
    def _is_access_denied(exc: Exception) -> bool:
        if not isinstance(exc, ClientError):
            return False
        code = str((exc.response.get("Error") or {}).get("Code") or "")
        return code in {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"}

    def _deploy_s3(
        self, preview: dict[str, Any], record: dict[str, Any]
    ) -> dict[str, Any]:
        files = self._static_files(preview)
        bucket = "aidevops-" + record["id"].lower().replace("_", "-")
        s3 = self._client("s3")
        if self.settings.aws_region == "us-east-1":
            s3.create_bucket(Bucket=bucket)
        else:
            s3.create_bucket(
                Bucket=bucket,
                CreateBucketConfiguration={"LocationConstraint": self.settings.aws_region},
            )
        try:
            s3.put_public_access_block(
                Bucket=bucket,
                PublicAccessBlockConfiguration={
                    "BlockPublicAcls": True,
                    "IgnorePublicAcls": True,
                    "BlockPublicPolicy": False,
                    "RestrictPublicBuckets": False,
                },
            )
            self._upload_static_files(s3, bucket, files)
            s3.put_bucket_website(
                Bucket=bucket,
                WebsiteConfiguration={
                    "IndexDocument": {"Suffix": "index.html"},
                    "ErrorDocument": {"Key": "index.html"},
                },
            )
            policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "PublicReadWebsiteFiles",
                        "Effect": "Allow",
                        "Principal": "*",
                        "Action": "s3:GetObject",
                        "Resource": f"arn:aws:s3:::{bucket}/*",
                    }
                ],
            }
            s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))
            s3.put_bucket_tagging(
                Bucket=bucket,
                Tagging={"TagSet": [
                    {"Key": "ManagedBy", "Value": "Aidevops"},
                    {"Key": "DeploymentId", "Value": record["id"]},
                ]},
            )
        except Exception:
            if not self._cleanup_failed_bucket(s3, bucket):
                raise AwsManagementError(
                    "Static-site deployment failed and cleanup may be incomplete. "
                    f"Check the newly created bucket {bucket} before retrying."
                )
            raise
        if self.settings.aws_mode == "localstack":
            endpoint = self.settings.aws_endpoint_url or "http://localhost:4566"
            parsed = urlsplit(endpoint)
            if parsed.hostname in {"localhost", "127.0.0.1"}:
                port = f":{parsed.port}" if parsed.port else ""
                url = f"{parsed.scheme}://{bucket}.s3-website.localhost.localstack.cloud{port}"
            else:
                url = f"{endpoint.rstrip('/')}/{bucket}/index.html"
        else:
            dns_suffix = "amazonaws.com.cn" if self.settings.aws_region.startswith("cn-") else "amazonaws.com"
            url = f"http://{bucket}.s3-website-{self.settings.aws_region}.{dns_suffix}"
        return {"resource_id": bucket, "url": url}

    @staticmethod
    def _upload_static_files(
        s3, bucket: str, files: list[tuple[str, bytes, str]]
    ) -> None:
        def upload_file(item: tuple[str, bytes, str]) -> None:
            key, content, content_type = item
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
            )

        with ThreadPoolExecutor(max_workers=max(1, min(8, len(files)))) as executor:
            list(executor.map(upload_file, files))

    @staticmethod
    def _cleanup_failed_bucket(s3, bucket: str) -> bool:
        try:
            paginator = s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket):
                objects = page.get("Contents", [])
                if not objects:
                    continue
                s3.delete_objects(
                    Bucket=bucket,
                    Delete={"Objects": [{"Key": item["Key"]} for item in objects]},
                )
            s3.delete_bucket(Bucket=bucket)
            return True
        except Exception:
            log.warning(
                "Could not clean up incomplete AWS website bucket",
                extra={"event": "aws_partial_resource_cleanup_failed"},
            )
            return False

    def _static_files(
        self, preview: dict[str, Any]
    ) -> list[tuple[str, bytes, str]]:
        try:
            import docker

            engine = docker.from_env()
            container = None
            archive_buffer = tempfile.SpooledTemporaryFile(max_size=10 * 1024 * 1024, mode="w+b")
            try:
                image = engine.images.get(preview["image_id"])
                labels = (image.attrs.get("Config") or {}).get("Labels") or {}
                if labels.get("io.aidevops.preview") != preview["id"]:
                    raise PolicyError("The Docker image is not owned by this verified preview")
                container = engine.containers.create(
                    preview["image_id"],
                    command=["true"],
                    network_disabled=True,
                    read_only=True,
                    cap_drop=["ALL"],
                    mem_limit="256m",
                    pids_limit=64,
                )
                chunks, _ = container.get_archive(_STATIC_PATH)
                for chunk in chunks:
                    archive_buffer.write(chunk)
                    if archive_buffer.tell() > _MAX_STATIC_BYTES:
                        raise ValidationError("The static site archive exceeds the 100 MiB deployment limit")
                archive_buffer.seek(0)
                return self._unpack_static_archive(archive_buffer)
            finally:
                archive_buffer.close()
                if container is not None:
                    container.remove(force=True)
                engine.close()
        except (PolicyError, ValidationError):
            raise
        except Exception as exc:
            raise AwsManagementError(
                "Could not read the verified static-site files from the built image. "
                "Confirm the image contains /usr/share/nginx/html."
            ) from exc

    @staticmethod
    def _unpack_static_archive(
        archive_bytes: bytes | BinaryIO,
    ) -> list[tuple[str, bytes, str]]:
        files = []
        total_bytes = 0
        try:
            fileobj = io.BytesIO(archive_bytes) if isinstance(archive_bytes, bytes) else archive_bytes
            archive = tarfile.open(fileobj=fileobj, mode="r:*")
        except tarfile.TarError as exc:
            raise ValidationError("The static site archive from Docker is invalid") from exc
        with archive:
            for member in archive:
                if member.isdir():
                    continue
                path = PurePosixPath(member.name)
                parts = [part for part in path.parts if part not in {"", "."}]
                if parts and parts[0] == "html":
                    parts = parts[1:]
                if (
                    not member.isfile()
                    or not parts
                    or path.is_absolute()
                    or any(part == ".." for part in parts)
                    or any("\\" in part or "\x00" in part for part in parts)
                ):
                    raise ValidationError("The static site contains an unsafe archive entry")
                if len(files) >= _MAX_STATIC_FILES:
                    raise ValidationError("The static site contains too many files (limit 5000)")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValidationError("The static site contains an unreadable file")
                content = stream.read(_MAX_STATIC_BYTES - total_bytes + 1)
                total_bytes += len(content)
                if total_bytes > _MAX_STATIC_BYTES:
                    raise ValidationError("The static site exceeds the 100 MiB deployment limit")
                key = "/".join(parts)
                content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
                files.append((key, content, content_type))
        if not any(key == "index.html" for key, _, _ in files):
            raise ValidationError("The static image does not contain index.html at its web root")
        return files

    def _deploy_ec2(
        self, preview: dict[str, Any], job: JobRecord, record: dict[str, Any]
    ) -> dict[str, Any]:
        if not self.settings.aws_ec2_ami_id:
            raise ValidationError("Configure AIDEVOPS_AWS_EC2_AMI_ID before deploying to EC2")
        if not _AMI_ID.fullmatch(self.settings.aws_ec2_ami_id):
            raise ValidationError("AIDEVOPS_AWS_EC2_AMI_ID must be a valid AMI identifier")
        if not self.settings.aws_ec2_instance_profile_arn:
            raise ValidationError(
                "Configure AIDEVOPS_AWS_EC2_INSTANCE_PROFILE_ARN with an instance profile that can pull from ECR"
            )
        if not _INSTANCE_PROFILE_ARN.fullmatch(
            self.settings.aws_ec2_instance_profile_arn
        ):
            raise ValidationError("AIDEVOPS_AWS_EC2_INSTANCE_PROFILE_ARN must be an instance-profile ARN")
        profile = job.profile
        port = preview.get("suggested_port") or profile.suggested_port or 8080
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValidationError("The detected app port is invalid")

        ec2 = self._client("ec2")
        vpcs = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}]).get("Vpcs", [])
        if not vpcs:
            raise ValidationError("No default VPC is available in this region; configure one before deployment")
        vpc_id = vpcs[0]["VpcId"]
        subnets = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]).get("Subnets", [])
        if not subnets:
            raise ValidationError("No subnet is available in the default VPC")
        subnet = subnets[0]["SubnetId"]
        ecr = self._client("ecr")
        repo_name = record["id"].replace("_", "-")
        repository = None
        repository_created = False
        group_id = None
        instance_id = None
        try:
            repository = ecr.create_repository(
                repositoryName=repo_name,
                imageScanningConfiguration={"scanOnPush": True},
                tags=[
                    {"Key": "ManagedBy", "Value": "Aidevops"},
                    {"Key": "DeploymentId", "Value": record["id"]},
                ],
            )["repository"]
            repository_created = True
            registry_id = repository.get("registryId")
            registry = repository["repositoryUri"].split("/")[0]
            auth = ecr.get_authorization_token(registryIds=[registry_id])["authorizationData"][0]
            username, password = base64.b64decode(auth["authorizationToken"]).decode("utf-8").split(":", 1)
            self._push_image(preview, repository["repositoryUri"], username, password)

            group_name = "aidevops-" + record["id"][-8:]
            group = ec2.create_security_group(
                GroupName=group_name,
                Description=f"Aidevops deployment {record['id']} HTTP ingress",
                VpcId=vpc_id,
                TagSpecifications=[{
                    "ResourceType": "security-group",
                    "Tags": [{"Key": "ManagedBy", "Value": "Aidevops"},
                             {"Key": "DeploymentId", "Value": record["id"]}],
                }],
            )
            group_id = group["GroupId"]
            ec2.authorize_security_group_ingress(
                GroupId=group_id,
                IpPermissions=[{
                    "IpProtocol": "tcp",
                    "FromPort": 80,
                    "ToPort": 80,
                    "IpRanges": [{
                        "CidrIp": "0.0.0.0/0",
                        "Description": "Public web access approved in Aidevops",
                    }],
                }],
            )
            script = (
                "#!/bin/bash\nset -euo pipefail\n"
                "dnf install -y docker awscli\n"
                "systemctl enable --now docker\n"
                f"aws ecr get-login-password --region {self.settings.aws_region} | "
                f"docker login --username AWS --password-stdin {registry}\n"
                f"docker run -d --restart unless-stopped --memory=768m --pids-limit=128 "
                "--cap-drop=ALL --security-opt=no-new-privileges "
                "--log-opt max-size=1m "
                f"--log-opt max-file=1 -p 80:{port} "
                f"{repository['repositoryUri']}:latest\n"
            )
            response = ec2.run_instances(
                ImageId=self.settings.aws_ec2_ami_id,
                InstanceType="t3.micro",
                MinCount=1,
                MaxCount=1,
                IamInstanceProfile={"Arn": self.settings.aws_ec2_instance_profile_arn},
                NetworkInterfaces=[{
                    "DeviceIndex": 0,
                    "SubnetId": subnet,
                    "Groups": [group_id],
                    "AssociatePublicIpAddress": True,
                }],
                UserData=script,
                TagSpecifications=[{
                    "ResourceType": "instance",
                    "Tags": [{"Key": "Name", "Value": record["id"]},
                             {"Key": "ManagedBy", "Value": "Aidevops"},
                             {"Key": "DeploymentId", "Value": record["id"]}],
                }],
            )
            instance_id = response["Instances"][0]["InstanceId"]
            ec2.get_waiter("instance_running").wait(
                InstanceIds=[instance_id], WaiterConfig={"Delay": 5, "MaxAttempts": 24}
            )
            instance = ec2.describe_instances(InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]
            public_ip = instance.get("PublicIpAddress")
            if not public_ip:
                raise AwsManagementError("The EC2 instance started without a public IP address.")
        except Exception as exc:
            if not self._cleanup_failed_ec2(
                ecr, ec2, repo_name if repository_created else None, group_id, instance_id
            ):
                raise AwsManagementError(
                    "EC2 deployment failed and cleanup may be incomplete. "
                    f"Check resources tagged with deployment ID {record['id']} before retrying."
                ) from exc
            raise
        return {
            "resource_id": instance_id,
            "url": (
                f"http://{public_ip}/docs"
                if getattr(profile, "framework", None) == "FastAPI"
                else f"http://{public_ip}"
            ),
        }

    @staticmethod
    def _cleanup_failed_ec2(
        ecr, ec2, repo_name: str | None, group_id: str | None, instance_id: str | None
    ) -> bool:
        cleanup_ok = True
        if instance_id:
            try:
                ec2.terminate_instances(InstanceIds=[instance_id])
                ec2.get_waiter("instance_terminated").wait(
                    InstanceIds=[instance_id], WaiterConfig={"Delay": 5, "MaxAttempts": 24}
                )
            except Exception:
                cleanup_ok = False
                log.warning(
                    "Could not terminate incomplete EC2 instance",
                    extra={"event": "aws_partial_resource_cleanup_failed"},
                )
        if group_id:
            try:
                ec2.delete_security_group(GroupId=group_id)
            except Exception:
                cleanup_ok = False
                log.warning(
                    "Could not remove incomplete EC2 security group",
                    extra={"event": "aws_partial_resource_cleanup_failed"},
                )
        if repo_name:
            try:
                ecr.delete_repository(repositoryName=repo_name, force=True)
            except Exception:
                cleanup_ok = False
                log.warning(
                    "Could not remove incomplete ECR repository",
                    extra={"event": "aws_partial_resource_cleanup_failed"},
                )
        return cleanup_ok

    @staticmethod
    def _push_image(
        preview: dict[str, Any], repository_uri: str, username: str, password: str
    ) -> None:
        engine = None
        image_ref = None
        try:
            import docker

            engine = docker.from_env()
            image = engine.images.get(preview["image_id"])
            labels = (image.attrs.get("Config") or {}).get("Labels") or {}
            if labels.get("io.aidevops.preview") != preview["id"]:
                raise PolicyError("The Docker image is not owned by this verified preview")
            repository, tag = repository_uri.rsplit(":", 1) if ":" in repository_uri.split("/")[-1] else (repository_uri, "latest")
            engine.api.tag(preview["image_id"], repository, tag=tag, force=True)
            image_ref = f"{repository}:{tag}"
            events = engine.api.push(
                repository,
                tag=tag,
                auth_config={"username": username, "password": password},
                decode=True,
            )
            for event in events:
                if event.get("error") or event.get("errorDetail"):
                    raise AwsManagementError("Docker could not publish the image to the configured ECR repository.")
        except (PolicyError, AwsManagementError):
            raise
        except Exception as exc:
            raise AwsManagementError(
                "Could not publish the verified Docker image to ECR. Check Docker Engine and registry access."
            ) from exc
        finally:
            if engine is not None:
                if image_ref:
                    try:
                        engine.images.remove(image_ref, force=False)
                    except Exception:
                        log.warning(
                            "Could not remove local ECR image tag",
                            extra={"event": "aws_local_image_tag_cleanup_failed"},
                        )
                try:
                    engine.close()
                except Exception:
                    log.warning(
                        "Could not close local Docker client",
                        extra={"event": "aws_docker_client_close_failed"},
                    )
