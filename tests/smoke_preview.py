"""Opt-in real Docker build/start/health/stop/cleanup regression. No external AI."""
from dataclasses import replace
from pathlib import Path
import json
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from aidevops.api.main import create_app
from aidevops.config import Settings


def wait(client, identity, expected, timeout=360):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = client.get(f"/api/previews/{identity}").json()
        if result["state"] in expected:
            return result
        if result["state"] in {"BUILD_FAILED", "START_FAILED", "CLEANUP_FAILED"}:
            raise AssertionError(json.dumps(result))
        time.sleep(0.3)
    raise AssertionError("Preview operation timed out")


def main():
    with tempfile.TemporaryDirectory(prefix="aidevops-preview-smoke-") as temp:
        root = Path(temp)
        cfg = Settings(data_dir=root / "data", db_path=root / "jobs.db",
            generated_dir=root / "generated", local_only=True, exec_timeout_seconds=300)
        resources = []
        with TestClient(create_app(cfg)) as client:
            try:
                for kind in ["python", "node", "build_failure", "startup_failure"]:
                    source = root / kind
                    source.mkdir()
                    if kind == "node":
                        (source / "package.json").write_text('{"name":"preview-smoke","version":"1.0.0"}')
                        (source / "index.js").write_text("require('node:http').createServer((req,res)=>{res.end('preview ok')}).listen(8000,'0.0.0.0');")
                    else:
                        (source / "requirements.txt").write_text("")
                        (source / "app.py").write_text("raise SystemExit(2)" if kind == "startup_failure" else
                            "from http.server import HTTPServer, SimpleHTTPRequestHandler\nHTTPServer(('0.0.0.0', 8000), SimpleHTTPRequestHandler).serve_forever()")
                    job = client.post("/api/jobs", json={"source_path": str(source)}).json()
                    job_id = job["id"]
                    result = client.post(f"/api/jobs/{job_id}/run").json()
                    assert result["state"] == "AWAITING_APPROVAL", result
                    if kind == "build_failure":
                        stored = client.app.state.store.get(job_id)
                        next(a for a in stored.artifacts if a.path == "Dockerfile").content = "FROM python:3.12-slim\nRUN false\n"
                        client.app.state.store.save(stored)
                    response = client.post(f"/api/jobs/{job_id}/previews")
                    assert response.status_code == 201, response.text
                    record = response.json()
                    identity = record["id"]
                    resources.append(identity)
                    assert client.post(f"/api/previews/{identity}/build", json={"digest": record["digest"], "approved": False}).status_code == 403
                    assert client.post(f"/api/previews/{identity}/build", json={"digest": record["digest"], "approved": True}).status_code == 202
                    record = wait(client, identity, {"BUILD_FAILED"} if kind == "build_failure" else {"BUILT"})
                    if kind == "build_failure":
                        print(kind, record["state"], flush=True)
                        continue
                    assert record["image_id"].startswith("sha256:")
                    result = client.post(f"/api/previews/{identity}/start", json={"approved": True, "port": 8000, "health_path": "/", "ttl_minutes": 1})
                    assert result.status_code == 202, result.text
                    record = wait(client, identity, {"START_FAILED"} if kind == "startup_failure" else {"READY"}, timeout=60)
                    if kind != "startup_failure":
                        import httpx
                        assert httpx.get(record["url"], trust_env=False).status_code == 200
                        assert record["url"].startswith("http://127.0.0.1:")
                        assert client.post(f"/api/previews/{identity}/stop").json()["state"] == "STOPPED"
                    print(kind, record["state"], "verified", flush=True)
            finally:
                for identity in resources:
                    result = client.post(f"/api/previews/{identity}/stop")
                    record = result.json()
                    if record.get("state") == "STOPPING":
                        wait(client, identity, {"CANCELLED", "STOPPED", "BUILD_FAILED", "START_FAILED"}, 30)
                    response = client.post(f"/api/previews/{identity}/cleanup")
                    assert response.status_code == 200, response.text
                    assert response.json()["state"] == "REMOVED"
                print("All smoke-owned containers, images and snapshots removed", flush=True)


if __name__ == "__main__":
    main()
