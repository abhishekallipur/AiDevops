from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from aidevops.services.aws_infrastructure import (
    AwsInfrastructureError,
    AwsInfrastructureService,
)


INSTANCE_ID = "i-1234567890abcdef0"


class FakePaginator:
    def __init__(self, instances):
        self.instances = instances

    def paginate(self, **_kwargs):
        yield {
            "Reservations": [
                {"Instances": self.instances},
            ]
        }


class FakeEc2:
    def __init__(self, state="running"):
        self.state = state
        self.actions = []
        self.launch_request = None
        self.instances = [
            {
                "InstanceId": INSTANCE_ID,
                "State": {"Name": state, "Code": 16},
                "InstanceType": "t3.micro",
                "ImageId": "ami-1234567890abcdef0",
                "LaunchTime": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "PublicIpAddress": "203.0.113.10",
                "PrivateIpAddress": "10.0.0.10",
                "Tags": [{"Key": "Name", "Value": "demo"}],
                "SecurityGroups": [{"GroupId": "sg-1234567890abcdef0", "GroupName": "web"}],
                "IamInstanceProfile": {"Arn": "arn:aws:iam::123456789012:instance-profile/demo"},
                "UserData": "must not be returned",
            }
        ]

    def get_paginator(self, _operation):
        return FakePaginator(self.instances)

    def describe_instances(self, **_kwargs):
        return {"Reservations": [{"Instances": self.instances}]}

    def describe_instance_status(self, **_kwargs):
        return {"InstanceStatuses": []}

    def run_instances(self, **kwargs):
        self.launch_request = kwargs
        self.instances = [
            {
                "InstanceId": INSTANCE_ID,
                "State": {"Name": "pending", "Code": 0},
                "InstanceType": kwargs["InstanceType"],
                "ImageId": kwargs["ImageId"],
                "Tags": kwargs["TagSpecifications"][0]["Tags"],
                "LaunchTime": datetime(2026, 1, 1, tzinfo=timezone.utc),
            }
        ]
        return {"Instances": self.instances}

    def start_instances(self, **kwargs):
        self.actions.append(("start", kwargs))
        return {"StartingInstances": [{"CurrentState": {"Name": "pending"}}]}

    def stop_instances(self, **kwargs):
        self.actions.append(("stop", kwargs))
        return {"StoppingInstances": [{"CurrentState": {"Name": "stopping"}}]}

    def reboot_instances(self, **kwargs):
        self.actions.append(("reboot", kwargs))
        return {}

    def terminate_instances(self, **kwargs):
        self.actions.append(("terminate", kwargs))
        return {"TerminatingInstances": [{"CurrentState": {"Name": "shutting-down"}}]}


