from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from src.jobs.repository import JobsRepository


@dataclass
class SessionConcurrencyService:
    repository: JobsRepository
    lease_seconds: int
    global_concurrency_limit: int

    def acquire_lane(
        self,
        db: Session,
        *,
        lane_key: str,
        execution_run_id: str,
        worker_id: str,
        now: datetime,
    ) -> datetime | None:
        return self.repository.acquire_session_lease(
            db,
            lane_key=lane_key,
            execution_run_id=execution_run_id,
            worker_id=worker_id,
            lease_seconds=self.lease_seconds,
            now=now,
        )

    def refresh_lane(
        self,
        db: Session,
        *,
        lane_key: str,
        execution_run_id: str,
        worker_id: str,
        now: datetime,
    ) -> datetime | None:
        return self.repository.refresh_session_lease(
            db,
            lane_key=lane_key,
            execution_run_id=execution_run_id,
            worker_id=worker_id,
            lease_seconds=self.lease_seconds,
            now=now,
        )

    def release_lane(
        self,
        db: Session,
        *,
        lane_key: str,
        execution_run_id: str,
        worker_id: str,
    ) -> None:
        self.repository.release_session_lease(
            db,
            lane_key=lane_key,
            execution_run_id=execution_run_id,
            worker_id=worker_id,
        )

    def refresh_global_slot(
        self,
        db: Session,
        *,
        execution_run_id: str,
        worker_id: str,
        now: datetime,
    ) -> datetime | None:
        return self.repository.refresh_global_slot(
            db,
            execution_run_id=execution_run_id,
            worker_id=worker_id,
            lease_seconds=self.lease_seconds,
            now=now,
        )

    def release_global_slot(
        self,
        db: Session,
        *,
        execution_run_id: str,
        worker_id: str,
    ) -> None:
        self.repository.release_global_slot(
            db,
            execution_run_id=execution_run_id,
            worker_id=worker_id,
        )
