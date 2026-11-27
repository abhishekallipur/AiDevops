from __future__ import annotations

import io
import json
import sqlite3
import sys
import threading
import tarfile
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import boto3
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, TokenRetrievalError

from aidevops.auth import SESSION_COOKIE
from aidevops.errors import ValidationError
from aidevops.models import ProjectType
from aidevops.services.aws_manager import AwsManagementError, AwsManagementService


PREVIEW_ID = "preview_0123456789abcdef"


class FakePreviews:
    def get(self, identity):
        assert identity == PREVIEW_ID
        return {
            "id": identity,
            "job_id": "job-1",
            "state": "BUILT",
            "image_id": "sha256:" + "a" * 64,
            "suggested_port": 8080,
        }


class FakeJobs:
    def __init__(self, project_type=ProjectType.STATIC, web_build_tool=None):
        self.profile = SimpleNamespace(
            project_type=project_type,
            web_build_tool=web_build_tool,
            suggested_port=8080,
        )

    def get(self, identity):
        assert identity == "job-1"
        return SimpleNamespace(profile=self.profile)


@pytest.fixture
def aws_service(settings):
    settings.ensure_dirs()
    return AwsManagementService(settings, FakePreviews(), FakeJobs())


def test_localstack_client_uses_only_dummy_credentials(monkeypatch, aws_service):
    calls = {}

    def fake_client(service, **options):
        calls.update(service=service, **options)
        return SimpleNamespace(get_caller_identity=lambda: {"Account": "000000000000"})

    monkeypatch.setattr(boto3, "client", fake_client)
    status = aws_service.status()

    assert status["available"] is True
    assert status["account_id"] == "000000000000"
    assert calls["endpoint_url"] == "http://localhost:4566"
    assert calls["aws_access_key_id"] == "test"
    assert calls["aws_secret_access_key"] == "test"


def test_real_aws_mode_does_not_pass_localstack_endpoint(monkeypatch, settings):
    settings = replace(settings, aws_mode="aws")
    service = AwsManagementService(settings, FakePreviews(), FakeJobs())
    calls = {}

    def fake_client(name, **options):
        calls.update(service=name, **options)
        return SimpleNamespace(get_caller_identity=lambda: {"Account": "123456789012"})

    monkeypatch.setattr(boto3, "client", fake_client)

    assert service.status()["account_id"] == "123456789012"
    assert "endpoint_url" not in calls
    assert "aws_access_key_id" not in calls


def test_status_reports_localstack_unavailable_without_falling_back(monkeypatch, aws_service):
    def fail(_service):
        raise EndpointConnectionError(endpoint_url="http://localhost:4566")

    monkeypatch.setattr(aws_service, "_client", fail)

    result = aws_service.status()

    assert result["available"] is False
    assert result["mode"] == "localstack"
    assert result["endpoint"] == "http://localhost:4566"
    assert "Start it" in result["message"]


def test_status_explains_how_to_refresh_expired_sso_session(settings, monkeypatch):
    settings = replace(settings, aws_mode="aws")
    service = AwsManagementService(settings, FakePreviews(), FakeJobs())

    def fail(_service):
        raise TokenRetrievalError(provider="sso", error_msg="expired")

    monkeypatch.setattr(service, "_client", fail)

    result = service.status()

    assert result["available"] is False
    assert result["mode"] == "aws"
    assert "aws sso login --profile <profile-name>" in result["message"]
    assert "backend host" in result["message"]


def test_status_never_returns_endpoint_userinfo(settings):
    settings = replace(
        settings,
        aws_endpoint_url="http://operator:do-not-expose@localhost:4566/path",
    )
    settings.ensure_dirs()
    service = AwsManagementService(settings, FakePreviews(), FakeJobs())

    result = service.status()

    assert result["endpoint"] == "http://localhost:4566"
    assert "operator" not in repr(result)
    assert "do-not-expose" not in repr(result)


