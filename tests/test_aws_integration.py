"""Opt-in, read-only LocalStack connectivity test."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path

import pytest

from aidevops.config import load_settings
from aidevops.services.aws_manager import AwsManagementService

pytestmark = pytest.mark.skipif(
    os.getenv("AIDEVOPS_AWS_INTEGRATION") != "1",
    reason="set AIDEVOPS_AWS_INTEGRATION=1 to contact LocalStack",
)


def test_localstack_sts_connection_is_read_only(tmp_path: Path):
    endpoint = os.getenv("AIDEVOPS_AWS_ENDPOINT_URL", "http://localhost:4566")
    settings = replace(
        load_settings(load_dotenv_file=False),
        data_dir=tmp_path / "data",
        generated_dir=tmp_path / "data" / "generated",
        db_path=tmp_path / "data" / "aidevops.db",
        aws_mode="localstack",
        aws_endpoint_url=endpoint,
    )
    settings.ensure_dirs()
    service = AwsManagementService(settings, previews=None, jobs=None)

    status = service.status()

    assert status["available"] is True, status["message"]
    assert status["mode"] == "localstack"
    assert status["account_id"] is not None
