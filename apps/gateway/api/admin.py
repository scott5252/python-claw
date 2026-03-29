from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from apps.gateway.deps import (
    get_approval_decision_service,
    get_collaboration_service,
    get_db,
    get_delegation_service,
    get_diagnostics_service,
    get_operator_principal,
    get_session_service,
    require_internal_or_operator_read,
    require_operator_read_access,
    require_operator_access,
)
from src.policies.approval_actions import ApprovalDecisionService
from src.sessions.collaboration import CollaborationConflictError, SessionCollaborationService
from src.delegations.service import DelegationService
from src.domain.schemas import (
    AgentProfileResponse,
    ApprovalActionPromptResponse,
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    CollaborationAssignRequest,
    CollaborationEventResponse,
    CollaborationMutationRequest,
    CollaborationSnapshotResponse,
    DelegationEventResponse,
    DelegationResponse,
    DiagnosticsPageResponse,
    ExecutionRunResponse,
    MessagePageResponse,
    ModelProfileResponse,
    OperatorNoteCreateRequest,
    OperatorNoteResponse,
    PendingApprovalResponse,
    RunDiagnosticsResponse,
    SessionContinuityDiagnosticsResponse,
    SessionResponse,
    SessionRunPageResponse,
)
from src.observability.diagnostics import DiagnosticsService
from src.sessions.service import SessionService

router = APIRouter(tags=["sessions"])


def _raise_conflict() -> None:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="stale collaboration version")


@router.get("/sessions/{session_id}", response_model=SessionResponse, dependencies=[Depends(require_operator_read_access)])
def get_session(
    session_id: str,
    db: Session = Depends(get_db),
    service: SessionService = Depends(get_session_service),
) -> SessionResponse:
    session = service.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return session


@router.get("/agents", response_model=list[AgentProfileResponse], dependencies=[Depends(require_operator_read_access)])
def list_agents(
    db: Session = Depends(get_db),
    service: SessionService = Depends(get_session_service),
) -> list[AgentProfileResponse]:
    return service.list_agents(db)


@router.get("/agents/{agent_id}", response_model=AgentProfileResponse, dependencies=[Depends(require_operator_read_access)])
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
    dependencies=[Depends(require_operator_read_access)],
)
def get_agent_sessions(
    agent_id: str,
    db: Session = Depends(get_db),
    service: SessionService = Depends(get_session_service),
) -> list[SessionResponse]:
    return service.list_agent_sessions(db, agent_id=agent_id)


@router.get(
    "/agents/{agent_id}/delegations",
    response_model=list[DelegationResponse],
    dependencies=[Depends(require_operator_read_access)],
)
def get_agent_delegations(
    agent_id: str,
    db: Session = Depends(get_db),
    service: DelegationService = Depends(get_delegation_service),
) -> list[DelegationResponse]:
    return [DelegationResponse.model_validate(item, from_attributes=True) for item in service.repository.list_by_child_agent(db, agent_id=agent_id)]


@router.get("/model-profiles", response_model=list[ModelProfileResponse], dependencies=[Depends(require_operator_read_access)])
def list_model_profiles(
    db: Session = Depends(get_db),
    service: SessionService = Depends(get_session_service),
) -> list[ModelProfileResponse]:
    return service.list_model_profiles(db)


