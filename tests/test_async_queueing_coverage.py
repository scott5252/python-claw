from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from apps.gateway.deps import create_run_execution_service, create_session_service
from apps.gateway.main import create_app
from src.config.settings import Settings
from src.db.models import (
    DedupeStatus,
    ExecutionRunRecord,
    ExecutionRunStatus,
    GlobalRunLeaseRecord,
    InboundDedupeRecord,
    ScheduledJobFireRecord,
    ScheduledJobRecord,
    SessionRunLeaseRecord,
)
from src.gateway.idempotency import IdempotencyConflictError
from src.jobs.repository import JobsRepository
from src.jobs.service import FailureClassifier, RunExecutionService, SchedulerService
from src.routing.service import RoutingInput, normalize_routing_input
from src.sessions.concurrency import SessionConcurrencyService
from src.sessions.repository import SessionRepository


@dataclass
class RaisingGraph:
    error: Exception

    def invoke(self, **kwargs):
        _ = kwargs
        raise self.error


def _create_session_with_message(session_manager, *, external_message_id: str = "msg-1"):
    repository = SessionRepository()
    routing = normalize_routing_input(
        RoutingInput(
            channel_kind="slack",
            channel_account_id="acct",
            sender_id="sender",
            peer_id="peer",
        )
    )
    with session_manager.session() as db:
        session = repository.get_or_create_session(db, routing)
        message = repository.append_message(
            db,
            session,
            role="user",
            content="hello",
            external_message_id=external_message_id,
            sender_id="sender",
            last_activity_at=datetime.now(timezone.utc),
        )
        db.commit()
        return session.id, message.id


def _create_scheduled_job(session_manager, *, session_id: str, job_key: str = "job-1", enabled: int = 1) -> str:
    with session_manager.session() as db:
        job = ScheduledJobRecord(
            job_key=job_key,
            agent_id="default-agent",
            target_kind="session",
            session_id=session_id,
            cron_expr="* * * * *",
            payload_json=json.dumps({"content": "scheduled"}),
            enabled=enabled,
        )
        db.add(job)
        db.commit()
        return job.id


def _create_execution_run(
    session_manager,
    *,
    session_id: str,
    message_id: int | None,
    trigger_kind: str = "inbound_message",
    trigger_ref: str = "trigger-1",
    max_attempts: int = 3,
    status: str = ExecutionRunStatus.QUEUED.value,
    worker_id: str | None = None,
) -> str:
    with session_manager.session() as db:
        run = ExecutionRunRecord(
            session_id=session_id,
            message_id=message_id,
            agent_id="default-agent",
            trigger_kind=trigger_kind,
            trigger_ref=trigger_ref,
            lane_key=session_id,
            status=status,
            attempt_count=0,
            max_attempts=max_attempts,
            available_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            worker_id=worker_id,
        )
        db.add(run)
        db.commit()
        return run.id


def test_admin_endpoints_return_404_for_missing_resources(client) -> None:
    assert client.get("/sessions/missing").status_code == 404
    assert client.get("/sessions/missing/messages").status_code == 404
    assert client.get("/sessions/missing/governance/pending").status_code == 404
    assert client.get("/sessions/missing/runs").status_code == 404
    assert client.get("/runs/missing").status_code == 404


def test_inbound_conflict_when_dedupe_claim_is_in_progress(session_manager, settings: Settings) -> None:
    now = datetime.now(timezone.utc)
    with session_manager.session() as db:
        db.add(
            InboundDedupeRecord(
                status=DedupeStatus.CLAIMED.value,
                channel_kind="slack",
                channel_account_id="acct",
                external_message_id="msg-1",
                first_seen_at=now,
                expires_at=now + timedelta(days=30),
            )
        )
        db.commit()

    client = TestClient(create_app(settings=settings, session_manager=session_manager))
    response = client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-1",
            "sender_id": "sender",
            "content": "hello",
            "peer_id": "peer",
        },
    )

    assert response.status_code == 409
    assert "already claimed" in response.json()["detail"]


