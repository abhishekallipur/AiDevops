r"""Opt-in real HTTP/Streamlit/Docker smoke; uses disposable data and no LLM key.

Run from the repository root: .venv\Scripts\python.exe tests/smoke_local.py
"""
from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_url(url, process):
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError("server exited before readiness")
        try:
            response = httpx.get(url, timeout=10)
            if response.status_code == 200:
                return response
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError("server readiness timed out")


def main():
    with tempfile.TemporaryDirectory(prefix="aidevops-smoke-") as temp:
        data = Path(temp)
        api_port, ui_port = port(), port()
        env = {**os.environ, "OPENAI_API_KEY": "", "AIDEVOPS_DATA_DIR": str(data),
               "AIDEVOPS_DB_PATH": str(data / "jobs.db"),
               "AIDEVOPS_GENERATED_DIR": str(data / "generated"),
               "AIDEVOPS_EXEC_BACKEND": "auto", "AIDEVOPS_ALLOW_LOCAL_PATHS": "true",
               "AIDEVOPS_API_URL": f"http://127.0.0.1:{api_port}"}
        processes = []
        try:
            api = subprocess.Popen([sys.executable, "-m", "uvicorn", "aidevops.api.main:app",
                                    "--host", "127.0.0.1", "--port", str(api_port)],
                                   cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(api)
            health = wait_url(f"{env['AIDEVOPS_API_URL']}/health", api).json()
            assert health["llm_mode"] == "mock"
            print("HTTP health: PASS; docker_available:", health["docker_available"], flush=True)
            node = data / "node"
            node.mkdir()
            (node / "package.json").write_text(json.dumps({"name": "smoke", "version": "1.0.0",
                "scripts": {"test": "node --test"}}))
            (node / "test_smoke.test.js").write_text(
                "const test = require('node:test'); const assert = require('node:assert'); "
                "test('arithmetic', () => assert.equal(2 + 2, 4));")
            with httpx.Client(base_url=env["AIDEVOPS_API_URL"], timeout=180) as client:
                for name, source in [("python", ROOT / "examples/sample_python_app"), ("node", node)]:
                    created = client.post("/api/jobs", json={"source_path": str(source)})
                    assert created.status_code == 201, created.text
                    job_id = created.json()["id"]
                    result = client.post(f"/api/jobs/{job_id}/run").json()
                    assert result["state"] == "AWAITING_APPROVAL", result.get("error")
                    assert client.post(f"/api/jobs/{job_id}/execute", json={"approved": False}).status_code == 400
                    result = client.post(f"/api/jobs/{job_id}/execute", json={"approved": True}).json()
                    records = [(e["tool"], e["status"]) for e in result["executions"]]
                    print(name, result["state"], records, flush=True)
                    if health["docker_available"]:
                        assert result["state"] == "SUCCEEDED", result.get("error")
                    else:
                        assert result["state"] == "FAILED"
            ui = subprocess.Popen([sys.executable, "-m", "streamlit", "run",
                "aidevops/ui/streamlit_app.py", "--server.address", "127.0.0.1",
                "--server.port", str(ui_port), "--server.headless", "true"],
                cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(ui)
            assert wait_url(f"http://127.0.0.1:{ui_port}/_stcore/health", ui).text == "ok"
            assert httpx.get(f"http://127.0.0.1:{ui_port}").status_code == 200
            print("Streamlit health + HTML: PASS (not a browser interaction test)", flush=True)
        finally:
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


if __name__ == "__main__":
    main()