@router.get(
    "/model-profiles/{profile_key}",
    response_model=ModelProfileResponse,
    dependencies=[Depends(require_operator_read_access)],
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


@router.get("/sessions/{session_id}/messages", response_model=MessagePageResponse, dependencies=[Depends(require_operator_read_access)])
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


@router.get(
    "/sessions/{session_id}/automation",
    response_model=CollaborationSnapshotResponse,
    dependencies=[Depends(require_operator_read_access)],
)
def get_session_automation(
    session_id: str,
    db: Session = Depends(get_db),
    service: SessionService = Depends(get_session_service),
) -> CollaborationSnapshotResponse:
    snapshot = service.get_collaboration_snapshot(db, session_id=session_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return snapshot


@router.get(
    "/sessions/{session_id}/notes",
    response_model=list[OperatorNoteResponse],
    dependencies=[Depends(require_operator_read_access)],
)
def get_session_notes(
    session_id: str,
    db: Session = Depends(get_db),
    service: SessionService = Depends(get_session_service),
) -> list[OperatorNoteResponse]:
    notes = service.list_operator_notes(db, session_id=session_id)
    if notes is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return notes


@router.get(
    "/sessions/{session_id}/collaboration",
    response_model=list[CollaborationEventResponse],
    dependencies=[Depends(require_operator_read_access)],
)
def get_session_collaboration(
    session_id: str,
    db: Session = Depends(get_db),
    service: SessionService = Depends(get_session_service),
) -> list[CollaborationEventResponse]:
    events = service.list_collaboration_events(db, session_id=session_id)
    if events is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return events


@router.get(
    "/sessions/{session_id}/approval-prompts",
    response_model=list[ApprovalActionPromptResponse],
    dependencies=[Depends(require_operator_read_access)],
)
def get_approval_prompts(
    session_id: str,
    db: Session = Depends(get_db),
    service: SessionService = Depends(get_session_service),
) -> list[ApprovalActionPromptResponse]:
    prompts = service.list_approval_action_prompts(db, session_id=session_id)
    if prompts is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return prompts


@router.get(
    "/sessions/{session_id}/governance/pending",
    response_model=list[PendingApprovalResponse],
    dependencies=[Depends(require_operator_read_access)],
)
def get_pending_governance_items(
    session_id: str,
    db: Session = Depends(get_db),
    service: SessionService = Depends(get_session_service),
) -> list[PendingApprovalResponse]:
    items = service.get_pending_approvals(db, session_id=session_id)
    if items is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return items


@router.post(
    "/sessions/{session_id}/takeover",
    response_model=CollaborationSnapshotResponse,
    dependencies=[Depends(require_operator_read_access)],
)
def takeover_session(
    session_id: str,
    payload: CollaborationMutationRequest,
    db: Session = Depends(get_db),
    operator_id: str = Depends(get_operator_principal),
    collaboration: SessionCollaborationService = Depends(get_collaboration_service),
    service: SessionService = Depends(get_session_service),
) -> CollaborationSnapshotResponse:
    try:
        collaboration.takeover_session(
            db,
            session_id=session_id,
            expected_collaboration_version=payload.expected_collaboration_version,
            operator_id=operator_id,
            reason=payload.reason,
            note=payload.note,
        )
    except CollaborationConflictError:
        _raise_conflict()
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    db.commit()
    snapshot = service.get_collaboration_snapshot(db, session_id=session_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return snapshot


@router.post(
    "/sessions/{session_id}/pause",
    response_model=CollaborationSnapshotResponse,
    dependencies=[Depends(require_operator_access)],
)
def pause_session(
    session_id: str,
    payload: CollaborationMutationRequest,
    db: Session = Depends(get_db),
    operator_id: str = Depends(get_operator_principal),
    collaboration: SessionCollaborationService = Depends(get_collaboration_service),
    service: SessionService = Depends(get_session_service),
) -> CollaborationSnapshotResponse:
    try:
        collaboration.pause_session(
            db,
            session_id=session_id,
            expected_collaboration_version=payload.expected_collaboration_version,
            operator_id=operator_id,
            reason=payload.reason,
            note=payload.note,
        )
    except CollaborationConflictError:
        _raise_conflict()
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    db.commit()
    snapshot = service.get_collaboration_snapshot(db, session_id=session_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return snapshot


@router.post(
    "/sessions/{session_id}/resume",
    response_model=CollaborationSnapshotResponse,
    dependencies=[Depends(require_operator_access)],
)
def resume_session(
    session_id: str,
    payload: CollaborationMutationRequest,
    db: Session = Depends(get_db),
    operator_id: str = Depends(get_operator_principal),
    collaboration: SessionCollaborationService = Depends(get_collaboration_service),
    service: SessionService = Depends(get_session_service),
) -> CollaborationSnapshotResponse:
    try:
        collaboration.resume_session(
            db,
            session_id=session_id,
            expected_collaboration_version=payload.expected_collaboration_version,
            operator_id=operator_id,
            reason=payload.reason,
            note=payload.note,
        )
    except CollaborationConflictError:
        _raise_conflict()
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    db.commit()
    snapshot = service.get_collaboration_snapshot(db, session_id=session_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return snapshot


@router.post(
    "/sessions/{session_id}/assign",
    response_model=CollaborationSnapshotResponse,
    dependencies=[Depends(require_operator_access)],
)
def assign_session(
    session_id: str,
    payload: CollaborationAssignRequest,
    db: Session = Depends(get_db),
    operator_id: str = Depends(get_operator_principal),
    collaboration: SessionCollaborationService = Depends(get_collaboration_service),
    service: SessionService = Depends(get_session_service),
) -> CollaborationSnapshotResponse:
    try:
        collaboration.assign_session(
            db,
            session_id=session_id,
            expected_collaboration_version=payload.expected_collaboration_version,
            operator_id=operator_id,
            assigned_operator_id=payload.assigned_operator_id,
            assigned_queue_key=payload.assigned_queue_key,
            reason=payload.reason,
            note=payload.note,
        )
    except CollaborationConflictError:
        _raise_conflict()
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    db.commit()
    snapshot = service.get_collaboration_snapshot(db, session_id=session_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return snapshot


@router.post(
    "/sessions/{session_id}/notes",
    response_model=OperatorNoteResponse,
    dependencies=[Depends(require_operator_access)],
)
def create_note(
    session_id: str,
    payload: OperatorNoteCreateRequest,
    db: Session = Depends(get_db),
    operator_id: str = Depends(get_operator_principal),
    collaboration: SessionCollaborationService = Depends(get_collaboration_service),
) -> OperatorNoteResponse:
    try:
        note = collaboration.add_operator_note(
            db,
            session_id=session_id,
            operator_id=operator_id,
            note_kind=payload.note_kind,
            body=payload.body,
        )
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    db.commit()
    return OperatorNoteResponse.model_validate(note, from_attributes=True)


@router.post(
    "/sessions/{session_id}/governance/{proposal_id}/decision",
    response_model=ApprovalDecisionResponse,
    dependencies=[Depends(require_operator_access)],
)
def decide_governance(
    session_id: str,
    proposal_id: str,
    payload: ApprovalDecisionRequest,
    db: Session = Depends(get_db),
    operator_id: str = Depends(get_operator_principal),
    approvals: ApprovalDecisionService = Depends(get_approval_decision_service),
) -> ApprovalDecisionResponse:
    try:
        result = approvals.decide(
            db,
            session_id=session_id,
            message_id=0,
            actor_id=operator_id,
            decision=payload.decision,
            proposal_id=proposal_id,
            token=payload.token,
            decided_via="admin_api",
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    return ApprovalDecisionResponse.model_validate(result, from_attributes=True)


@router.get("/runs/{run_id}", response_model=ExecutionRunResponse, dependencies=[Depends(require_operator_read_access)])
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    service: SessionService = Depends(get_session_service),
) -> ExecutionRunResponse:
    run = service.get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    return run


@router.get("/sessions/{session_id}/runs", response_model=SessionRunPageResponse, dependencies=[Depends(require_operator_read_access)])
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
    "/sessions/{session_id}/delegations",
    response_model=list[DelegationResponse],
    dependencies=[Depends(require_operator_read_access)],
)
def get_session_delegations(
    session_id: str,
    db: Session = Depends(get_db),
    service: DelegationService = Depends(get_delegation_service),
) -> list[DelegationResponse]:
    return [DelegationResponse.model_validate(item, from_attributes=True) for item in service.repository.list_by_parent_session(db, session_id=session_id)]


@router.get(
    "/delegations/{delegation_id}",
    response_model=DelegationResponse,
    dependencies=[Depends(require_operator_read_access)],
)
def get_delegation(
    delegation_id: str,
    db: Session = Depends(get_db),
    service: DelegationService = Depends(get_delegation_service),
) -> DelegationResponse:
    delegation = service.repository.get_delegation(db, delegation_id=delegation_id)
    if delegation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="delegation not found")
    return DelegationResponse.model_validate(delegation, from_attributes=True)


@router.get(
    "/delegations/{delegation_id}/events",
    response_model=list[DelegationEventResponse],
    dependencies=[Depends(require_operator_read_access)],
)
def get_delegation_events(
    delegation_id: str,
    db: Session = Depends(get_db),
    service: DelegationService = Depends(get_delegation_service),
) -> list[DelegationEventResponse]:
    return [
        DelegationEventResponse.model_validate(item, from_attributes=True)
        for item in service.repository.list_events(db, delegation_id=delegation_id)
    ]


@router.get(
    "/diagnostics/runs",
    response_model=DiagnosticsPageResponse,
    dependencies=[Depends(require_internal_or_operator_read)],
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
    dependencies=[Depends(require_internal_or_operator_read)],
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
    dependencies=[Depends(require_internal_or_operator_read)],
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
    dependencies=[Depends(require_internal_or_operator_read)],
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
    dependencies=[Depends(require_internal_or_operator_read)],
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
    dependencies=[Depends(require_internal_or_operator_read)],
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
    dependencies=[Depends(require_internal_or_operator_read)],
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