def test_recommendation_selects_s3_for_static_and_ec2_for_server_apps(aws_service):
    static = aws_service.recommendation(PREVIEW_ID)
    assert static["target"] == "s3"
    assert "browser assets" in static["reason"]

    aws_service.jobs = FakeJobs(ProjectType.NODE, "next")
    server = aws_service.recommendation(PREVIEW_ID)
    assert server["target"] == "ec2"
    assert any("instance profile" in item for item in server["requirements"])
    assert any("AIDEVOPS_AWS_EC2_AMI_ID" in item for item in server["requirements"])

    aws_service.settings = replace(
        aws_service.settings,
        aws_ec2_ami_id="ami-12345678",
        aws_ec2_instance_profile_arn=(
            "arn:aws:iam::123456789012:instance-profile/aidevops-ecr-pull"
        ),
    )
    configured = aws_service.recommendation(PREVIEW_ID)
    assert configured["requirements"] == [
        "LocalStack EC2 deployments require ECR support in the active license."
    ]


def test_unapproved_or_unconfirmed_deployment_is_refused_before_cloud_calls(aws_service, monkeypatch):
    called = False

    def cloud_call(_service):
        nonlocal called
        called = True
        raise AssertionError("must not contact AWS")

    monkeypatch.setattr(aws_service, "_client", cloud_call)
    with pytest.raises(ValidationError, match="explicit approval"):
        aws_service.deploy(
            "admin", PREVIEW_ID, "s3", approved=False, public_access_confirmed=True
        )
    with pytest.raises(ValidationError, match="Public access"):
        aws_service.deploy(
            "admin", PREVIEW_ID, "s3", approved=True, public_access_confirmed=False
        )
    assert called is False


def test_static_archive_requires_root_index_and_rejects_traversal():
    def archive_with(name, contents):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w") as archive:
            data = contents.encode()
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
        return output.getvalue()

    files = AwsManagementService._unpack_static_archive(
        archive_with("html/index.html", "<h1>app</h1>")
    )
    assert files == [("index.html", b"<h1>app</h1>", "text/html")]

    with pytest.raises(ValidationError, match="unsafe archive entry"):
        AwsManagementService._unpack_static_archive(
            archive_with("html/../../outside.txt", "unsafe")
        )
    with pytest.raises(ValidationError, match="index.html"):
        AwsManagementService._unpack_static_archive(
            archive_with("html/assets/app.js", "code")
        )


def test_static_image_export_verifies_preview_label_and_uses_isolated_container(
    aws_service, monkeypatch
):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        content = b"<h1>site</h1>"
        item = tarfile.TarInfo("html/index.html")
        item.size = len(content)
        archive.addfile(item, io.BytesIO(content))

    calls = {}

    class FakeContainer:
        def get_archive(self, path):
            calls["archive_path"] = path
            return iter([output.getvalue()]), {}

        def remove(self, *, force):
            calls["removed"] = force

    class FakeEngine:
        images = SimpleNamespace(
            get=lambda _image_id: SimpleNamespace(
                attrs={"Config": {"Labels": {"io.aidevops.preview": PREVIEW_ID}}}
            )
        )
        containers = SimpleNamespace(
            create=lambda image, **kwargs: (
                calls.update(image=image, container_options=kwargs) or FakeContainer()
            )
        )

        def close(self):
            calls["closed"] = True

    engine = FakeEngine()
    monkeypatch.setitem(sys.modules, "docker", SimpleNamespace(from_env=lambda: engine))

    files = aws_service._static_files(FakePreviews().get(PREVIEW_ID))

    assert files == [("index.html", b"<h1>site</h1>", "text/html")]
    assert calls["archive_path"] == "/usr/share/nginx/html"
    assert calls["container_options"]["network_disabled"] is True
    assert calls["container_options"]["read_only"] is True
    assert calls["removed"] is True
    assert calls["closed"] is True


