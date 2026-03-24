from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.domain.schemas import DependencyStatusResponse, HealthResponse


@dataclass
class HealthService:
    settings: Settings

    def live(self) -> HealthResponse:
        return HealthResponse(status="ok", service=self.settings.app_name, checks=[])

    def ready(self, db: Session) -> HealthResponse:
        checks: list[DependencyStatusResponse] = []
        overall_status = "ok"
        try:
            db.execute(text("SELECT 1"))
            checks.append(DependencyStatusResponse(name="postgresql", status="ok"))
        except Exception as exc:
            checks.append(DependencyStatusResponse(name="postgresql", status="failed", detail=str(exc)))
            overall_status = "degraded"
        checks.append(
            DependencyStatusResponse(
                name="node_runner",
                status="enabled" if self.settings.remote_execution_enabled else "not_enabled",
            )
        )
        checks.append(
            DependencyStatusResponse(
                name="tracing",
                status="enabled" if self.settings.observability_tracing_enabled else "not_configured",
            )
        )
        return HealthResponse(status=overall_status, service=self.settings.app_name, checks=checks)
