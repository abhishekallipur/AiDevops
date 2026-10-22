import pytest

from aidevops.config import Settings
from aidevops.db import JobStore
from aidevops.errors import InvalidTransitionError, NotFoundError
from aidevops.models import JobRecord, JobState


def test_create_and_get(store: JobStore):
    job = store.create(JobRecord(project_name="demo"))
    assert store.get(job.id).project_name == "demo"
    assert store.list()[0].id == job.id


def test_missing_job_raises(store: JobStore):
    with pytest.raises(NotFoundError):
        store.get("job_missing")


def test_valid_transition_records_history(store: JobStore):
    job = store.create(JobRecord())
    store.transition(job.id, JobState.ANALYZING)
    store.transition(job.id, JobState.PLANNED)
    final = store.get(job.id)
    assert final.state == JobState.PLANNED
    assert [t.to_state for t in final.history] == [JobState.ANALYZING, JobState.PLANNED]


def test_invalid_transition_rejected(store: JobStore):
    job = store.create(JobRecord())
    with pytest.raises(InvalidTransitionError):
        store.transition(job.id, JobState.SUCCEEDED)


def test_cancel_is_idempotent(store: JobStore):
    job = store.create(JobRecord())
    assert store.cancel(job.id).state == JobState.CANCELLED
    assert store.cancel(job.id).state == JobState.CANCELLED


def test_state_persists_across_store_instances(settings: Settings):
    first = JobStore(settings.db_path)
    job = first.create(JobRecord(project_name="persisted"))
    second = JobStore(settings.db_path)
    assert second.get(job.id).project_name == "persisted"
