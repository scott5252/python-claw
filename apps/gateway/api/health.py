from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from apps.gateway.deps import get_db, get_health_service, require_ready_access
from src.config.settings import Settings
from src.domain.schemas import HealthResponse
from src.observability.health import HealthService

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def healthcheck(service: HealthService = Depends(get_health_service)) -> HealthResponse:
    return service.live()


@router.get("/health/live", response_model=HealthResponse)
def live(service: HealthService = Depends(get_health_service)) -> HealthResponse:
    return service.live()


@router.get("/health/ready", response_model=HealthResponse)
def ready(
    response: Response,
    db: Session = Depends(get_db),
    service: HealthService = Depends(get_health_service),
    _: object | None = Depends(require_ready_access),
) -> HealthResponse:
    result = service.ready(db)
    if result.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