def test_static_deployment_records_resource_and_audit(settings):
    settings.ensure_dirs()
    service = AwsManagementService(settings, FakePreviews(), FakeJobs())
    service._static_files = lambda _preview: [("index.html", b"<h1>ok</h1>", "text/html")]

    class FakeS3:
        def __init__(self):
            self.created = []
            self.objects = []
            self.policy = None

        def create_bucket(self, **kwargs):
            self.created.append(kwargs)

        def put_public_access_block(self, **kwargs):
            self.public_block = kwargs

        def put_object(self, **kwargs):
            self.objects.append(kwargs)

        def put_bucket_website(self, **kwargs):
            self.website = kwargs

        def put_bucket_policy(self, **kwargs):
            self.policy = json.loads(kwargs["Policy"])

        def put_bucket_tagging(self, **_kwargs):
            pass

    s3 = FakeS3()
    service._client = lambda name: s3
    result = service.deploy(
        "admin",
        PREVIEW_ID,
        "s3",
        approved=True,
        public_access_confirmed=True,
    )

    assert result["state"] == "DEPLOYED"
    assert result["resource_id"].startswith("aidevops-aws-")
    assert ".s3-website.localhost.localstack.cloud" in result["url"]
    assert s3.objects[0]["Body"] == b"<h1>ok</h1>"
    assert s3.policy["Statement"][0]["Action"] == "s3:GetObject"
    assert len(service.list_deployments()) == 1
    with pytest.raises(ValidationError, match="already has"):
        service.deploy(
            "admin",
            PREVIEW_ID,
            "s3",
            approved=True,
            public_access_confirmed=True,
        )
    with sqlite3.connect(service.db_path) as conn:
        assert conn.execute("SELECT state FROM aws_audit ORDER BY id").fetchall() == [
            ("started",), ("succeeded",)
        ]


def test_static_site_uploads_run_concurrently_with_a_bounded_worker_count():
    barrier = threading.Barrier(8)
    lock = threading.Lock()

    class FakeS3:
        def __init__(self):
            self.active = 0
            self.max_active = 0
            self.keys = []

        def put_object(self, **kwargs):
            with lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            try:
                barrier.wait(timeout=3)
                self.keys.append(kwargs["Key"])
            finally:
                with lock:
                    self.active -= 1

    s3 = FakeS3()
    files = [(f"{index}.html", b"page", "text/html") for index in range(8)]

    AwsManagementService._upload_static_files(s3, "site-bucket", files)

    assert s3.max_active == 8
    assert sorted(s3.keys) == [f"{index}.html" for index in range(8)]


def test_aws_permission_denial_names_required_permissions(aws_service):
    error = ClientError(
        {"Error": {"Code": "UnauthorizedOperation", "Message": "redacted details"}},
        "RunInstances",
    )

    message = aws_service._deployment_failure_message(error, "ec2")

    assert "AWS denied RunInstances" in message
    assert "iam:PassRole" in message
    assert "redacted details" not in message
    assert aws_service._is_access_denied(error) is True


