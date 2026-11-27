"""Validated AWS infrastructure operations and allowlisted SSM Docker controls."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from botocore.exceptions import BotoCoreError, ClientError

from ..config import Settings
from ..privacy import redact
from .aws_manager import AwsManagementError

_INSTANCE_ID = re.compile(r"^i-[0-9a-f]{8,17}$")
_AMI_ID = re.compile(r"^ami-[0-9a-f]{8,17}$")
_SUBNET_ID = re.compile(r"^subnet-[0-9a-f]{8,17}$")
_SECURITY_GROUP_ID = re.compile(r"^sg-[0-9a-f]{8,17}$")
_INSTANCE_PROFILE_ARN = re.compile(
    r"^arn:(?:aws|aws-us-gov|aws-cn):iam::\d{12}:instance-profile/"
    r"(?:[A-Za-z0-9+=,.@_-]+/)*[A-Za-z0-9+=,.@_-]+$"
)
_CONTAINER_ID = re.compile(r"^(?:[0-9a-f]{12}|[0-9a-f]{64})$")
_COMMAND_ID = re.compile(r"^[0-9a-f-]{36}$")
_CONTAINER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
_TAG_KEY = re.compile(r"^[A-Za-z0-9 _.:/=+@-]{1,128}$")
_TAG_VALUE = re.compile(r"^[A-Za-z0-9 _.:/=+@-]{0,256}$")
_ECR_IMAGE = re.compile(
    r"^(?P<account>\d{12})\.dkr\.ecr\.(?P<region>[a-z0-9-]+)\.amazonaws\.com/"
    r"[a-z0-9][a-z0-9._/-]{0,254}:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$"
)
_SECRET_TAG = re.compile(r"(?:secret|password|token|credential|access.?key)", re.I)
_ALLOWED_DOCKER_ACTIONS = {"list", "logs", "start", "stop", "restart", "remove", "deploy"}


class AwsInfrastructureError(Exception):
    """Safe, user-readable error raised by infrastructure operations."""

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AwsInfrastructureService:
    """AWS lifecycle, cost, monitoring, and SSM operations."""

    def __init__(
        self,
        settings: Settings,
        client_factory: Callable[..., Any],
        db_path: str | Path,
    ) -> None:
        self.settings = settings
        self.client_factory = client_factory
        self.db_path = db_path
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS aws_infrastructure_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    resource_id TEXT,
                    command_id TEXT,
                    state TEXT NOT NULL,
                    error TEXT,
                    duration_ms INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(aws_infrastructure_audit)")
            }
            if "command_id" not in columns:
                conn.execute(
                    "ALTER TABLE aws_infrastructure_audit ADD COLUMN command_id TEXT"
                )

    def _client(self, service: str, *, region_name: str | None = None) -> Any:
        try:
            return self.client_factory(service, region_name=region_name)
        except AwsManagementError as exc:
            raise AwsInfrastructureError(exc.message, status_code=exc.status_code) from exc

    @staticmethod
    def _validate_instance_id(instance_id: str) -> str:
        if not isinstance(instance_id, str) or not _INSTANCE_ID.fullmatch(instance_id):
            raise AwsInfrastructureError("Invalid EC2 instance ID.", status_code=422)
        return instance_id

    @staticmethod
    def _map_aws_error(exc: Exception) -> AwsInfrastructureError:
        if isinstance(exc, ClientError):
            error = exc.response.get("Error") or {}
            code = str(error.get("Code") or "")
            operation = exc.operation_name or "AWS operation"
            if code in {"InvalidInstanceID.NotFound", "InvalidInstanceID.Malformed"}:
                return AwsInfrastructureError("The EC2 instance was not found.", status_code=404)
            if code == "InvalidInstanceId":
                return AwsInfrastructureError("The EC2 instance was not found.", status_code=404)
            if code == "InvocationDoesNotExist":
                return AwsInfrastructureError(
                    "The SSM command is not available for this instance yet.", status_code=404
                )
            if code in {
                "InvalidAMIID.NotFound",
                "InvalidSubnetID.NotFound",
                "InvalidGroup.NotFound",
                "InvalidIamInstanceProfile.NotFound",
            }:
                return AwsInfrastructureError(
                    "An AMI, subnet, security group, or instance profile was not found in this region.",
                    status_code=422,
                )
            if code in {"IncorrectInstanceState", "InvalidInstanceState"}:
                return AwsInfrastructureError(
                    "The EC2 instance is in a state that does not allow this operation.",
                    status_code=409,
                )
            if code in {"UnauthorizedOperation", "AccessDenied", "AccessDeniedException"}:
                return AwsInfrastructureError(
                    f"AWS denied {operation}. Review the backend profile's scoped IAM permissions.",
                    status_code=403,
                )
            if code in {"Throttling", "ThrottlingException", "RequestLimitExceeded"}:
                return AwsInfrastructureError(
                    "AWS is throttling requests. Wait briefly and retry.", status_code=429
                )
        if isinstance(exc, (BotoCoreError, OSError)):
            return AwsInfrastructureError(
                "Could not reach the AWS service. Check the backend credentials, network, and region.",
                status_code=503,
            )
        return AwsInfrastructureError("The AWS operation failed.", status_code=502)

    def _call(self, callback: Callable[[], Any]) -> Any:
        try:
            return callback()
        except AwsInfrastructureError:
            raise
        except (ClientError, BotoCoreError, OSError) as exc:
            raise self._map_aws_error(exc) from exc

    def _audit(
        self,
        username: str,
        operation: str,
        resource_id: str | None,
        state: str,
        error: str | None,
        duration_ms: int,
        command_id: str | None = None,
    ) -> None:
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.execute(
                """
                INSERT INTO aws_infrastructure_audit
                    (username, operation, resource_id, command_id, state, error, duration_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    username,
                    operation,
                    resource_id,
                    command_id,
                    state,
                    error,
                    duration_ms,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def _audited(
        self,
        username: str,
        operation: str,
        resource_id: str | None,
        callback: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            result = callback()
        except Exception as exc:
            safe_message = redact(str(exc))[:500]
            self._audit(
                username,
                operation,
                resource_id,
                "FAILED",
                safe_message or "Operation failed.",
                int((time.monotonic() - started) * 1000),
            )
            raise
        state = str(result.get("operation_state") or "SUCCEEDED")
        self._audit(
            username,
            operation,
            resource_id or result.get("instance_id") or result.get("command_id"),
            state,
            None,
            int((time.monotonic() - started) * 1000),
            result.get("command_id"),
        )
        return result

    @staticmethod
    def _serialize_instance(instance: dict[str, Any]) -> dict[str, Any]:
        tags = instance.get("Tags", [])
        name = next(
            (tag.get("Value") for tag in tags if tag.get("Key") == "Name"),
            "Unnamed instance",
        )
        name = redact(name) if isinstance(name, str) else "Unnamed instance"
        launch_time = instance.get("LaunchTime")
        return {
            "instance_id": instance.get("InstanceId"),
            "name": name,
            "state": (instance.get("State") or {}).get("Name", "unknown"),
            "state_code": (instance.get("State") or {}).get("Code"),
            "instance_type": instance.get("InstanceType"),
            "ami_id": instance.get("ImageId"),
            "launch_time": launch_time.isoformat() if launch_time else None,
            "public_ip": instance.get("PublicIpAddress"),
            "private_ip": instance.get("PrivateIpAddress"),
            "vpc_id": instance.get("VpcId"),
            "subnet_id": instance.get("SubnetId"),
            "key_name": instance.get("KeyName"),
            "security_groups": [
                {"id": group.get("GroupId"), "name": group.get("GroupName")}
                for group in instance.get("SecurityGroups", [])
            ],
        }

    def list_instances(self, state: str | None = None, limit: int = 100) -> dict[str, Any]:
        allowed_states = {
            "pending",
            "running",
            "shutting-down",
            "terminated",
            "stopping",
            "stopped",
        }
        if state is not None and (
            not isinstance(state, str) or state not in allowed_states
        ):
            raise AwsInfrastructureError("Unsupported EC2 instance state filter.", status_code=422)
        if type(limit) is not int or not 1 <= limit <= 200:
            raise AwsInfrastructureError("Instance list limit must be between 1 and 200.", status_code=422)
        filters = [{"Name": "instance-state-name", "Values": [state]}] if state else []

        def fetch() -> dict[str, Any]:
            ec2 = self._client("ec2")
            paginator = ec2.get_paginator("describe_instances")
            instances = []
            for page in paginator.paginate(Filters=filters):
                for reservation in page.get("Reservations", []):
                    for instance in reservation.get("Instances", []):
                        instances.append(self._serialize_instance(instance))
                        if len(instances) > limit:
                            return {"instances": instances[:limit], "truncated": True}
            return {"instances": instances, "truncated": False}

        return self._call(fetch)

    def _describe_instance(self, instance_id: str) -> dict[str, Any]:
        identity = self._validate_instance_id(instance_id)
        response = self._call(
            lambda: self._client("ec2").describe_instances(InstanceIds=[identity])
        )
        reservations = response.get("Reservations", [])
        instances = [
            instance
            for reservation in reservations
            for instance in reservation.get("Instances", [])
        ]
        if not instances:
            raise AwsInfrastructureError("The EC2 instance was not found.", status_code=404)
        return instances[0]

    def get_instance(self, instance_id: str) -> dict[str, Any]:
        identity = self._validate_instance_id(instance_id)
        instance = self._describe_instance(identity)
        checks = self._call(
            lambda: self._client("ec2").describe_instance_status(
                InstanceIds=[identity], IncludeAllInstances=True
            )
        ).get("InstanceStatuses", [])
        status = checks[0] if checks else {}
        return {
            **self._serialize_instance(instance),
            "instance_status": (status.get("InstanceStatus") or {}).get("Status"),
            "system_status": (status.get("SystemStatus") or {}).get("Status"),
            "instance_status_checks": (status.get("InstanceStatus") or {}).get("Details", []),
            "system_status_checks": (status.get("SystemStatus") or {}).get("Details", []),
            "iam_instance_profile_arn": (instance.get("IamInstanceProfile") or {}).get("Arn"),
            "root_device_type": instance.get("RootDeviceType"),
            "architecture": instance.get("Architecture"),
        }

    def create_instance(
        self,
        username: str,
        *,
        ami_id: str,
        instance_type: str,
        subnet_id: str,
        security_group_ids: list[str],
        name: str,
        instance_profile_arn: str | None = None,
        key_name: str | None = None,
        associate_public_ip: bool = False,
        public_access_confirmed: bool = False,
        bootstrap_docker: bool = False,
        tags: dict[str, str] | None = None,
        dry_run: bool = False,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        if not _AMI_ID.fullmatch(ami_id or ""):
            raise AwsInfrastructureError("AMI ID is invalid.", status_code=422)
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,31}", instance_type or ""):
            raise AwsInfrastructureError("Instance type is invalid.", status_code=422)
        if not _SUBNET_ID.fullmatch(subnet_id or ""):
            raise AwsInfrastructureError("Subnet ID is invalid.", status_code=422)
        if not security_group_ids or len(security_group_ids) > 5 or any(
            not _SECURITY_GROUP_ID.fullmatch(group_id) for group_id in security_group_ids
        ):
            raise AwsInfrastructureError(
                "Provide between one and five valid security group IDs.", status_code=422
            )
        if not name or len(name) > 128 or not _TAG_VALUE.fullmatch(name):
            raise AwsInfrastructureError("Instance name tag is invalid.", status_code=422)
        if instance_profile_arn and not _INSTANCE_PROFILE_ARN.fullmatch(instance_profile_arn):
            raise AwsInfrastructureError("Instance profile ARN is invalid.", status_code=422)
        if key_name is not None and not re.fullmatch(r"[A-Za-z0-9._-]{1,255}", key_name):
            raise AwsInfrastructureError("EC2 key pair name is invalid.", status_code=422)
        if (
            not isinstance(dry_run, bool)
            or not isinstance(confirmed, bool)
            or not isinstance(public_access_confirmed, bool)
        ):
            raise AwsInfrastructureError("Confirmation flags must be boolean.", status_code=422)
        if not public_access_confirmed:
            raise AwsInfrastructureError(
                "Confirm that the instance may be reachable through its public IP and security group.",
                status_code=422,
            )
        if not dry_run and not confirmed:
            raise AwsInfrastructureError(
                "Creating an EC2 instance requires explicit confirmation.", status_code=422
            )
        input_tags = tags or {}
        if len(input_tags) > 19 or any(
            not _TAG_KEY.fullmatch(key)
            or not _TAG_VALUE.fullmatch(value)
            or key.lower().startswith("aws:")
            or _SECRET_TAG.search(key)
            or key.casefold() in {"name", "managedby"}
            for key, value in input_tags.items()
        ):
            raise AwsInfrastructureError(
                "Tags must use valid AWS tag names and must not contain secret-like keys.",
                status_code=422,
            )
        tag_list = [
            {"Key": key, "Value": value} for key, value in input_tags.items()
        ]
        tag_list.extend(
            [
                {"Key": "Name", "Value": name},
                {"Key": "ManagedBy", "Value": "Aidevops"},
            ]
        )
        network_interface = {
            "DeviceIndex": 0,
            "SubnetId": subnet_id,
            "Groups": security_group_ids,
            "AssociatePublicIpAddress": associate_public_ip,
        }
        request: dict[str, Any] = {
            "ImageId": ami_id,
            "InstanceType": instance_type,
            "MinCount": 1,
            "MaxCount": 1,
            "ClientToken": str(uuid.uuid4()),
            "NetworkInterfaces": [network_interface],
            "TagSpecifications": [
                {"ResourceType": "instance", "Tags": tag_list},
                {"ResourceType": "volume", "Tags": tag_list},
            ],
            "DryRun": dry_run,
        }
        if instance_profile_arn:
            request["IamInstanceProfile"] = {"Arn": instance_profile_arn}
        if key_name:
            request["KeyName"] = key_name
        if bootstrap_docker:
            request["UserData"] = (
                "#!/bin/bash\nset -euo pipefail\n"
                "dnf install -y docker\n"
                "systemctl enable --now docker\n"
            )

        def launch() -> dict[str, Any]:
            try:
                result = self._client("ec2").run_instances(**request)
            except ClientError as exc:
                if dry_run and (exc.response.get("Error") or {}).get("Code") == "DryRunOperation":
                    return {"dry_run": True, "operation_state": "VALIDATED"}
                raise
            if dry_run:
                return {"dry_run": True, "operation_state": "VALIDATED"}
            instances = result.get("Instances", [])
            if not instances or not instances[0].get("InstanceId"):
                raise AwsInfrastructureError(
                    "AWS did not return the newly created instance ID."
                )
            created = instances[0]
            return {
                **self._serialize_instance(created),
                "iam_instance_profile_arn": instance_profile_arn,
                "operation_state": (created.get("State") or {}).get("Name", "pending"),
                "message": "Instance creation was accepted. Refresh its details to verify readiness.",
            }

        return self._audited(username, "create_instance", None, lambda: self._call(launch))

    def manage_instance(
        self,
        username: str,
        instance_id: str,
        action: str,
        *,
        confirmation: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        identity = self._validate_instance_id(instance_id)
        if not isinstance(action, str) or action not in {
            "start",
            "stop",
            "reboot",
            "terminate",
        }:
            raise AwsInfrastructureError("Unsupported EC2 action.", status_code=422)
        if not isinstance(dry_run, bool):
            raise AwsInfrastructureError("Dry-run flag must be boolean.", status_code=422)
        if action == "terminate" and confirmation != f"terminate {identity}":
            raise AwsInfrastructureError(
                f"Termination is permanent. Confirm by sending exactly: terminate {identity}",
                status_code=422,
            )

        def execute() -> dict[str, Any]:
            ec2 = self._client("ec2")
            instance = self._describe_instance(identity)
            current_state = (instance.get("State") or {}).get("Name", "unknown")
            expected_states = {
                "start": {"stopped"},
                "stop": {"running"},
                "reboot": {"running"},
                "terminate": {"pending", "running", "stopping", "stopped"},
            }
            if current_state not in expected_states[action]:
                raise AwsInfrastructureError(
                    f"Cannot {action} an instance in state '{current_state}'.",
                    status_code=409,
                )
            method = {
                "start": ec2.start_instances,
                "stop": ec2.stop_instances,
                "reboot": ec2.reboot_instances,
                "terminate": ec2.terminate_instances,
            }[action]
            try:
                result = method(InstanceIds=[identity], DryRun=dry_run)
            except ClientError as exc:
                code = str((exc.response.get("Error") or {}).get("Code") or "")
                if dry_run and code == "DryRunOperation":
                    return {
                        "instance_id": identity,
                        "action": action,
                        "dry_run": True,
                        "operation_state": "VALIDATED",
                    }
                raise
            if dry_run:
                return {
                    "instance_id": identity,
                    "action": action,
                    "dry_run": True,
                    "operation_state": "VALIDATED",
                }
            changes = result.get("StartingInstances") or result.get("StoppingInstances") or result.get("TerminatingInstances") or []
            state = (changes[0].get("CurrentState") or {}).get("Name") if changes else (
                "rebooting" if action == "reboot" else "accepted"
            )
            return {
                "instance_id": identity,
                "action": action,
                "state": state,
                "operation_state": "ACCEPTED",
                "message": (
                    "The action was accepted. Refresh instance details to verify its final state."
                ),
            }

        return self._audited(
            username, f"ec2_{action}", identity, lambda: self._call(execute)
        )

    def get_instance_metrics(self, instance_id: str) -> dict[str, Any]:
        identity = self._validate_instance_id(instance_id)
        self._describe_instance(identity)
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=60)
        definitions = {
            "cpu_percent": ("AWS/EC2", "CPUUtilization", "Average", "Percent"),
            "network_in_bytes": ("AWS/EC2", "NetworkIn", "Sum", "Bytes"),
            "network_out_bytes": ("AWS/EC2", "NetworkOut", "Sum", "Bytes"),
            "ebs_read_bytes": ("AWS/EC2", "EBSReadBytes", "Sum", "Bytes"),
            "ebs_write_bytes": ("AWS/EC2", "EBSWriteBytes", "Sum", "Bytes"),
            "memory_percent": ("CWAgent", "mem_used_percent", "Average", "Percent"),
        }
        cloudwatch = self._client("cloudwatch")
        metrics: dict[str, Any] = {}
        for key, (namespace, metric_name, statistic, unit) in definitions.items():
            try:
                response = self._call(
                    lambda namespace=namespace, metric_name=metric_name, statistic=statistic, unit=unit: (
                        cloudwatch.get_metric_statistics(
                            Namespace=namespace,
                            MetricName=metric_name,
                            Dimensions=[{"Name": "InstanceId", "Value": identity}],
                            StartTime=start,
                            EndTime=end,
                            Period=300,
                            Statistics=[statistic],
                            Unit=unit,
                        )
                    )
                )
            except AwsInfrastructureError as exc:
                if isinstance(exc.__cause__, ClientError) and (
                    (exc.__cause__.response.get("Error") or {}).get("Code")
                    in {"InvalidParameterValue", "ResourceNotFound", "ResourceNotFoundException"}
                ):
                    metrics[key] = None
                    continue
                raise
            points = response.get("Datapoints", [])
            latest = max(points, key=lambda point: point["Timestamp"]) if points else None
            metrics[key] = (
                round(float(latest[statistic]), 2) if latest and statistic in latest else None
            )
        checks = self._call(
            lambda: self._client("ec2").describe_instance_status(
                InstanceIds=[identity], IncludeAllInstances=True
            )
        ).get("InstanceStatuses", [])
        status = checks[0] if checks else {}
        metrics["instance_status_check"] = (status.get("InstanceStatus") or {}).get("Status")
        metrics["system_status_check"] = (status.get("SystemStatus") or {}).get("Status")
        metrics["period_minutes"] = 60
        metrics["message"] = (
            "Missing metrics are unavailable from CloudWatch. Memory requires the CloudWatch Agent."
        )
        return metrics

    def get_cost_report(
        self,
        start: date,
        end: date,
        granularity: str = "DAILY",
    ) -> dict[str, Any]:
        today = datetime.now(timezone.utc).date()
        if (
            type(start) is not date
            or type(end) is not date
            or start >= end
            or end > today
            or (end - start).days > 90
        ):
            raise AwsInfrastructureError(
                "Choose a completed date range of at most 90 days.", status_code=422
            )
        if granularity not in {"DAILY", "MONTHLY"}:
            raise AwsInfrastructureError(
                "Cost granularity must be DAILY or MONTHLY.", status_code=422
            )

        def fetch() -> dict[str, Any]:
            response = self._client("ce", region_name="us-east-1").get_cost_and_usage(
                TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
                Granularity=granularity,
                Metrics=["UnblendedCost"],
                GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            )
            buckets = []
            for period in response.get("ResultsByTime", []):
                groups = [
                    {
                        "service": group.get("Keys", ["Unknown"])[0],
                        "amount": float((group.get("Metrics", {}).get("UnblendedCost") or {}).get("Amount", 0)),
                        "unit": (group.get("Metrics", {}).get("UnblendedCost") or {}).get("Unit", "USD"),
                    }
                    for group in period.get("Groups", [])
                ]
                total = period.get("Total", {}).get("UnblendedCost", {})
                buckets.append(
                    {
                        "start": period.get("TimePeriod", {}).get("Start"),
                        "end": period.get("TimePeriod", {}).get("End"),
                        "amount": float(total.get("Amount", 0)),
                        "unit": total.get("Unit", "USD"),
                        "services": groups,
                    }
                )
            return {
                "cost_basis": "UnblendedCost",
                "granularity": granularity,
                "currency": "USD",
                "buckets": buckets,
                "disclaimer": (
                    "UnblendedCost is delayed and can differ from the final bill, including credits and taxes."
                ),
            }

        return self._call(fetch)

    @staticmethod
    def _docker_command(
        action: str,
        *,
        container_id: str | None = None,
        tail: int = 100,
        image: str | None = None,
        container_name: str | None = None,
        container_port: int | None = None,
        host_port: int | None = None,
    ) -> str:
        if not isinstance(action, str) or action not in _ALLOWED_DOCKER_ACTIONS:
            raise AwsInfrastructureError("Unsupported remote Docker action.", status_code=422)
        if action == "list":
            return (
                "docker ps -a --no-trunc --format "
                "'{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}'"
            )
        if action in {"logs", "start", "stop", "restart", "remove"}:
            if not isinstance(container_id, str) or not _CONTAINER_ID.fullmatch(container_id):
                raise AwsInfrastructureError("Invalid Docker container ID.", status_code=422)
            if action == "logs":
                if type(tail) is not int or not 1 <= tail <= 1000:
                    raise AwsInfrastructureError("Log tail must be between 1 and 1000.", status_code=422)
                return f"docker logs --tail {tail} {container_id} 2>&1"
            if action == "start":
                return f"docker start {container_id}"
            if action == "stop":
                return f"docker stop --time 10 {container_id}"
            if action == "restart":
                return f"docker restart --time 10 {container_id}"
            return f"docker rm -f {container_id}"
        if (
            not isinstance(image, str)
            or not _ECR_IMAGE.fullmatch(image)
            or not isinstance(container_name, str)
            or not _CONTAINER_NAME.fullmatch(container_name)
            or type(container_port) is not int
            or not 1 <= container_port <= 65535
            or type(host_port) is not int
            or not 1 <= host_port <= 65535
        ):
            raise AwsInfrastructureError(
                "Provide a valid ECR image URI, container name, and port mapping.",
                status_code=422,
            )
        match = _ECR_IMAGE.fullmatch(image)
        if match is None:
            raise AwsInfrastructureError("ECR image reference is invalid.", status_code=422)
        registry = f"{match.group('account')}.dkr.ecr.{match.group('region')}.amazonaws.com"
        return (
            f"aws ecr get-login-password --region {match.group('region')} | "
            f"docker login --username AWS --password-stdin {registry} && "
            f"docker pull {image} && "
            f"docker run -d --restart unless-stopped --memory=768m --pids-limit=128 "
            f"--cap-drop=ALL --security-opt=no-new-privileges "
            f"-p {host_port}:{container_port} --name {container_name} {image}"
        )

    def send_docker_command(
        self,
        username: str,
        instance_id: str,
        action: str,
        *,
        container_id: str | None = None,
        confirmation: str | None = None,
        tail: int = 100,
        image: str | None = None,
        container_name: str | None = None,
        container_port: int | None = None,
        host_port: int | None = None,
        confirmed: bool = False,
        public_access_confirmed: bool = False,
    ) -> dict[str, Any]:
        identity = self._validate_instance_id(instance_id)
        if not isinstance(confirmed, bool) or not isinstance(public_access_confirmed, bool):
            raise AwsInfrastructureError("Confirmation flags must be boolean.", status_code=422)
        command = self._docker_command(
            action,
            container_id=container_id,
            tail=tail,
            image=image,
            container_name=container_name,
            container_port=container_port,
            host_port=host_port,
        )
        if action == "remove" and confirmation != f"remove {container_id}":
            raise AwsInfrastructureError(
                f"Container removal is permanent. Confirm by sending exactly: remove {container_id}",
                status_code=422,
            )
        if action == "deploy" and not confirmed:
            raise AwsInfrastructureError(
                "Deploying a container to EC2 requires explicit confirmation.",
                status_code=422,
            )
        if action == "deploy" and not public_access_confirmed:
            raise AwsInfrastructureError(
                "Confirm that the mapped container port may be reachable through the instance security group.",
                status_code=422,
            )
        def execute() -> dict[str, Any]:
            instance = self._describe_instance(identity)
            if (instance.get("State") or {}).get("Name") != "running":
                raise AwsInfrastructureError(
                    "SSM Docker management requires the EC2 instance to be running.",
                    status_code=409,
                )
            ssm = self._client("ssm")
            information = self._call(
                lambda: ssm.describe_instance_information(
                    Filters=[{"Key": "InstanceIds", "Values": [identity]}]
                )
            ).get("InstanceInformationList", [])
            if not information or information[0].get("PingStatus") != "Online":
                raise AwsInfrastructureError(
                    "The instance is not connected to Systems Manager. Install/register the SSM Agent, "
                    "attach an SSM instance role, and verify network access.",
                    status_code=409,
                )
            response = self._call(
                lambda: ssm.send_command(
                    InstanceIds=[identity],
                    DocumentName="AWS-RunShellScript",
                    Parameters={"commands": [command]},
                    TimeoutSeconds=600,
                    Comment=f"Aidevops allowlisted Docker action: {action}",
                    MaxConcurrency="1",
                    MaxErrors="0",
                )
            )
            command_id = response.get("Command", {}).get("CommandId")
            if not command_id or not _COMMAND_ID.fullmatch(command_id):
                raise AwsInfrastructureError("SSM did not return a valid command ID.")
            return {
                "instance_id": identity,
                "action": action,
                "command_id": command_id,
                "status": "Pending",
                "operation_state": "ACCEPTED",
                "message": "SSM accepted the allowlisted command. Poll its status to verify completion.",
            }

        return self._audited(
            username,
            f"ssm_docker_{action}",
            identity,
            lambda: self._call(execute),
        )

    def get_ssm_command(
        self, username: str, instance_id: str, command_id: str
    ) -> dict[str, Any]:
        identity = self._validate_instance_id(instance_id)
        if not isinstance(command_id, str) or not _COMMAND_ID.fullmatch(command_id):
            raise AwsInfrastructureError("Invalid SSM command ID.", status_code=422)
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            found = conn.execute(
                """
                SELECT 1 FROM aws_infrastructure_audit
                WHERE username = ? AND resource_id = ? AND command_id = ?
                    AND operation LIKE 'ssm_docker_%'
                LIMIT 1
                """,
                (username, identity, command_id),
            ).fetchone()
        if not found:
            raise AwsInfrastructureError(
                "The SSM command was not created by this Aidevops account.",
                status_code=404,
            )

        def fetch() -> dict[str, Any]:
            response = self._call(
                lambda: self._client("ssm").get_command_invocation(
                    CommandId=command_id,
                    InstanceId=identity,
                )
            )
            output = redact(response.get("StandardOutputContent", ""))[:100_000]
            error_output = redact(response.get("StandardErrorContent", ""))[:20_000]
            state = str(response.get("Status", "Unknown"))
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                conn.execute(
                    """
                    UPDATE aws_infrastructure_audit SET state = ?, error = ?
                    WHERE command_id = ? AND operation LIKE 'ssm_docker_%'
                    """,
                    (state, error_output or None, command_id),
                )
            return {
                "command_id": command_id,
                "instance_id": identity,
                "status": state,
                "response_code": response.get("ResponseCode"),
                "stdout": output,
                "stderr": error_output,
            }

        return self._call(fetch)

    def audit_events(self, limit: int = 100) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise AwsInfrastructureError("Audit limit must be between 1 and 500.", status_code=422)
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT username, operation, resource_id, command_id, state, error, duration_ms, created_at
                FROM aws_infrastructure_audit ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