class FakeCloudWatch:
    def get_metric_statistics(self, **kwargs):
        statistic = kwargs["Statistics"][0]
        value = 42.5 if kwargs["MetricName"] == "CPUUtilization" else 1024
        return {
            "Datapoints": [
                {"Timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc), statistic: value}
            ]
        }


class FakeSsm:
    def __init__(self):
        self.sent = []

    def describe_instance_information(self, **_kwargs):
        return {"InstanceInformationList": [{"PingStatus": "Online"}]}

    def send_command(self, **kwargs):
        self.sent.append(kwargs)
        return {"Command": {"CommandId": "12345678-1234-1234-1234-123456789abc"}}

    def get_command_invocation(self, **_kwargs):
        return {
            "Status": "Success",
            "ResponseCode": 0,
            "StandardOutputContent": "web container running",
            "StandardErrorContent": "",
        }


def _service(settings, tmp_path, clients):
    return AwsInfrastructureService(
        settings,
        lambda service, **_kwargs: clients[service],
        tmp_path / "aws-infrastructure.db",
    )


def test_list_instances_excludes_userdata_and_secrets(settings, tmp_path):
    ec2 = FakeEc2()
    service = _service(settings, tmp_path, {"ec2": ec2})

    result = service.list_instances()

    assert result["truncated"] is False
    assert result["instances"][0]["name"] == "demo"
    assert result["instances"][0]["public_ip"] == "203.0.113.10"
    assert "UserData" not in result["instances"][0]
    assert "must not be returned" not in str(result)


def test_get_instance_validates_id_before_aws_call(settings, tmp_path):
    ec2 = FakeEc2()
    service = _service(settings, tmp_path, {"ec2": ec2})

    with pytest.raises(AwsInfrastructureError) as error:
        service.get_instance("i-$(whoami)")

    assert error.value.status_code == 422
    assert ec2.actions == []


@pytest.mark.parametrize(
    ("action", "state", "confirmation"),
    [
        ("start", "stopped", None),
        ("stop", "running", None),
        ("reboot", "running", None),
        ("terminate", "stopped", f"terminate {INSTANCE_ID}"),
    ],
)
def test_ec2_management_actions_are_audited(
    settings, tmp_path, action, state, confirmation
):
    ec2 = FakeEc2(state)
    service = _service(settings, tmp_path, {"ec2": ec2})

    result = service.manage_instance(
        "admin", INSTANCE_ID, action, confirmation=confirmation
    )

    assert result["operation_state"] == "ACCEPTED"
    assert ec2.actions[0][0] == action
    assert service.audit_events()[0]["operation"] == f"ec2_{action}"


def test_terminate_requires_exact_confirmation(settings, tmp_path):
    ec2 = FakeEc2("stopped")
    service = _service(settings, tmp_path, {"ec2": ec2})

    with pytest.raises(AwsInfrastructureError) as error:
        service.manage_instance("admin", INSTANCE_ID, "terminate", confirmation="yes")

    assert error.value.status_code == 422
    assert ec2.actions == []


def test_create_instance_requires_confirmations_and_bootstraps_docker_safely(
    settings, tmp_path
):
    ec2 = FakeEc2("pending")
    service = _service(settings, tmp_path, {"ec2": ec2})
    values = {
        "ami_id": "ami-1234567890abcdef0",
        "instance_type": "t3.micro",
        "subnet_id": "subnet-1234567890abcdef0",
        "security_group_ids": ["sg-1234567890abcdef0"],
        "name": "aidevops-test",
        "bootstrap_docker": True,
    }

    with pytest.raises(AwsInfrastructureError):
        service.create_instance("admin", **values)
    assert ec2.launch_request is None

    result = service.create_instance(
        "admin",
        **values,
        confirmed=True,
        public_access_confirmed=True,
    )
    assert result["instance_id"] == INSTANCE_ID
    assert "dnf install -y docker" in ec2.launch_request["UserData"]
    assert "awscli" not in ec2.launch_request["UserData"]
    assert "UserData" not in result
    assert service.audit_events()[0]["operation"] == "create_instance"


def test_metrics_report_unavailable_memory_as_none(settings, tmp_path):
    ec2 = FakeEc2()
    service = _service(
        settings,
        tmp_path,
        {"ec2": ec2, "cloudwatch": FakeCloudWatch()},
    )
    cloudwatch = service.client_factory("cloudwatch")
    cloudwatch.get_metric_statistics = lambda **_kwargs: {"Datapoints": []}

    metrics = service.get_instance_metrics(INSTANCE_ID)

    assert metrics["cpu_percent"] is None
    assert metrics["memory_percent"] is None
    assert metrics["period_minutes"] == 60


def test_unsupported_cloudwatch_metric_does_not_hide_other_metrics(settings, tmp_path):
    class PartialCloudWatch:
        def get_metric_statistics(self, **kwargs):
            if kwargs["MetricName"] == "EBSReadBytes":
                raise ClientError(
                    {
                        "Error": {
                            "Code": "InvalidParameterValue",
                            "Message": "unsupported metric",
                        }
                    },
                    "GetMetricStatistics",
                )
            statistic = kwargs["Statistics"][0]
            return {
                "Datapoints": [
                    {
                        "Timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc),
                        statistic: 12.5,
                    }
                ]
            }

    service = _service(
        settings,
        tmp_path,
        {"ec2": FakeEc2(), "cloudwatch": PartialCloudWatch()},
    )

    metrics = service.get_instance_metrics(INSTANCE_ID)

    assert metrics["cpu_percent"] == 12.5
    assert metrics["ebs_read_bytes"] is None


def test_cost_report_uses_cost_explorer_region_and_rejects_bad_range(
    settings, tmp_path
):
    calls = []

    class FakeCostExplorer:
        def get_cost_and_usage(self, **kwargs):
            calls.append(kwargs)
            return {"ResultsByTime": []}

    service = AwsInfrastructureService(
        settings,
        lambda service, **kwargs: (
            calls.append({"service": service, **kwargs}) or FakeCostExplorer()
        ),
        tmp_path / "aws-infrastructure.db",
    )
    # Provide a fixed recent date range that is valid independently of current usage.
    end = date.today()

    with pytest.raises(AwsInfrastructureError):
        service.get_cost_report(end, end)

    report = service.get_cost_report(date(2025, 1, 1), date(2025, 1, 2))
    assert report["cost_basis"] == "UnblendedCost"
    assert calls[0]["region_name"] == "us-east-1"
    assert calls[1]["TimePeriod"] == {"Start": "2025-01-01", "End": "2025-01-02"}


def test_ssm_docker_commands_are_allowlisted_and_audited(settings, tmp_path):
    ec2 = FakeEc2()
    ssm = FakeSsm()
    service = _service(settings, tmp_path, {"ec2": ec2, "ssm": ssm})

    result = service.send_docker_command("admin", INSTANCE_ID, "list")

    assert result["command_id"] == "12345678-1234-1234-1234-123456789abc"
    assert ssm.sent[0]["Parameters"]["commands"] == [
        "docker ps -a --no-trunc --format '{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}'"
    ]
    assert service.audit_events()[0]["command_id"] == result["command_id"]
    status = service.get_ssm_command("admin", INSTANCE_ID, result["command_id"])
    assert status["status"] == "Success"
    assert status["stdout"] == "web container running"


def test_ssm_poll_only_returns_commands_created_by_aidevops(settings, tmp_path):
    ssm = FakeSsm()
    service = _service(settings, tmp_path, {"ssm": ssm})

    with pytest.raises(AwsInfrastructureError) as error:
        service.get_ssm_command(
            "admin", INSTANCE_ID, "12345678-1234-1234-1234-123456789abc"
        )

    assert error.value.status_code == 404
    assert ssm.sent == []


def test_ssm_remove_requires_exact_confirmation_and_blocks_shell_input(
    settings, tmp_path
):
    service = _service(settings, tmp_path, {})

    with pytest.raises(AwsInfrastructureError):
        service.send_docker_command(
            "admin", INSTANCE_ID, "remove", container_id="a" * 12
        )
    with pytest.raises(AwsInfrastructureError):
        service.send_docker_command(
            "admin",
            INSTANCE_ID,
            "start",
            container_id="a" * 12 + "; whoami",
        )
    assert service._docker_command("logs", container_id="a" * 12, tail=25) == (
        f"docker logs --tail 25 {'a' * 12} 2>&1"
    )


def test_aws_infrastructure_routes_require_admin(client):
    response = client.get("/api/aws/infra/instances")

    assert response.status_code == 401


def test_aws_infrastructure_routes_reject_non_admin_users(client):
    signup = client.post(
        "/api/auth/register",
        json={"username": "regular-user", "password": "valid-password-123"},
    )
    assert signup.status_code == 201
    login = client.post(
        "/api/auth/login",
        json={"username": "regular-user", "password": "valid-password-123"},
    )
    assert login.status_code == 200

    response = client.get("/api/aws/infra/instances")

    assert response.status_code == 403
    assert "restricted to the configured administrator" in response.json()["detail"]


def test_aws_unavailable_is_reported_as_service_unavailable(settings, tmp_path):
    def unavailable(*_args, **_kwargs):
        raise EndpointConnectionError(endpoint_url="https://ec2.example.invalid")

    service = AwsInfrastructureService(
        settings, unavailable, tmp_path / "aws-infrastructure.db"
    )

    with pytest.raises(AwsInfrastructureError) as error:
        service.list_instances()

    assert error.value.status_code == 503
    assert "could not reach" in error.value.message.casefold()


def _login_as_admin(client):
    settings = client.app.state.settings
    response = client.post(
        "/api/auth/login",
        json={"username": settings.admin_username, "password": settings.admin_password},
    )
    assert response.status_code == 200


def test_assistant_requires_admin_and_confirms_termination(client, monkeypatch):
    from types import SimpleNamespace

    calls = []
    service = SimpleNamespace(
        manage_instance=lambda *args, **kwargs: (
            calls.append((args, kwargs))
            or {"state": "shutting-down", "operation_state": "ACCEPTED"}
        )
    )
    monkeypatch.setattr(client.app.state, "aws_infrastructure_service", service)
    command = f"aws terminate {INSTANCE_ID}"
    body = {"messages": [{"role": "user", "content": command}]}

    unauthorized = client.post("/api/assistant/chat", json=body)
    assert unauthorized.status_code == 401

    _login_as_admin(client)
    prompt = client.post("/api/assistant/chat", json=body)
    assert prompt.status_code == 200
    assert f"aws confirm terminate {INSTANCE_ID}" in prompt.json()["reply"]
    assert calls == []

    confirmed = client.post(
        "/api/assistant/chat",
        json={"messages": [{"role": "user", "content": f"aws confirm terminate {INSTANCE_ID}"}]},
    )
    assert confirmed.status_code == 200
    assert calls[0][0][2] == "terminate"
    assert calls[0][1]["confirmation"] == f"terminate {INSTANCE_ID}"


def test_assistant_docker_remove_requires_explicit_confirmation(client, monkeypatch):
    from types import SimpleNamespace

    container_id = "a" * 12
    calls = []
    service = SimpleNamespace(
        send_docker_command=lambda *args, **kwargs: (
            calls.append((args, kwargs))
            or {"command_id": "12345678-1234-1234-1234-123456789abc"}
        )
    )
    monkeypatch.setattr(client.app.state, "aws_infrastructure_service", service)
    _login_as_admin(client)

    request = client.post(
        "/api/assistant/chat",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": f"aws docker remove {INSTANCE_ID} {container_id}",
                }
            ]
        },
    )
    assert request.status_code == 200
    assert "aws docker confirm remove" in request.json()["reply"]
    assert calls == []

    confirmed = client.post(
        "/api/assistant/chat",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"aws docker confirm remove {INSTANCE_ID} {container_id}"
                    ),
                }
            ]
        },
    )
    assert confirmed.status_code == 200
    assert calls[0][0][2] == "remove"
    assert calls[0][1]["confirmation"] == f"remove {container_id}"


def test_assistant_docker_deploy_requires_public_access_confirmation(client, monkeypatch):
    from types import SimpleNamespace

    calls = []
    service = SimpleNamespace(
        send_docker_command=lambda *args, **kwargs: (
            calls.append((args, kwargs))
            or {"command_id": "12345678-1234-1234-1234-123456789abc"}
        )
    )
    monkeypatch.setattr(client.app.state, "aws_infrastructure_service", service)
    _login_as_admin(client)
    command = (
        f"aws docker deploy {INSTANCE_ID} "
        "123456789012.dkr.ecr.us-east-1.amazonaws.com/web:latest web 8080 80"
    )

    prompt = client.post(
        "/api/assistant/chat",
        json={"messages": [{"role": "user", "content": command}]},
    )
    assert prompt.status_code == 200
    assert "aws docker confirm deploy" in prompt.json()["reply"]
    assert calls == []

    confirmed = client.post(
        "/api/assistant/chat",
        json={
            "messages": [
                {"role": "user", "content": command.replace("aws docker", "aws docker confirm")}
            ]
        },
    )
    assert confirmed.status_code == 200
    assert calls[0][0][2] == "deploy"
    assert calls[0][1]["public_access_confirmed"] is True
