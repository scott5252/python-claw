"""
Tests for the awaiting_approval delegation lifecycle.

Covers the architecture change that prevents double-completion of a delegation
when a child agent pauses for human approval before continuing its work.

Prior behaviour (broken):
  - Child run completes → handle_child_run_completed → delegation COMPLETED
  - User approves → continuation child run queued
  - Continuation run completes → handle_child_run_completed → creates parent
    result run with trigger_ref=delegation.id → deduplication returns the
    already-completed first run → parent NEVER processes the final result.

New behaviour (fixed):
  - Child run completes with awaiting_approval=True
    → handle_child_run_paused_for_approval
    → delegation AWAITING_APPROVAL
    → parent notification run queued (trigger_kind="delegation_approval_prompt")
  - User approves → continuation child run queued → delegation QUEUED
  - Continuation run completes with awaiting_approval=False
    → handle_child_run_completed (first and only time)
    → delegation COMPLETED
    → parent result run queued (trigger_kind="delegation_result")
    → NO deduplication collision
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from apps.gateway.deps import create_approval_decision_service
from apps.gateway.main import create_app
from src.config.settings import (
    HistoricalAgentProfileOverrideConfig,
    PolicyProfileConfig,
    Settings,
    ToolProfileConfig,
)
from src.db.models import DelegationStatus, MessageRole
from src.jobs.repository import JobsRepository
from src.policies.service import PolicyService
from src.routing.service import RoutingInput, normalize_routing_input
from src.sessions.repository import SessionRepository


# ---------------------------------------------------------------------------
# Shared settings
# ---------------------------------------------------------------------------


def _settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        runtime_mode="rule_based",
        diagnostics_admin_bearer_token="admin-secret",
        policy_profiles=[
            PolicyProfileConfig(
                key="default",
                remote_execution_enabled=True,
                delegation_enabled=True,
                max_delegation_depth=2,
                allowed_child_agent_ids=["deploy-agent"],
            ),
            PolicyProfileConfig(
                key="deploy-policy",
                remote_execution_enabled=True,
                delegation_enabled=False,
                max_delegation_depth=0,
            ),
        ],
        tool_profiles=[
            ToolProfileConfig(
                key="default",
                allowed_capability_names=["echo_text", "delegate_to_agent", "remote_exec"],
            ),
            ToolProfileConfig(
                key="deploy-tools",
                allowed_capability_names=["echo_text", "remote_exec"],
            ),
        ],
        historical_agent_profile_overrides=[
            HistoricalAgentProfileOverrideConfig(
                agent_id="deploy-agent",
                model_profile_key="default",
                policy_profile_key="deploy-policy",
                tool_profile_key="deploy-tools",
            )
        ],
    )


# ---------------------------------------------------------------------------
# Test 1: handle_child_run_paused_for_approval creates notification run
# ---------------------------------------------------------------------------


def test_paused_for_approval_marks_delegation_awaiting_and_queues_notification(session_manager) -> None:
    settings = _settings(str(session_manager.engine.url))
    app = create_app(settings=settings, session_manager=session_manager)
    repository = SessionRepository()
    jobs = JobsRepository()
    delegation_service = app.state.delegation_service

    # --- Setup: parent session, delegation, child run running ---
    with session_manager.session() as db:
        parent_session = repository.get_or_create_session(
            db,
            normalize_routing_input(
                RoutingInput(
                    channel_kind="webchat",
                    channel_account_id="acct",
                    sender_id="user-1",
                    peer_id="user-1",
                )
            ),
            owner_agent_id="default-agent",
        )
        message = repository.append_message(
            db,
            parent_session,
            role=MessageRole.USER.value,
            content="Deploy northwind-api to staging.",
            external_message_id="approval-cont-test1",
            sender_id="user-1",
            last_activity_at=datetime.now(timezone.utc),
        )
        parent_run = jobs.create_or_get_execution_run(
            db,
            session_id=parent_session.id,
            message_id=message.id,
            agent_id="default-agent",
            trigger_kind="inbound_message",
            trigger_ref=f"test1-{message.id}",
            lane_key=parent_session.id,
            max_attempts=2,
        )
        delegation_result = delegation_service.create_delegation(
            db,
            policy_service=PolicyService(
                allowed_capabilities={"echo_text", "delegate_to_agent", "remote_exec"},
                delegation_enabled=True,
                max_delegation_depth=2,
                allowed_child_agent_ids={"deploy-agent"},
                remote_execution_enabled=True,
            ),
            parent_session_id=parent_session.id,
            parent_message_id=message.id,
            parent_run_id=parent_run.id,
            parent_agent_id="default-agent",
            parent_policy_profile_key="default",
            parent_tool_profile_key="default",
            correlation_id="tool-call-test1",
            child_agent_id="deploy-agent",
            task_text="POST to the webhook with curl.",
            delegation_kind="deployment",
        )
        delegation_service.mark_child_run_running(db, child_run_id=delegation_result.child_run_id)

        # Simulate child run completing while awaiting approval.
        child_session = repository.get_session(db, delegation_result.child_session_id)
        repository.append_message(
            db,
            child_session,
            role=MessageRole.ASSISTANT.value,
            content="Approval required for remote_exec.",
            external_message_id=None,
            sender_id="deploy-agent",
            last_activity_at=datetime.now(timezone.utc),
        )

        delegation_service.handle_child_run_paused_for_approval(
            db, child_run_id=delegation_result.child_run_id
        )
        db.commit()

    with session_manager.session() as db:
        delegation = delegation_service.repository.get_delegation(
            db, delegation_id=delegation_result.delegation_id
        )
        assert delegation is not None
        assert delegation.status == DelegationStatus.AWAITING_APPROVAL.value

        # A notification run must exist in the parent session with the distinct
        # trigger_kind "delegation_approval_prompt".
        notification_run = jobs.get_execution_run_by_trigger(
            db,
            trigger_kind="delegation_approval_prompt",
            trigger_ref=f"{delegation_result.delegation_id}:{delegation_result.child_run_id}",
        )
        assert notification_run is not None
        assert notification_run.session_id == parent_session.id
        assert notification_run.status == "queued"

        # The notification message carries the delegation_result JSON with
        # status="awaiting_approval".
        notification_message = repository.get_message(db, message_id=notification_run.message_id)
        assert notification_message is not None
        payload = json.loads(notification_message.content)
        assert payload["kind"] == "delegation_result"
        assert payload["status"] == DelegationStatus.AWAITING_APPROVAL.value
        assert payload["delegation_id"] == delegation_result.delegation_id
        assert payload["child_agent_id"] == "deploy-agent"

        # NO delegation_result run should exist yet.
        delegation_result_run = jobs.get_execution_run_by_trigger(
            db,
            trigger_kind="delegation_result",
            trigger_ref=delegation_result.delegation_id,
        )
        assert delegation_result_run is None

        # The delegation lifecycle event must be recorded.
        events = delegation_service.repository.list_events(
            db, delegation_id=delegation_result.delegation_id
        )
        assert any(e.event_kind == "awaiting_approval" for e in events)


# ---------------------------------------------------------------------------
# Test 2: awaiting_approval delegation is counted as active
# ---------------------------------------------------------------------------


def test_awaiting_approval_delegation_counts_as_active(session_manager) -> None:
    settings = _settings(str(session_manager.engine.url))
    app = create_app(settings=settings, session_manager=session_manager)
    repository = SessionRepository()
    jobs = JobsRepository()
    delegation_service = app.state.delegation_service

    with session_manager.session() as db:
        parent_session = repository.get_or_create_session(
            db,
            normalize_routing_input(
                RoutingInput(
                    channel_kind="webchat",
                    channel_account_id="acct",
                    sender_id="user-2",
                    peer_id="user-2",
                )
            ),
            owner_agent_id="default-agent",
        )
        message = repository.append_message(
            db, parent_session,
            role=MessageRole.USER.value,
            content="deploy",
            external_message_id="approval-cont-test2",
            sender_id="user-2",
            last_activity_at=datetime.now(timezone.utc),
        )
        parent_run = jobs.create_or_get_execution_run(
            db,
            session_id=parent_session.id,
            message_id=message.id,
            agent_id="default-agent",
            trigger_kind="inbound_message",
            trigger_ref=f"test2-{message.id}",
            lane_key=parent_session.id,
            max_attempts=2,
        )
        delegation_result = delegation_service.create_delegation(
            db,
            policy_service=PolicyService(
                allowed_capabilities={"echo_text", "delegate_to_agent", "remote_exec"},
                delegation_enabled=True,
                max_delegation_depth=2,
                allowed_child_agent_ids={"deploy-agent"},
                remote_execution_enabled=True,
            ),
            parent_session_id=parent_session.id,
            parent_message_id=message.id,
            parent_run_id=parent_run.id,
            parent_agent_id="default-agent",
            parent_policy_profile_key="default",
            parent_tool_profile_key="default",
            correlation_id="tool-call-test2",
            child_agent_id="deploy-agent",
            task_text="deploy task",
            delegation_kind="deployment",
        )
        delegation_service.mark_child_run_running(db, child_run_id=delegation_result.child_run_id)
        delegation_service.handle_child_run_paused_for_approval(
            db, child_run_id=delegation_result.child_run_id
        )
        db.commit()

    with session_manager.session() as db:
        # An awaiting_approval delegation still counts as active for the
        # parent session — the workflow is not done.
        count = delegation_service.repository.count_active_for_parent_session(
            db, parent_session_id=parent_session.id
        )
        assert count == 1

        delegation = delegation_service.repository.get_delegation(
            db, delegation_id=delegation_result.delegation_id
        )
        assert delegation.status == DelegationStatus.AWAITING_APPROVAL.value


# ---------------------------------------------------------------------------
# Test 3: full lifecycle — paused → approved → resumed → completed, no collision
# ---------------------------------------------------------------------------


def test_approval_continuation_completes_without_deduplication_collision(session_manager) -> None:
    """
    The critical regression test.

    Before the architecture change, the second call to handle_child_run_completed
    (after the continuation run succeeded) would find the already-completed first
    parent result run via (trigger_kind="delegation_result", trigger_ref=delegation.id)
    and return it, leaving the parent session without a new queued run.

    With the new architecture, the first child-run completion calls
    handle_child_run_paused_for_approval, which creates a run with
    trigger_kind="delegation_approval_prompt" — a different trigger_kind.
    handle_child_run_completed is only called once (for the successful second run),
    so (trigger_kind="delegation_result", trigger_ref=delegation.id) is only ever
    created once and there is no collision.
    """
    settings = _settings(str(session_manager.engine.url))
    app = create_app(settings=settings, session_manager=session_manager)
    repository = SessionRepository()
    jobs = JobsRepository()
    delegation_service = app.state.delegation_service
    approval_decision_service = create_approval_decision_service(settings)

    # -----------------------------------------------------------------------
    # Phase 1: set up parent session and delegation
    # -----------------------------------------------------------------------
    with session_manager.session() as db:
        parent_session = repository.get_or_create_session(
            db,
            normalize_routing_input(
                RoutingInput(
                    channel_kind="webchat",
                    channel_account_id="acct",
                    sender_id="user-3",
                    peer_id="user-3",
                )
            ),
            owner_agent_id="default-agent",
        )
        message = repository.append_message(
            db, parent_session,
            role=MessageRole.USER.value,
            content="Deploy northwind-api to staging.",
            external_message_id="approval-cont-test3",
            sender_id="user-3",
            last_activity_at=datetime.now(timezone.utc),
        )
        parent_run = jobs.create_or_get_execution_run(
            db,
            session_id=parent_session.id,
            message_id=message.id,
            agent_id="default-agent",
            trigger_kind="inbound_message",
            trigger_ref=f"test3-{message.id}",
            lane_key=parent_session.id,
            max_attempts=2,
        )
        delegation_result = delegation_service.create_delegation(
            db,
            policy_service=PolicyService(
                allowed_capabilities={"echo_text", "delegate_to_agent", "remote_exec"},
                delegation_enabled=True,
                max_delegation_depth=2,
                allowed_child_agent_ids={"deploy-agent"},
                remote_execution_enabled=True,
            ),
            parent_session_id=parent_session.id,
            parent_message_id=message.id,
            parent_run_id=parent_run.id,
            parent_agent_id="default-agent",
            parent_policy_profile_key="default",
            parent_tool_profile_key="default",
            correlation_id="tool-call-test3",
            child_agent_id="deploy-agent",
            task_text="POST to the webhook with curl.",
            delegation_kind="deployment",
        )
        delegation_service.mark_child_run_running(db, child_run_id=delegation_result.child_run_id)
        db.commit()

    first_child_run_id = delegation_result.child_run_id

    # -----------------------------------------------------------------------
    # Phase 2: child run proposes remote_exec (awaiting_approval)
    # -----------------------------------------------------------------------
    with session_manager.session() as db:
        child_session = repository.get_session(db, delegation_result.child_session_id)
        repository.append_message(
            db, child_session,
            role=MessageRole.ASSISTANT.value,
            content="Approval required for remote_exec.",
            external_message_id=None,
            sender_id="deploy-agent",
            last_activity_at=datetime.now(timezone.utc),
        )

        # Create a governance proposal (the child LLM proposed remote_exec).
        proposal, _version = repository.create_governance_proposal(
            db,
            session_id=delegation_result.child_session_id,
            message_id=repository.get_session(db, delegation_result.child_session_id).id,
            agent_id="deploy-agent",
            requested_by="system",
            capability_name="remote_exec",
            arguments={
                "executable": "/usr/bin/curl",
                "args": ["-X", "POST", "http://localhost/deploy"],
            },
            tool_schema_name="remote_exec.invocation",
            tool_schema_version="1.0",
        )

        # The jobs service calls this instead of handle_child_run_completed
        # because state.awaiting_approval=True.
        delegation_service.handle_child_run_paused_for_approval(
            db, child_run_id=first_child_run_id
        )
        db.commit()

    # Delegation must be awaiting_approval — NOT completed.
    with session_manager.session() as db:
        delegation = delegation_service.repository.get_delegation(
            db, delegation_id=delegation_result.delegation_id
        )
        assert delegation.status == DelegationStatus.AWAITING_APPROVAL.value

        # No delegation_result run should exist yet.
        assert jobs.get_execution_run_by_trigger(
            db,
            trigger_kind="delegation_result",
            trigger_ref=delegation_result.delegation_id,
        ) is None

    # -----------------------------------------------------------------------
    # Phase 3: user approves → _enqueue_approved_continuation queues a new
    #           child continuation run
    # -----------------------------------------------------------------------
    with session_manager.session() as db:
        approval_outcome = approval_decision_service.decide(
            db,
            session_id=delegation_result.child_session_id,
            message_id=None,
            actor_id="user-3",
            decision="approve",
            proposal_id=proposal.id,
            token=None,
            decided_via="text_command",
        )
        db.commit()

    assert approval_outcome.continuation_enqueued is True
    continuation_run_id = approval_outcome.continuation_run_id
    assert continuation_run_id is not None

    with session_manager.session() as db:
        delegation = delegation_service.repository.get_delegation(
            db, delegation_id=delegation_result.delegation_id
        )
        # Delegation is now QUEUED again (continuation run queued).
        assert delegation.status == DelegationStatus.QUEUED.value
        assert delegation.child_run_id == continuation_run_id

    # -----------------------------------------------------------------------
    # Phase 4: continuation run executes successfully
    # -----------------------------------------------------------------------
    with session_manager.session() as db:
        delegation_service.mark_child_run_running(db, child_run_id=continuation_run_id)

        child_session = repository.get_session(db, delegation_result.child_session_id)
        repository.append_message(
            db, child_session,
            role=MessageRole.ASSISTANT.value,
            content="Deployment curl command executed successfully.",
            external_message_id=None,
            sender_id="deploy-agent",
            last_activity_at=datetime.now(timezone.utc),
        )

        # handle_child_run_completed is called for the FIRST (and only) time.
        payload = delegation_service.handle_child_run_completed(
            db, child_run_id=continuation_run_id
        )
        db.commit()

    assert payload is not None
    assert "successfully" in payload.summary_text

    # -----------------------------------------------------------------------
    # Phase 5: verify final state — delegation completed, parent result queued
    # -----------------------------------------------------------------------
    with session_manager.session() as db:
        delegation = delegation_service.repository.get_delegation(
            db, delegation_id=delegation_result.delegation_id
        )
        assert delegation.status == DelegationStatus.COMPLETED.value

        # The parent result run must be freshly queued (not an old completed run).
        parent_result_run = jobs.get_execution_run(db, delegation.parent_result_run_id)
        assert parent_result_run is not None
        assert parent_result_run.session_id == parent_session.id
        assert parent_result_run.trigger_kind == "delegation_result"
        assert parent_result_run.trigger_ref == delegation_result.delegation_id
        assert parent_result_run.status == "queued"

        # The approval-prompt notification run is a separate run.
        notification_run = jobs.get_execution_run_by_trigger(
            db,
            trigger_kind="delegation_approval_prompt",
            trigger_ref=f"{delegation_result.delegation_id}:{first_child_run_id}",
        )
        assert notification_run is not None
        assert notification_run.id != parent_result_run.id

        # There are exactly two delegation-related parent runs:
        # one notification prompt and one final result.
        parent_delegation_runs = [
            run
            for run in jobs.list_session_runs(db, session_id=parent_session.id, limit=20)
            if run.trigger_kind in ("delegation_approval_prompt", "delegation_result")
        ]
        assert len(parent_delegation_runs) == 2
        trigger_kinds = {run.trigger_kind for run in parent_delegation_runs}
        assert trigger_kinds == {"delegation_approval_prompt", "delegation_result"}
