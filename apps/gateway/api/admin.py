from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from apps.gateway.deps import get_db, get_diagnostics_service, get_session_service, require_operator_access
from src.domain.schemas import (
    AgentProfileResponse,
    DiagnosticsPageResponse,
    ExecutionRunResponse,
    MessagePageResponse,
    ModelProfileResponse,
    PendingApprovalResponse,
    RunDiagnosticsResponse,
    SessionContinuityDiagnosticsResponse,
    SessionResponse,
    SessionRunPageResponse,
)
from src.observability.diagnostics import DiagnosticsService
from src.sessions.service import SessionService

router = APIRouter(tags=["sessions"])


@router.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session(
    session_id: str,
    db: Session = Depends(get_db),
    service: SessionService = Depends(get_session_service),
) -> SessionResponse:
    session = service.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return session


@router.get("/agents", response_model=list[AgentProfileResponse], dependencies=[Depends(require_operator_access)])
def list_agents(
    db: Session = Depends(get_db),
    service: SessionService = Depends(get_session_service),
) -> list[AgentProfileResponse]:
    return service.list_agents(db)


@router.get("/agents/{agent_id}", response_model=AgentProfileResponse, dependencies=[Depends(require_operator_access)])
def get_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    service: SessionService = Depends(get_session_service),
) -> AgentProfileResponse:
    agent = service.get_agent(db, agent_id=agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    return agent


@router.get(
    "/agents/{agent_id}/sessions",
    response_model=list[SessionResponse],
    dependencies=[Depends(require_operator_access)],
)
def get_agent_sessions(
    agent_id: str,
    db: Session = Depends(get_db),
    service: SessionService = Depends(get_session_service),
) -> list[SessionResponse]:
    return service.list_agent_sessions(db, agent_id=agent_id)


@router.get("/model-profiles", response_model=list[ModelProfileResponse], dependencies=[Depends(require_operator_access)])
def list_model_profiles(
    db: Session = Depends(get_db),
    service: SessionService = Depends(get_session_service),
) -> list[ModelProfileResponse]:
    return service.list_model_profiles(db)


@router.get(
    "/model-profiles/{profile_key}",
    response_model=ModelProfileResponse,
    dependencies=[Depends(require_operator_access)],
)
def get_model_profile(
    profile_key: str,
    db: Session = Depends(get_db),
    service: SessionService = Depends(get_session_service),
) -> ModelProfileResponse:
    profile = service.get_model_profile(db, profile_key=profile_key)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="model profile not found")
    return profile


@router.get("/sessions/{session_id}/messages", response_model=MessagePageResponse)
def get_session_messages(
    session_id: str,
    limit: int | None = Query(default=None, ge=1),
    before_message_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    service: SessionService = Depends(get_session_service),
) -> MessagePageResponse:
    page = service.get_messages(
        db,
        session_id=session_id,
        limit=limit,
        before_message_id=before_message_id,
    )
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return page


@router.get("/sessions/{session_id}/governance/pending", response_model=list[PendingApprovalResponse])
def get_pending_governance_items(
    session_id: str,
    db: Session = Depends(get_db),
    service: SessionService = Depends(get_session_service),
) -> list[PendingApprovalResponse]:
    items = service.get_pending_approvals(db, session_id=session_id)
    if items is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return items


@router.get("/runs/{run_id}", response_model=ExecutionRunResponse)
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    service: SessionService = Depends(get_session_service),
) -> ExecutionRunResponse:
    run = service.get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    return run


@router.get("/sessions/{session_id}/runs", response_model=SessionRunPageResponse)
def get_session_runs(
    session_id: str,
    limit: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    service: SessionService = Depends(get_session_service),
) -> SessionRunPageResponse:
    page = service.get_session_runs(db, session_id=session_id, limit=limit)
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return page


@router.get(
    "/diagnostics/runs",
    response_model=DiagnosticsPageResponse,
    dependencies=[Depends(require_operator_access)],
)
def list_runs(
    limit: int | None = Query(default=None, ge=1),
    cursor: str | None = Query(default=None),
    status: str | None = Query(default=None),
    trigger_kind: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    stale_only: bool = Query(default=False),
    recent_seconds: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    service: DiagnosticsService = Depends(get_diagnostics_service),
) -> DiagnosticsPageResponse:
    return service.list_runs(
        db,
        limit=limit,
        cursor=cursor,
        status=status,
        trigger_kind=trigger_kind,
        session_id=session_id,
        agent_id=agent_id,
        stale_only=stale_only,
        recent_seconds=recent_seconds,
    )


@router.get(
    "/diagnostics/runs/{run_id}",
    response_model=RunDiagnosticsResponse,
    dependencies=[Depends(require_operator_access)],
)
def get_run_diagnostics(
    run_id: str,
    db: Session = Depends(get_db),
    service: DiagnosticsService = Depends(get_diagnostics_service),
) -> RunDiagnosticsResponse:
    response = service.get_run_detail(db, run_id=run_id)
    if response is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    return response


@router.get(
    "/diagnostics/sessions/{session_id}/continuity",
    response_model=SessionContinuityDiagnosticsResponse,
    dependencies=[Depends(require_operator_access)],
)
def get_session_continuity(
    session_id: str,
    db: Session = Depends(get_db),
    service: DiagnosticsService = Depends(get_diagnostics_service),
) -> SessionContinuityDiagnosticsResponse:
    return service.get_session_continuity(db, session_id=session_id)


@router.get(
    "/diagnostics/outbox-jobs",
    response_model=DiagnosticsPageResponse,
    dependencies=[Depends(require_operator_access)],
)
def get_outbox_jobs(
    limit: int | None = Query(default=None, ge=1),
    cursor: str | None = Query(default=None),
    status: str | None = Query(default=None),
    stale_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    service: DiagnosticsService = Depends(get_diagnostics_service),
) -> DiagnosticsPageResponse:
    return service.list_outbox_jobs(db, limit=limit, cursor=cursor, status=status, stale_only=stale_only)


@router.get(
    "/diagnostics/node-executions",
    response_model=DiagnosticsPageResponse,
    dependencies=[Depends(require_operator_access)],
)
def get_node_executions(
    limit: int | None = Query(default=None, ge=1),
    cursor: str | None = Query(default=None),
    status: str | None = Query(default=None),
    stale_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    service: DiagnosticsService = Depends(get_diagnostics_service),
) -> DiagnosticsPageResponse:
    return service.list_node_executions(db, limit=limit, cursor=cursor, status=status, stale_only=stale_only)


@router.get(
    "/diagnostics/deliveries",
    response_model=DiagnosticsPageResponse,
    dependencies=[Depends(require_operator_access)],
)
def get_deliveries(
    limit: int | None = Query(default=None, ge=1),
    cursor: str | None = Query(default=None),
    status: str | None = Query(default=None),
    stale_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    service: DiagnosticsService = Depends(get_diagnostics_service),
) -> DiagnosticsPageResponse:
    return service.list_deliveries(db, limit=limit, cursor=cursor, status=status, stale_only=stale_only)


@router.get(
    "/diagnostics/attachments",
    response_model=DiagnosticsPageResponse,
    dependencies=[Depends(require_operator_access)],
)
def get_attachments(
    limit: int | None = Query(default=None, ge=1),
    cursor: str | None = Query(default=None),
    normalization_status: str | None = Query(default=None),
    stale_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    service: DiagnosticsService = Depends(get_diagnostics_service),
) -> DiagnosticsPageResponse:
    return service.list_attachments(
        db,
        limit=limit,
        cursor=cursor,
        normalization_status=normalization_status,
        stale_only=stale_only,
    )
