from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from apps.gateway.deps import get_approval_decision_service, get_quota_service, get_session_manager, get_session_service, get_settings
from src.policies.quota import QuotaService
from src.channels.adapters.slack import SlackAdapter
from src.config.settings import Settings
from src.db.session import DatabaseSessionManager
from src.domain.schemas import ApprovalDecisionRequest, ApprovalDecisionResponse, InboundMessageResponse
from src.policies.approval_actions import ApprovalDecisionService
from src.sessions.service import SessionService

router = APIRouter(prefix="/providers/slack", tags=["providers"])


@router.post("/events", status_code=status.HTTP_202_ACCEPTED)
async def slack_events(
    request: Request,
    x_slack_request_timestamp: str | None = Header(default=None),
    x_slack_signature: str | None = Header(default=None),
    session_manager: DatabaseSessionManager = Depends(get_session_manager),
    service: SessionService = Depends(get_session_service),
    settings: Settings = Depends(get_settings),
    quota_service: QuotaService = Depends(get_quota_service),
):
    body = await request.body()
    payload = await request.json()
    channel_account_id = str(payload.get("api_app_id") or "acct")
    account = settings.get_channel_account(channel_kind="slack", channel_account_id=channel_account_id)
    adapter = SlackAdapter()
    if not adapter.verify_request(
        body=body,
        timestamp=x_slack_request_timestamp,
        signature=x_slack_signature,
        signing_secret=account.signing_secret if account.mode == "real" else "fake-slack-secret",
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid slack signature")
    if payload.get("type") == "url_verification":
        return JSONResponse(status_code=status.HTTP_200_OK, content={"challenge": payload.get("challenge", "")})
    translated = adapter.translate_inbound(payload=payload, channel_account_id=channel_account_id)
    if translated is None:
        return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ignored"})
    if settings.rate_limits_enabled:
        with session_manager.session() as db:
            decision = quota_service.check_and_increment(
                db,
                scope_kind="channel_account",
                scope_key=f"slack:{channel_account_id}",
                limit=settings.inbound_requests_per_minute_per_channel_account,
                window_seconds=60,
            )
            if not decision.allowed:
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="rate limit exceeded",
                    headers={"Retry-After": str(decision.retry_after_seconds or 60)},
                )
            db.commit()
    with session_manager.session() as db:
        result = service.process_inbound(db=db, **translated)
        db.commit()
    return InboundMessageResponse(
        session_id=result.session_id,
        message_id=result.message_id,
        run_id=result.run_id,
        status=result.status,
        dedupe_status=result.dedupe_status,  # type: ignore[arg-type]
        trace_id=result.trace_id,
    )


@router.post("/actions/{channel_account_id}", response_model=ApprovalDecisionResponse)
async def slack_approval_action(
    channel_account_id: str,
    request: Request,
    x_slack_request_timestamp: str | None = Header(default=None),
    x_slack_signature: str | None = Header(default=None),
    approvals: ApprovalDecisionService = Depends(get_approval_decision_service),
    settings: Settings = Depends(get_settings),
    session_manager: DatabaseSessionManager = Depends(get_session_manager),
) -> ApprovalDecisionResponse:
    body = await request.body()
    payload = await request.json()
    account = settings.get_channel_account(channel_kind="slack", channel_account_id=channel_account_id)
    adapter = SlackAdapter()
    if not adapter.verify_request(
        body=body,
        timestamp=x_slack_request_timestamp,
        signature=x_slack_signature,
        signing_secret=account.signing_secret if account.mode == "real" else "fake-slack-secret",
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid slack signature")
    decision = ApprovalDecisionRequest.model_validate(payload)
    with session_manager.session() as db:
        try:
            result = approvals.decide(
                db,
                session_id="",
                message_id=None,
                actor_id="slack-user",
                decision=decision.decision,
                proposal_id=decision.proposal_id,
                token=decision.token,
                decided_via="channel_action",
            )
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        db.commit()
    return ApprovalDecisionResponse.model_validate(result, from_attributes=True)