def test_duplicate_replay_without_execution_run_fails_closed(session_manager, settings: Settings) -> None:
    service = create_session_service(settings)
    session_id, message_id = _create_session_with_message(session_manager)

    with session_manager.session() as db:
        db.add(
            InboundDedupeRecord(
                status=DedupeStatus.COMPLETED.value,
                channel_kind="slack",
                channel_account_id="acct",
                external_message_id="msg-1",
                session_id=session_id,
                message_id=message_id,
                first_seen_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            )
        )
        db.commit()

    with session_manager.session() as db:
        with pytest.raises(IdempotencyConflictError, match="missing execution run"):
            service.process_inbound(
                db=db,
                channel_kind="slack",
                channel_account_id="acct",
                external_message_id="msg-1",
                sender_id="sender",
                content="hello",
                peer_id="peer",
                group_id=None,
            )


def test_run_execution_service_marks_scheduler_fire_failed_for_retryable_dead_letter(session_manager) -> None:
    session_id, message_id = _create_session_with_message(session_manager)
    job_id = _create_scheduled_job(session_manager, session_id=session_id)
    jobs_repository = JobsRepository()
    fire_key = "job-1:2026-03-23T12:00:00+00:00"

    with session_manager.session() as db:
        fire = jobs_repository.create_or_get_scheduled_fire(
            db,
            scheduled_job_id=job_id,
            fire_key=fire_key,
            scheduled_for=datetime(2026, 3, 23, 12, 0, tzinfo=timezone.utc),
        )
        run = ExecutionRunRecord(
            session_id=session_id,
            message_id=message_id,
            agent_id="default-agent",
            trigger_kind="scheduler_fire",
            trigger_ref=fire.fire_key,
            lane_key=session_id,
            status=ExecutionRunStatus.QUEUED.value,
            attempt_count=0,
            max_attempts=1,
            available_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        db.add(run)
        db.commit()
        run_id = run.id
        fire_id = fire.id

    service = RunExecutionService(
        jobs_repository=jobs_repository,
        session_repository=SessionRepository(),
        concurrency_service=SessionConcurrencyService(
            repository=jobs_repository,
            lease_seconds=30,
            global_concurrency_limit=1,
        ),
        assistant_graph_factory=lambda: RaisingGraph(ValueError("temporary outage")),
        failure_classifier=FailureClassifier(),
        base_backoff_seconds=2,
        max_backoff_seconds=8,
    )

    with session_manager.session() as db:
        processed = service.process_next_run(db, worker_id="worker-1")
        db.commit()

    assert processed == run_id
    with session_manager.session() as db:
        run = db.get(ExecutionRunRecord, run_id)
        fire = jobs_repository.mark_fire_by_key(db, fire_key="missing-fire", status="failed")
        session_lease = db.get(SessionRunLeaseRecord, session_id)
        global_leases = list(db.query(GlobalRunLeaseRecord).all())

    assert run is not None
    assert run.status == ExecutionRunStatus.DEAD_LETTER.value
    assert run.attempt_count == 1
    assert run.last_error == "temporary outage"
    assert run.finished_at is not None
    assert fire is None
    assert session_lease is None
    assert global_leases == []

    with session_manager.session() as db:
        refreshed_fire = jobs_repository.mark_fire_terminal(db, fire_id=fire_id, status="cancelled", error="manual stop")
        db.commit()

    assert refreshed_fire.status == "cancelled"
    assert refreshed_fire.last_error == "manual stop"


def test_run_execution_service_marks_scheduler_fire_failed_for_non_retryable_error(
    session_manager,
    settings: Settings,
) -> None:
    session_id, _ = _create_session_with_message(session_manager)
    job_id = _create_scheduled_job(session_manager, session_id=session_id, job_key="job-2")
    jobs_repository = JobsRepository()
    fire_key = "job-2:2026-03-23T12:01:00+00:00"

    with session_manager.session() as db:
        jobs_repository.create_or_get_scheduled_fire(
            db,
            scheduled_job_id=job_id,
            fire_key=fire_key,
            scheduled_for=datetime(2026, 3, 23, 12, 1, tzinfo=timezone.utc),
        )
        run = ExecutionRunRecord(
            session_id=session_id,
            message_id=None,
            agent_id="default-agent",
            trigger_kind="scheduler_fire",
            trigger_ref=fire_key,
            lane_key=session_id,
            status=ExecutionRunStatus.QUEUED.value,
            attempt_count=0,
            max_attempts=3,
            available_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        db.add(run)
        db.commit()
        run_id = run.id

    service = create_run_execution_service(settings)
    with session_manager.session() as db:
        processed = service.process_next_run(db, worker_id="worker-2")
        db.commit()

    assert processed == run_id
    with session_manager.session() as db:
        run = db.get(ExecutionRunRecord, run_id)
        fire = db.query(ScheduledJobFireRecord).filter_by(fire_key=fire_key).one()

    assert run is not None
    assert run.status == ExecutionRunStatus.FAILED.value
    assert "missing canonical transcript state" in (run.last_error or "")
    assert fire is not None
    assert fire.status == "failed"


def test_jobs_repository_recover_expired_leases_and_manage_scheduler_fires(session_manager) -> None:
    repository = JobsRepository()
    session_id, message_id = _create_session_with_message(session_manager)
    job_id = _create_scheduled_job(session_manager, session_id=session_id, job_key="job-list")
    _create_scheduled_job(session_manager, session_id=session_id, job_key="job-disabled", enabled=0)

    now = datetime(2026, 3, 23, 12, 0, tzinfo=timezone.utc)
    run_id = _create_execution_run(
        session_manager,
        session_id=session_id,
        message_id=message_id,
        trigger_ref="run-recover",
        status=ExecutionRunStatus.RUNNING.value,
        worker_id="crashed-worker",
    )

    with session_manager.session() as db:
        run = db.get(ExecutionRunRecord, run_id)
        assert run is not None
        run.claimed_at = now - timedelta(minutes=1)
        run.started_at = now - timedelta(minutes=1)
        db.add(
            SessionRunLeaseRecord(
                lane_key=session_id,
                execution_run_id=run.id,
                worker_id="crashed-worker",
                lease_expires_at=now - timedelta(seconds=1),
            )
        )
        db.add(
            GlobalRunLeaseRecord(
                slot_key="0",
                execution_run_id=run.id,
                worker_id="crashed-worker",
                lease_expires_at=now - timedelta(seconds=1),
            )
        )
        fire = repository.create_or_get_scheduled_fire(
            db,
            scheduled_job_id=job_id,
            fire_key="job-list:2026-03-23T12:00:00+00:00",
            scheduled_for=now,
        )
        db.commit()
        fire_id = fire.id

    with session_manager.session() as db:
        repository.recover_expired_leases(db, now=now)
        repository.link_fire_to_run(db, fire_id=fire_id, run_id=run_id)
        enabled_jobs = repository.list_enabled_scheduled_jobs(db)
        db.commit()

    assert [job.job_key for job in enabled_jobs] == ["job-list"]
    with session_manager.session() as db:
        run = db.get(ExecutionRunRecord, run_id)
        session_lease = db.get(SessionRunLeaseRecord, session_id)
        global_slot = db.get(GlobalRunLeaseRecord, "0")
        fire = repository.mark_fire_by_key(db, fire_key="job-list:2026-03-23T12:00:00+00:00", status="completed")
        db.commit()

    assert run is not None
    assert run.status == ExecutionRunStatus.RETRY_WAIT.value
    assert run.attempt_count == 1
    assert run.worker_id is None
    assert session_lease is None
    assert global_slot is None
    assert fire is not None
    assert fire.execution_run_id == run_id


def test_jobs_repository_claim_helpers_and_owned_run_guards(session_manager) -> None:
    repository = JobsRepository()
    session_id, message_id = _create_session_with_message(session_manager)
    run_id = _create_execution_run(
        session_manager,
        session_id=session_id,
        message_id=message_id,
        trigger_ref="run-claim",
    )

    with session_manager.session() as db:
        assert repository.claim_next_eligible_run(
            db,
            worker_id="worker-1",
            lease_seconds=30,
            global_concurrency_limit=0,
            now=datetime.now(timezone.utc),
        ) is None

    with session_manager.session() as db:
        claim = repository.claim_next_eligible_run(
            db,
            worker_id="worker-1",
            lease_seconds=30,
            global_concurrency_limit=1,
            now=datetime.now(timezone.utc),
        )
        assert claim is not None
        refreshed_lane = repository.refresh_session_lease(
            db,
            lane_key=session_id,
            execution_run_id=run_id,
            worker_id="worker-1",
            lease_seconds=30,
            now=datetime.now(timezone.utc),
        )
        refreshed_global = repository.refresh_global_slot(
            db,
            execution_run_id=run_id,
            worker_id="worker-1",
            lease_seconds=30,
            now=datetime.now(timezone.utc),
        )
        repository.mark_running(db, run_id=run_id, worker_id="worker-1")
        repository.complete_run(db, run_id=run_id, worker_id="worker-1")
        repository.release_session_lease(
            db,
            lane_key=session_id,
            execution_run_id=run_id,
            worker_id="other-worker",
        )
        repository.release_global_slot(db, execution_run_id=run_id, worker_id="other-worker")
        db.commit()

    assert refreshed_lane is not None
    assert refreshed_global is not None

    with session_manager.session() as db:
        run = db.get(ExecutionRunRecord, run_id)
        assert run is not None
        assert run.status == ExecutionRunStatus.COMPLETED.value
        repository.release_session_lease(
            db,
            lane_key=session_id,
            execution_run_id=run_id,
            worker_id="worker-1",
        )
        repository.release_global_slot(db, execution_run_id=run_id, worker_id="worker-1")
        db.commit()

    with session_manager.session() as db:
        with pytest.raises(RuntimeError, match="not owned by worker"):
            repository.fail_run(db, run_id=run_id, worker_id="worker-2", error="wrong worker")


def test_session_concurrency_service_delegates_expected_parameters() -> None:
    class RecordingRepository:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        def acquire_session_lease(self, db, **kwargs):
            self.calls.append(("acquire_lane", db, kwargs))
            return "lane-expiry"

        def refresh_session_lease(self, db, **kwargs):
            self.calls.append(("refresh_lane", db, kwargs))
            return "lane-refresh"

        def release_session_lease(self, db, **kwargs):
            self.calls.append(("release_lane", db, kwargs))

        def refresh_global_slot(self, db, **kwargs):
            self.calls.append(("refresh_global", db, kwargs))
            return "global-refresh"

        def release_global_slot(self, db, **kwargs):
            self.calls.append(("release_global", db, kwargs))

    repository = RecordingRepository()
    service = SessionConcurrencyService(
        repository=repository,  # type: ignore[arg-type]
        lease_seconds=45,
        global_concurrency_limit=3,
    )
    now = datetime(2026, 3, 23, 12, 0, tzinfo=timezone.utc)

    assert service.acquire_lane("db", lane_key="lane", execution_run_id="run", worker_id="worker", now=now) == "lane-expiry"
    assert service.refresh_lane("db", lane_key="lane", execution_run_id="run", worker_id="worker", now=now) == "lane-refresh"
    assert service.refresh_global_slot("db", execution_run_id="run", worker_id="worker", now=now) == "global-refresh"
    service.release_lane("db", lane_key="lane", execution_run_id="run", worker_id="worker")
    service.release_global_slot("db", execution_run_id="run", worker_id="worker")

    assert [call[0] for call in repository.calls] == [
        "acquire_lane",
        "refresh_lane",
        "refresh_global",
        "release_lane",
        "release_global",
    ]
    assert repository.calls[0][2]["lease_seconds"] == 45
    assert repository.calls[2][2]["lease_seconds"] == 45


def test_failure_classifier_and_scheduler_service_not_found(session_manager) -> None:
    classifier = FailureClassifier()
    assert classifier.classify(RuntimeError("boom")).retryable is False
    assert classifier.classify(ValueError("boom")).retryable is True

    scheduler_service = SchedulerService(
        jobs_repository=JobsRepository(),
        session_repository=SessionRepository(),
        submit_scheduler_run=lambda **kwargs: ("run-id", "queued"),
    )
    with session_manager.session() as db:
        with pytest.raises(RuntimeError, match="scheduled job not found"):
            scheduler_service.submit_due_job(
                db,
                job_key="missing-job",
                scheduled_for=datetime(2026, 3, 23, 12, 0, tzinfo=timezone.utc),
            )
