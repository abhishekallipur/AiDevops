"""Shared test fixtures.

All fixtures build temporary repositories under ``tmp_path`` and a throwaway
:class:`Settings`/database, so tests never touch the developer's real project,
database, or AWS account. Container execution is disabled so tests are
deterministic regardless of whether Docker is running.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from aidevops.config import Settings
from aidevops.db import JobStore


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    return path


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    return Settings(
        data_dir=data,
        generated_dir=data / "generated",
        db_path=data / "aidevops.db",
        exec_backend="disabled",
        allow_local_paths=True,
        llm_max_retries=0,
    )


@pytest.fixture
def store(settings: Settings) -> JobStore:
    return JobStore(settings.db_path)


@pytest.fixture
def python_repo(tmp_path: Path) -> Path:
    root = tmp_path / "pyproject-repo"
    write(root / "requirements.txt", "fastapi\nuvicorn\n")
    write(
        root / "app.py",
        """
        from fastapi import FastAPI

        app = FastAPI()


        if __name__ == "__main__":
            import uvicorn
            uvicorn.run(app, port=8000)
        """,
    )
    write(root / "tests" / "test_app.py", "def test_ok():\n    assert True\n")
    write(root / "README.md", "# sample app\n")
    return root


@pytest.fixture
def node_repo(tmp_path: Path) -> Path:
    root = tmp_path / "node-repo"
    write(
        root / "package.json",
        """
        {
          "name": "sample-node",
          "version": "1.0.0",
          "main": "index.js",
          "dependencies": {"express": "^4.19.2"},
          "scripts": {"test": "node --test"}
        }
        """,
    )
    write(root / "index.js", 'const express = require("express");\napp.listen(3000);\n')
    return root


@pytest.fixture
def unknown_repo(tmp_path: Path) -> Path:
    root = tmp_path / "unknown-repo"
    write(root / "notes.txt", "just some prose, no manifest here\n")
    return root


@pytest.fixture
def python_profile(python_repo: Path, settings: Settings):
    from aidevops.analyzer import analyze_path

    return analyze_path(python_repo, settings)


@pytest.fixture
def client(settings: Settings):
    from fastapi.testclient import TestClient

    from aidevops.api.main import create_app

    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
