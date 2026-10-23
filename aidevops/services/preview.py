"""Single-process local preview worker. Durable records; no automatic side-effect replay."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import time
import uuid

import httpx

from ..analyzer.analyzer import _collect_files
from ..errors import InvalidTransitionError, NotFoundError, PolicyError, ValidationError
from ..execution.runner import _subprocess
from ..privacy import redact
from ..generator.validators import scan_secrets

ACTIVE = {"BUILDING", "STARTING"}
LABEL = "io.aidevops.preview"


def safe_log(text, secrets=()):
    try:
        return redact(text, secrets)
    except PolicyError:
        return "Output withheld by the privacy filter"


class PreviewService:
    def __init__(self, settings, jobs):
        self.settings, self.jobs = settings, jobs
        self.root = settings.data_dir / "previews"
        self.root.mkdir(parents=True, exist_ok=True)
        self.worker_lock = (self.root / "worker.lock").open("a+b")
        try:
            import os
            self.worker_lock.seek(0, 2)
            if self.worker_lock.tell() == 0:
                self.worker_lock.write(b"0")
                self.worker_lock.flush()
            self.worker_lock.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.worker_lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.worker_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.worker_lock.close()
            raise PolicyError("Only one backend process may use a preview data directory") from exc
        self.db = settings.data_dir / "previews.db"
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="preview")
        self.events = {}
        self.halt = threading.Event()
        with self.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS previews(id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        self.reconcile()
        self.monitor = threading.Thread(target=self.watch, daemon=True)
        self.monitor.start()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db, timeout=30)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def get(self, identity):
        with self.connect() as conn:
            row = conn.execute("SELECT data FROM previews WHERE id=?", (identity,)).fetchone()
        if not row:
            raise NotFoundError("Preview not found")
        return json.loads(row[0])

    def all(self):
        with self.connect() as conn:
            return [json.loads(r[0]) for r in conn.execute("SELECT data FROM previews ORDER BY rowid DESC")]

    def save(self, record):
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO previews VALUES (?,?)", (record["id"], json.dumps(record)))
        return record

    def update(self, identity, **fields):
        with self.lock:
            record = self.get(identity)
            record.update(fields)
            return self.save(record)

    def command(self, argv, timeout=30, cancel=None, on_output=None):
        return _subprocess(argv, cwd=self.root, timeout=timeout,
                           max_output=self.settings.exec_max_output_bytes, cancel=cancel, on_output=on_output)

    def inspect(self, resource, image=False):
        code, output, _, reason = self.command(
            ["docker", "image" if image else "container", "inspect", resource], timeout=10)
        if code != 0 or reason:
            return None
        try:
            return json.loads(output)[0]
        except (ValueError, IndexError):
            return None

    def owned(self, record, image=False):
        resource = (record.get("image_id") or record.get("image_tag")) if image else record["container_name"]
        if not resource:
            return None
        info = self.inspect(resource, image)
        if info and info.get("Config", {}).get("Labels", {}).get(LABEL) == record["id"]:
            return info
        return None

    @staticmethod
    def digest(folder):
        digest = hashlib.sha256()
        for path in sorted(folder.rglob("*")):
            if path.is_symlink():
                raise PolicyError("Snapshot contains a link")
            if path.is_file():
                digest.update(path.relative_to(folder).as_posix().encode() + b"\0")
                digest.update(path.read_bytes())
        return digest.hexdigest()

    def snapshot(self, job_id):
        with self.lock:
            return self._snapshot(job_id)

    def _snapshot(self, job_id):
        if sum(r["state"] != "REMOVED" for r in self.all()) >= 20:
            raise ValidationError("Remove unused preview resources before preparing more snapshots (limit 20)")
        job = self.jobs.get(job_id)
        if not job.profile or not job.plan or not job.artifacts or any(not r.passed for r in job.validation):
            raise ValidationError("Prepare and validate the project before building a preview")
        if self.settings.exec_backend == "disabled":
            raise PolicyError("Container execution is disabled")
        identity = "preview_" + uuid.uuid4().hex[:16]
        folder = self.root / identity / "context"
        folder.mkdir(parents=True)
        source = Path(job.source_path).resolve()
        try:
            files, warnings, truncated = _collect_files(source, self.settings)
            if truncated or any(w.startswith("cannot read directory") for w in warnings):
                raise ValidationError("Source exceeds limits or contains unreadable directories")
            total = 0
            for rel in files:
                original = source / rel
                if original.is_symlink() or not original.resolve().is_relative_to(source):
                    raise PolicyError("Source changed while snapshotting")
                size = original.stat().st_size
                total += size
                if size > self.settings.max_upload_bytes or total > self.settings.max_upload_bytes * 4:
                    raise ValidationError("Source exceeds build snapshot size limits")
                with original.open("rb") as stream:
                    content = stream.read(self.settings.max_upload_bytes + 1)
                if len(content) > self.settings.max_upload_bytes:
                    raise ValidationError("Source changed or exceeds snapshot size limits")
                # Reject recognizable credentials, even in ordinary source files.
                text = content.decode("utf-8", errors="replace")
                from ..privacy import PATTERNS
                if scan_secrets(text) or any(re.search(p, text, re.DOTALL if "PRIVATE KEY" in p else 0) for p, _ in PATTERNS[:5]):
                    raise PolicyError("Possible secret found in source; remove it before building")
                dest = folder / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
                shutil.copymode(original, dest)
            for artifact in job.artifacts:
                dest = (folder / artifact.path).resolve()
                if not dest.is_relative_to(folder.resolve()):
                    raise PolicyError("Artifact escapes build context")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(artifact.content, encoding="utf-8")
            dockerfile = (folder / "Dockerfile").read_text(encoding="utf-8")
            if "replace-with-real-command" in dockerfile or (job.profile.project_type.value == "unknown" and "Dockerfile" not in job.profile.existing_dockerfiles):
                raise ValidationError("This project needs a completed Dockerfile before preview")
            record = dict(id=identity, job_id=job_id, state="AWAITING_BUILD_APPROVAL",
                digest=self.digest(folder), file_count=sum(p.is_file() for p in folder.rglob("*")),
                image_tag="aidevops-preview:" + identity, image_id=None,
                container_name="aidevops-" + identity, container_id=None, url=None,
                log="", error=None, expires_at=None, health_path=None, port=None,
                created_at=datetime.now(timezone.utc).isoformat())
            record["suggested_port"] = job.profile.suggested_port or job.plan.exposed_port
            record["suggested_health_path"] = job.profile.suggested_health_path
            return self.save(record)
        except Exception:
            shutil.rmtree(folder.parent)
            raise

    def approve_build(self, identity, digest, approved):
        if self.settings.exec_backend == "disabled":
            raise PolicyError("Container execution is disabled")
        if not approved:
            raise PolicyError("Building requires explicit approval")
        with self.lock:
            if sum(r["state"] in ACTIVE | {"STOPPING"} for r in self.all()) >= 2:
                raise InvalidTransitionError("Two preview operations are already active; wait or cancel one")
            record = self.get(identity)
            if record["state"] not in {"AWAITING_BUILD_APPROVAL", "BUILD_FAILED"}:
                raise InvalidTransitionError("This preview cannot start another build now")
            folder = self.root / identity / "context"
            if digest != record["digest"] or self.digest(folder) != digest:
                raise PolicyError("Snapshot changed; prepare and approve a new snapshot")
            self.update(identity, state="BUILDING", error=None, log="", approved_digest=digest,
                        approved_at=datetime.now(timezone.utc).isoformat())
            event = self.events[identity] = threading.Event()
            self.pool.submit(self.build, identity, event)
            return self.get(identity)

    def build(self, identity, event):
        record = self.get(identity)
        folder = self.root / identity / "context"
        iid = folder.parent / "image-id"
        last_log_update = [0.0]
        def live_output(output):
            if time.monotonic() - last_log_update[0] >= 1:
                self.update(identity, log=safe_log(output))
                last_log_update[0] = time.monotonic()
        try:
            iid.unlink(missing_ok=True)
            code, output, _, reason = self.command(["docker", "build", "--label", f"{LABEL}={identity}",
                "--iidfile", str(iid), "--tag", record["image_tag"], str(folder)],
                timeout=self.settings.build_timeout_seconds, cancel=event, on_output=live_output)
            if event.is_set():
                self.update(identity, state="CANCELLED", log=safe_log(output))
                return
            if code != 0 or reason or not iid.exists():
                raise ValidationError("Image build failed or timed out. Review the build log.")
            image_id = iid.read_text().strip()
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id):
                raise ValidationError("Docker did not return a valid image identity")
            info = self.inspect(image_id, image=True)
            if not info or info.get("Config", {}).get("Labels", {}).get(LABEL) != identity:
                raise ValidationError("Built image could not be independently verified")
            with self.lock:
                ports = info.get("Config", {}).get("ExposedPorts", {})
                exposed = [int(p.split("/")[0]) for p in ports if p.endswith("/tcp") and p.split("/")[0].isdigit()]
                self.update(identity, image_id=image_id, log=safe_log(output),
                            suggested_port=exposed[0] if len(exposed) == 1 else record.get("suggested_port"),
                            state="CANCELLED" if event.is_set() else "BUILT")
        except Exception as exc:
            self.update(identity, state="CANCELLED" if event.is_set() else "BUILD_FAILED",
                        error=safe_log(str(exc)), log=safe_log(locals().get("output", "")))

    def approve_start(self, identity, approved, port, path, ttl, environment):
        if self.settings.exec_backend == "disabled":
            raise PolicyError("Container execution is disabled")
        if not approved:
            raise PolicyError("Starting an app requires separate explicit approval")
        if not 1 <= port <= 65535 or not path.startswith("/") or path.startswith("//") or "#" in path:
            raise ValidationError("Choose a valid container port and local health path")
        if sum(len(k) + len(v) for k, v in environment.items()) > 65536 or len(environment) > 30 or any(not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,63}", k) or "\n" in v or "\r" in v for k, v in environment.items()):
            raise ValidationError("Environment names must be uppercase; values must be single-line")
        with self.lock:
            if sum(r["state"] in ACTIVE | {"STOPPING"} for r in self.all()) >= 2:
                raise InvalidTransitionError("Two preview operations are already active; wait or cancel one")
            record = self.get(identity)
            if record["state"] not in {"BUILT", "STOPPED", "START_FAILED", "EXPIRED"}:
                raise InvalidTransitionError("Build the image or stop the current operation first")
            if not self.owned(record, image=True):
                raise ValidationError("The verified preview image is no longer available")
            # Never persist environment values: only this worker receives them.
            self.update(identity, state="STARTING", error=None, url=None, port=port, health_path=path,
                expires_at=(datetime.now(timezone.utc) + timedelta(minutes=ttl)).isoformat(),
                start_approved_at=datetime.now(timezone.utc).isoformat())
            event = self.events[identity] = threading.Event()
            self.pool.submit(self.start, identity, port, path, environment, event)
            return self.get(identity)

    def remove_container(self, record):
        code, output, _, reason = self.command(["docker", "container", "inspect", record["container_name"]], timeout=10)
        if reason or (code != 0 and "No such" not in output):
            raise ValidationError("Docker could not verify the preview container; retry cleanup")
        if code == 0:
            info = json.loads(output)[0]
            if info.get("Config", {}).get("Labels", {}).get(LABEL) != record["id"]:
                raise PolicyError("Container ownership could not be verified; refusing removal")
            code, _, _, reason = self.command(["docker", "rm", "--force", record["container_name"]])
            if code != 0 or reason:
                raise ValidationError("Docker could not remove this preview container; retry cleanup")

    def start(self, identity, port, path, environment, event):
        record = self.get(identity)
        envfile = self.root / identity / ("runtime-" + uuid.uuid4().hex + ".env")
        secrets = list(environment.values())
        try:
            self.remove_container(record)
            env_args = []
            if environment:
                import os
                fd = os.open(envfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as out:
                    out.write("\n".join(f"{k}={v}" for k, v in environment.items()))
                env_args = ["--env-file", str(envfile)]
            argv = ["docker", "run", "--detach", "--name", record["container_name"],
                "--label", f"{LABEL}={identity}", "--memory", "1g", "--cpus", "2",
                "--pids-limit", "256", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--log-opt", "max-size=1m", "--log-opt", "max-file=1",
                "--publish", f"127.0.0.1::{port}", *env_args, record["image_id"]]
            code, output, _, reason = self.command(argv, cancel=event)
            if code != 0 or reason:
                raise ValidationError("The container could not start: " + safe_log(output, secrets)[-1500:])
            deadline = time.monotonic() + 45
            url = None
            while time.monotonic() < deadline and not event.is_set():
                info = self.owned(record)
                if not info or not info.get("State", {}).get("Running"):
                    exit_code = info.get("State", {}).get("ExitCode") if info else None
                    raise ValidationError(f"Your app stopped during startup (exit {exit_code}). Check the generated startup command and app requirements.")
                bindings = info.get("NetworkSettings", {}).get("Ports", {}).get(f"{port}/tcp") or []
                if bindings and bindings[0].get("HostIp") == "127.0.0.1":
                    url = f"http://127.0.0.1:{int(bindings[0]['HostPort'])}"
                    try:
                        with httpx.Client(trust_env=False, follow_redirects=False, timeout=2) as client:
                            with client.stream("GET", url + path) as response:
                                if 200 <= response.status_code < 400:
                                    with self.lock:
                                        if not event.is_set():
                                            self.update(identity, state="READY", container_id=info["Id"], url=url)
                                            return
                    except httpx.HTTPError:
                        pass
                event.wait(0.5)
            raise ValidationError("Preview cancelled" if event.is_set() else "App started but its HTTP health check did not pass")
        except Exception as exc:
            try:
                self.remove_container(record)
                self.update(identity, state="STOPPED" if event.is_set() else "START_FAILED", url=None,
                            error=redact(str(exc), secrets))
            except Exception:
                self.update(identity, state="CLEANUP_FAILED", url=None, error="Container cleanup failed; retry Stop preview")
        finally:
            envfile.unlink(missing_ok=True)
            environment.clear()

    def stop(self, identity):
        with self.lock:
            record = self.get(identity)
            event = self.events.get(identity)
            if event:
                event.set()
            if record["state"] in ACTIVE:
                return self.update(identity, state="STOPPING", url=None)
            self.remove_container(record)
            return self.update(identity, state="STOPPED", url=None)

    def cleanup(self, identity):
        with self.lock:
            record = self.get(identity)
            if record["state"] in ACTIVE | {"STOPPING"}:
                raise InvalidTransitionError("Stop the operation and wait for it to finish before cleanup")
            self.remove_container(record)
            if self.owned(record, image=True):
                code, _, _, reason = self.command(["docker", "image", "rm", record.get("image_id") or record["image_tag"]])
                if code != 0 or reason:
                    raise ValidationError("Image is in use or Docker cleanup failed")
            target = (self.root / identity).resolve()
            if target.parent != self.root.resolve():
                raise PolicyError("Invalid cleanup path")
            shutil.rmtree(target, ignore_errors=False) if target.exists() else None
            return self.update(identity, state="REMOVED", url=None, image_id=None, container_id=None, log="")

    def logs(self, identity):
        record = self.get(identity)
        # Runtime logs can print credentials. They are deliberately not exported.
        return {"build_log": record["log"], "runtime_log": "Runtime logs are withheld because application output may contain secrets. Use Docker locally if needed."}

    def reconcile(self):
        for record in self.all():
            for envfile in (self.root / record["id"]).glob("runtime-*.env"):
                envfile.unlink(missing_ok=True)
            if record["state"] in ACTIVE | {"STOPPING"}:
                try:
                    self.remove_container(record)
                    self.update(record["id"], state="INTERRUPTED", url=None, error="Service restarted; operation was not replayed")
                except Exception:
                    self.update(record["id"], state="CLEANUP_FAILED", url=None, error="Retry preview cleanup when Docker is available")
        self.sweep()

    def sweep(self):
        for saved in self.all():
            if self.halt.is_set():
                break
            with self.lock:
                record = self.get(saved["id"])
                if record["state"] != "READY":
                    continue
                try:
                    if datetime.fromisoformat(record["expires_at"]) <= datetime.now(timezone.utc):
                        self.remove_container(record)
                        self.update(record["id"], state="EXPIRED", url=None)
                    else:
                        info = self.owned(record)
                        if not info or not info.get("State", {}).get("Running"):
                            self.update(record["id"], state="START_FAILED", url=None, error="Preview container is no longer running")
                except Exception:
                    self.update(record["id"], state="CLEANUP_FAILED", url=None, error="Could not verify preview; retry Stop preview")

    def watch(self):
        while not self.halt.wait(10):
            self.sweep()

    def close(self):
        self.halt.set()
        for event in self.events.values():
            event.set()
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.monitor.join()
        self.worker_lock.close()
