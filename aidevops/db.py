"""SQLite persistence for job records.

The store keeps a small indexed surface (id, state, timestamps) plus the full
job document as JSON, so schema evolution does not require migrations for the
MVP. Every write goes through :class:`JobStore` which enforces state-machine
rules and appends to the transition history.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from .errors import InvalidTransitionError, NotFoundError
from .models import ALLOWED_TRANSITIONS, JobRecord, JobState, StateTransition, can_transition

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    state       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    project_name TEXT,
    data        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);
"""


class JobStore:
    """Thread-safe (per-connection) job repository."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    # ---------------------------------------------------------------- reads
    def get(self, job_id: str) -> JobRecord:
        with self._connect() as conn:
            row = conn.execute("SELECT data FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"job {job_id} not found")
        return JobRecord.model_validate_json(row["data"])

    def list(self, *, limit: int = 50) -> list[JobRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [JobRecord.model_validate_json(r["data"]) for r in rows]

    def _iter(self) -> Iterator[JobRecord]:
        yield from self.list(limit=10_000)

    # --------------------------------------------------------------- writes
    def create(self, job: JobRecord) -> JobRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO jobs (id, state, created_at, updated_at, project_name, data)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    job.id,
                    job.state.value,
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                    job.project_name,
                    job.model_dump_json(),
                ),
            )
        return job

    def save(self, job: JobRecord) -> JobRecord:
        job.updated_at = datetime.now(timezone.utc)
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE jobs SET state = ?, updated_at = ?, project_name = ?, data = ?"
                " WHERE id = ? AND state = ?",
                (
                    job.state.value,
                    job.updated_at.isoformat(),
                    job.project_name,
                    job.model_dump_json(),
                    job.id,
                    job.state.value,
                ),
            )
            if cur.rowcount == 0:
                self.get(job.id)
                raise InvalidTransitionError("job state changed while work was running; stale update refused")
        return job

    def transition(
        self, job_id: str, new_state: JobState, *, reason: str | None = None
    ) -> JobRecord:
        """Move a job to ``new_state``, rejecting illegal transitions."""

        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT data FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise NotFoundError(f"job {job_id} not found")
            job = JobRecord.model_validate_json(row["data"])
            if not can_transition(job.state, new_state):
                raise InvalidTransitionError(
                    f"cannot transition job {job_id} from {job.state.value} to {new_state.value}",
                    detail=f"allowed: {sorted(s.value for s in ALLOWED_TRANSITIONS[job.state])}",
                )
            job.history.append(
                StateTransition(from_state=job.state, to_state=new_state, reason=reason)
            )
            job.state = new_state
            job.updated_at = datetime.now(timezone.utc)
            conn.execute(
                "UPDATE jobs SET state = ?, updated_at = ?, data = ? WHERE id = ?",
                (job.state.value, job.updated_at.isoformat(), job.model_dump_json(), job.id),
            )
        return job

    def cancel(self, job_id: str) -> JobRecord:
        job = self.get(job_id)
        if job.state.value in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return job
        return self.transition(job_id, JobState.CANCELLED, reason="cancelled by operator")
