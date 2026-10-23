"""Opt-in Docker build/HTTP/assets/SPA tests; optional --source actual project path."""
from pathlib import Path
import argparse
import json
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
import httpx
from aidevops.api.main import create_app
from aidevops.config import Settings
from smoke_preview import wait


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="aidevops-web-smoke-") as temp:
        root = Path(temp)
        cases = []
        if args.source:
            cases.append(("actual-todo", args.source))
        else:
            for kind in ("static", "vite", "flask", "fastapi"):
                source = root / kind
                source.mkdir()
                (source / "index.html").write_text('<html><body><h1>Todo preview</h1><script type="module" src="/src.js"></script></body></html>')
                (source / "src.js").write_text("document.body.dataset.ready='yes';")
                if kind == "vite":
                    (source / "package.json").write_text(json.dumps({"name": "todo-vite-smoke", "version": "1.0.0", "scripts": {"build": "vite build"}, "devDependencies": {"vite": "^6.0.0"}}))
                elif kind == "flask":
                    (source / "requirements.txt").write_text("flask\n")
                    (source / "app.py").write_text("from flask import Flask\nweb=Flask(__name__)\n@web.route('/')\ndef home(): return '<html><body>Flask preview</body></html>'\n")
                elif kind == "fastapi":
                    (source / "requirements.txt").write_text("fastapi\n")
                    (source / "app.py").write_text("from fastapi import FastAPI\nfrom fastapi.responses import HTMLResponse\napi=FastAPI()\n@api.get('/', response_class=HTMLResponse)\ndef home(): return '<html><body>FastAPI preview</body></html>'\n")
                cases.append((kind, source))
        cfg = Settings(data_dir=root / "data", db_path=root / "jobs.db", generated_dir=root / "generated",
            local_only=True, exec_timeout_seconds=600)
        with TestClient(create_app(cfg)) as client:
            identities = []
            try:
                for name, source in cases:
                    job = client.post("/api/jobs", json={"source_path": str(source)}).json()
                    response = client.post(f"/api/jobs/{job['id']}/run")
                    assert response.json()["state"] == "AWAITING_APPROVAL", response.text
                    print(name, "detected", response.json()["profile"].get("web_build_tool"), flush=True)
                    response = client.post(f"/api/jobs/{job['id']}/previews")
                    assert response.status_code == 201, response.text
                    record = response.json()
                    identity = record["id"]
                    identities.append(identity)
                    response = client.post(f"/api/previews/{identity}/build", json={"approved": True, "digest": record["digest"]})
                    assert response.status_code == 202, response.text
                    record = wait(client, identity, {"BUILT"}, timeout=660)
                    assert record["suggested_port"] == (5000 if name == "flask" else 8000 if name == "fastapi" else 8080)
                    print(name, "image built", flush=True)
                    response = client.post(f"/api/previews/{identity}/start", json={"approved": True, "port": record["suggested_port"], "health_path": "/", "ttl_minutes": 5})
                    assert response.status_code == 202, response.text
                    record = wait(client, identity, {"READY"}, timeout=60)
                    with httpx.Client(base_url=record["url"], trust_env=False) as web:
                        page = web.get("/")
                        assert page.status_code == 200 and "<html" in page.text.lower()
                        if name not in {"flask", "fastapi"}:
                            assert web.get("/tasks/example").status_code == 200
                        assets = re.findall(r'(?:src|href)="([^"]+\.(?:js|css))"', page.text)
                        if name not in {"flask", "fastapi"}:
                            assert assets, page.text[:500]
                        for asset in assets:
                            response = web.get(asset)
                            assert response.status_code == 200, asset
                            assert "text/html" not in response.headers.get("content-type", ""), asset
                    print(name, "READY:", (f"HTML + {len(assets)} assets + SPA route" if name not in {"flask", "fastapi"} else "application HTTP page"), "verified", flush=True)
            finally:
                for identity in identities:
                    response = client.post(f"/api/previews/{identity}/stop")
                    if response.json().get("state") == "STOPPING":
                        wait(client, identity, {"STOPPED", "CANCELLED", "BUILD_FAILED", "START_FAILED"}, 30)
                    response = client.post(f"/api/previews/{identity}/cleanup")
                    assert response.status_code == 200, response.text
                print("All frontend smoke-owned resources removed", flush=True)


if __name__ == "__main__":
    main()