def test_cloudwatch_metric_uses_latest_available_datapoint(aws_service, monkeypatch):
    class FakeCloudWatch:
        def get_metric_statistics(self, **_kwargs):
            return {
                "Datapoints": [
                    {"Timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc), "Average": 10.0},
                    {"Timestamp": datetime(2026, 1, 2, tzinfo=timezone.utc), "Average": 42.5},
                ]
            }

    monkeypatch.setattr(aws_service, "_client", lambda name: FakeCloudWatch())
    assert aws_service._cpu_metric("i-123") == 42.5


def test_ec2_memory_metric_uses_cloudwatch_agent_data(aws_service, monkeypatch):
    class FakeCloudWatch:
        def get_metric_statistics(self, **kwargs):
            assert kwargs["Namespace"] == "CWAgent"
            assert kwargs["MetricName"] == "mem_used_percent"
            return {
                "Datapoints": [
                    {"Timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc), "Average": 65.75}
                ]
            }

    monkeypatch.setattr(aws_service, "_client", lambda _name: FakeCloudWatch())

    assert aws_service._memory_metric("i-123") == 65.75


def test_overview_stops_paginating_after_one_hundred_instances(aws_service, monkeypatch):
    instances = [
        {"InstanceId": f"i-{index}", "State": {"Name": "stopped"}}
        for index in range(100)
    ]
    calls = {"extra_page": False}

    class FakePaginator:
        def paginate(self):
            yield {"Reservations": [{"Instances": instances}]}
            calls["extra_page"] = True
            yield {"Reservations": [{"Instances": [{"InstanceId": "i-extra"}]}]}

    class FakeEc2:
        def get_paginator(self, _operation):
            return FakePaginator()

    class FakeS3:
        def list_buckets(self):
            return {"Buckets": []}

    clients = {"ec2": FakeEc2(), "s3": FakeS3()}
    monkeypatch.setattr(aws_service, "status", lambda: {"available": True})
    monkeypatch.setattr(aws_service, "_client", lambda name: clients[name])

    result = aws_service.overview()

    assert len(result["instances"]) == 100
    assert calls["extra_page"] is False


def test_ec2_deployment_requires_ami_and_instance_profile(aws_service, monkeypatch):
    aws_service.jobs = FakeJobs(ProjectType.PYTHON)
    contacted = False

    def cloud_call(_service):
        nonlocal contacted
        contacted = True
        raise AssertionError("configuration should be checked before cloud calls")

    monkeypatch.setattr(aws_service, "_client", cloud_call)
    with pytest.raises(ValidationError, match="AMI_ID"):
        aws_service.deploy(
            "admin",
            PREVIEW_ID,
            "ec2",
            approved=True,
            public_access_confirmed=True,
        )
    assert contacted is False


def test_ec2_deployment_uses_verified_image_and_public_http_confirmation(
    settings, monkeypatch
):
    settings = replace(
        settings,
        aws_ec2_ami_id="ami-12345678",
        aws_ec2_instance_profile_arn=(
            "arn:aws:iam::123456789012:instance-profile/aidevops-ecr-pull"
        ),
    )
    settings.ensure_dirs()
    service = AwsManagementService(settings, FakePreviews(), FakeJobs(ProjectType.PYTHON))
    calls = {}

    class FakeEcr:
        def create_repository(self, **kwargs):
            calls["repository"] = kwargs
            return {
                "repository": {
                    "repositoryUri": "123456789012.dkr.ecr.us-east-1.amazonaws.com/repo",
                    "registryId": "123456789012",
                }
            }

        def get_authorization_token(self, **_kwargs):
            import base64
            return {
                "authorizationData": [{
                    "authorizationToken": base64.b64encode(b"AWS:private-token").decode()
                }]
            }

        def delete_repository(self, **_kwargs):
            pass

    class FakeWaiter:
        def wait(self, **_kwargs):
            pass

    class FakeEc2:
        def describe_vpcs(self, **_kwargs):
            return {"Vpcs": [{"VpcId": "vpc-123"}]}

        def describe_subnets(self, **_kwargs):
            return {"Subnets": [{"SubnetId": "subnet-123"}]}

        def create_security_group(self, **kwargs):
            calls["security_group"] = kwargs
            return {"GroupId": "sg-123"}

        def authorize_security_group_ingress(self, **kwargs):
            calls["ingress"] = kwargs

        def run_instances(self, **kwargs):
            calls["instance"] = kwargs
            return {"Instances": [{"InstanceId": "i-123"}]}

        def get_waiter(self, name):
            assert name == "instance_running"
            return FakeWaiter()

        def describe_instances(self, **_kwargs):
            return {"Reservations": [{"Instances": [{"PublicIpAddress": "203.0.113.12"}]}]}

    ecr, ec2 = FakeEcr(), FakeEc2()
    monkeypatch.setattr(
        service,
        "_client",
        lambda name: {"ec2": ec2, "ecr": ecr}[name],
    )
    pushed = []
    monkeypatch.setattr(
        service,
        "_push_image",
        lambda preview, uri, username, password: pushed.append(
            (preview["image_id"], uri, username, password)
        ),
    )

    result = service.deploy(
        "admin",
        PREVIEW_ID,
        "ec2",
        approved=True,
        public_access_confirmed=True,
    )

    assert result["state"] == "DEPLOYED"
    assert result["resource_id"] == "i-123"
    assert result["url"] == "http://203.0.113.12"
    assert pushed == [("sha256:" + "a" * 64,
                       "123456789012.dkr.ecr.us-east-1.amazonaws.com/repo",
                       "AWS", "private-token")]
    assert calls["ingress"]["IpPermissions"][0]["IpRanges"][0]["CidrIp"] == "0.0.0.0/0"
    assert "docker run -d" in calls["instance"]["UserData"]
    assert "private-token" not in repr(result)


def test_localstack_ecr_license_failure_is_actionable_and_recorded(aws_service, monkeypatch):
    settings = replace(
        aws_service.settings,
        aws_ec2_ami_id="ami-12345678",
        aws_ec2_instance_profile_arn=(
            "arn:aws:iam::123456789012:instance-profile/aidevops-ecr-pull"
        ),
    )
    service = AwsManagementService(settings, FakePreviews(), FakeJobs(ProjectType.PYTHON))

    class FakeEc2:
        def describe_vpcs(self, **_kwargs):
            return {"Vpcs": [{"VpcId": "vpc-123"}]}

        def describe_subnets(self, **_kwargs):
            return {"Subnets": [{"SubnetId": "subnet-123"}]}

    class FakeEcr:
        def create_repository(self, **_kwargs):
            raise ClientError(
                {
                    "Error": {
                        "Code": "InternalFailure",
                        "Message": (
                            "Sorry, the ecr service is not included within your "
                            "LocalStack license."
                        ),
                    }
                },
                "CreateRepository",
            )

    ec2, ecr = FakeEc2(), FakeEcr()
    monkeypatch.setattr(service, "_client", lambda name: {"ec2": ec2, "ecr": ecr}[name])

    with pytest.raises(AwsManagementError, match="active LocalStack license does not include ECR"):
        service.deploy(
            "admin",
            PREVIEW_ID,
            "ec2",
            approved=True,
            public_access_confirmed=True,
        )

    deployment = service.list_deployments()[0]
    assert deployment["state"] == "FAILED"
    assert "license with ECR support" in deployment["error"]


def test_dashboard_limits_cloudwatch_requests_and_sanitizes_resources(aws_service, monkeypatch):
    class FakePaginator:
        def paginate(self):
            return [{
                "Reservations": [{
                    "Instances": [
                        {
                            "InstanceId": f"i-{index}",
                            "InstanceType": "t3.micro",
                            "State": {"Name": "running"},
                            "Tags": [{"Key": "Name", "Value": f"app-{index}"}],
                            "PrivateKey": "must-not-be-returned",
                        }
                        for index in range(12)
                    ]
                }]
            }]

    class FakeEc2:
        def get_paginator(self, _operation):
            return FakePaginator()

    class FakeS3:
        def list_buckets(self):
            return {"Buckets": [{"Name": "static-site", "CreationDate": datetime.now(timezone.utc)}]}

    metric_calls = []

    class FakeCloudWatch:
        def get_metric_statistics(self, **kwargs):
            metric_calls.append(kwargs)
            return {"Datapoints": []}

    monkeypatch.setattr(
        aws_service,
        "_client",
        lambda name: {
            "sts": SimpleNamespace(get_caller_identity=lambda: {"Account": "000000000000"}),
            "ec2": FakeEc2(),
            "s3": FakeS3(),
            "cloudwatch": FakeCloudWatch(),
        }[name],
    )
    result = aws_service.overview()

    assert len(result["instances"]) == 12
    assert len(metric_calls) == 10
    assert result["buckets"][0]["name"] == "static-site"
    assert "must-not-be-returned" not in repr(result)


def test_aws_routes_require_configured_admin(client, monkeypatch):
    assert client.get("/api/aws/status").status_code == 401
    assert client.app.state.auth_store.create_user("viewer", "a-strong-password")
    other_token, _ = client.app.state.auth_store.create_session("viewer")
    client.cookies.set(SESSION_COOKIE, other_token)
    forbidden = client.get("/api/aws/status")
    assert forbidden.status_code == 403
    assert "AWS management" in forbidden.json()["detail"]

    admin_login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert admin_login.status_code == 200
    unapproved = client.post(
        f"/api/aws/previews/{PREVIEW_ID}/deploy",
        json={"target": "s3", "approved": False, "public_access_confirmed": True},
    )
    assert unapproved.status_code == 400
    public_not_confirmed = client.post(
        f"/api/aws/previews/{PREVIEW_ID}/deploy",
        json={"target": "s3", "approved": True, "public_access_confirmed": False},
    )
    assert public_not_confirmed.status_code == 400
    monkeypatch.setattr(
        client.app.state.aws_service,
        "status",
        lambda: {
            "available": True, "mode": "localstack", "endpoint": "http://localhost:4566",
            "region": "us-east-1", "account_id": "000000000000", "message": "Connected",
        },
    )
    assert client.get("/api/aws/status").status_code == 200
