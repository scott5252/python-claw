from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from src.agents.service import AgentProfileService
from src.config.settings import Settings
from src.db.models import DelegationStatus, ExecutionRunStatus, SessionKind
from src.delegations.repository import DelegationRepository
from src.domain.schemas import DelegationResultPayload
from src.jobs.repository import JobsRepository
from src.policies.service import PolicyService
from src.sessions.repository import SessionRepository
from src.sessions.collaboration import SessionCollaborationService


@dataclass
class DelegationCreateResult:
    delegation_id: str
    child_session_id: str
    child_run_id: str
    status: str
    child_agent_id: str


@dataclass
class DelegationService:
    repository: DelegationRepository
    session_repository: SessionRepository
    jobs_repository: JobsRepository
    agent_profile_service: AgentProfileService
    settings: Settings
    collaboration_service: SessionCollaborationService | None = None

    def create_delegation(
        self,
        db: Session,
        *,
        policy_service: PolicyService,
        parent_session_id: str,
        parent_message_id: int,
        parent_run_id: str,
        parent_agent_id: str,
        parent_policy_profile_key: str,
        parent_tool_profile_key: str,
        correlation_id: str,
        child_agent_id: str,
        task_text: str,
        delegation_kind: str,
        expected_output: str | None = None,
        notes: str | None = None,
    ) -> DelegationCreateResult:
        existing = self.repository.get_by_parent_correlation(
            db,
            parent_run_id=parent_run_id,
            correlation_id=correlation_id,
        )
        if existing is not None:
            return DelegationCreateResult(
                delegation_id=existing.id,
                child_session_id=existing.child_session_id,
                child_run_id=existing.child_run_id,
                status=existing.status,
                child_agent_id=existing.child_agent_id,
            )
        parent_session = self.session_repository.get_session(db, parent_session_id)
        if parent_session is None:
            raise RuntimeError("parent session not found")
        if parent_session.owner_agent_id != parent_agent_id:
            raise PermissionError("parent agent does not own session")

        parent_policy = self.settings.get_policy_profile(parent_policy_profile_key)
        if not policy_service.is_tool_visible(
            context=self._tool_context_stub(parent_session_id, parent_message_id, parent_agent_id),
            capability_name="delegate_to_agent",
        ):
            raise PermissionError("delegation tool not available in runtime context")
        if not parent_policy.delegation_enabled:
            raise PermissionError("delegation is disabled for this policy profile")
        if child_agent_id not in set(parent_policy.allowed_child_agent_ids):
            raise PermissionError("requested child agent is not allowlisted")
        child_binding = self.agent_profile_service.resolve_binding_for_agent(
            db,
            agent_id=child_agent_id,
            session_kind=SessionKind.CHILD.value,
        )
        _ = self.settings.get_tool_profile(parent_tool_profile_key)

        parent_delegation = self.repository.get_by_child_session(db, child_session_id=parent_session_id)
        depth = 1 if parent_delegation is None else parent_delegation.depth + 1
        if depth > parent_policy.max_delegation_depth:
            raise PermissionError("delegation depth exceeds configured maximum")
        if (
            parent_policy.max_active_delegations_per_run is not None
            and self.repository.count_active_for_parent_run(db, parent_run_id=parent_run_id)
            >= parent_policy.max_active_delegations_per_run
        ):
            raise PermissionError("active delegation limit reached for run")
        if (
            parent_policy.max_active_delegations_per_session is not None
            and self.repository.count_active_for_parent_session(db, parent_session_id=parent_session_id)
            >= parent_policy.max_active_delegations_per_session
        ):
            raise PermissionError("active delegation limit reached for session")

        delegation_id = str(uuid4())
        context_payload, child_content = self._build_context_package(
            db,
            parent_session_id=parent_session_id,
            parent_message_id=parent_message_id,
            parent_run_id=parent_run_id,
            parent_agent_id=parent_agent_id,
            child_agent_id=child_agent_id,
            depth=depth,
            delegation_kind=delegation_kind,
            task_text=task_text,
            expected_output=expected_output,
            notes=notes,
        )
        child_session = self.session_repository.create_child_session(
            db,
            parent_session=parent_session,
            delegation_id=delegation_id,
            child_agent_id=child_agent_id,
        )
        child_message = self.session_repository.append_message(
            db,
            child_session,
            role="system",
            content=child_content,
            external_message_id=None,
            sender_id=f"system:delegation:{parent_agent_id}",
            last_activity_at=child_session.last_activity_at,
        )
        child_run = self.jobs_repository.create_or_get_execution_run(
            db,
            session_id=child_session.id,
            message_id=child_message.id,
            agent_id=child_binding.agent_id,
            model_profile_key=child_binding.model_profile_key,
            policy_profile_key=child_binding.policy_profile_key,
            tool_profile_key=child_binding.tool_profile_key,
            trigger_kind="delegation_child",
            trigger_ref=delegation_id,
            lane_key=child_session.id,
            max_attempts=self.settings.execution_run_max_attempts,
        )
        record = self.repository.create_delegation(
            db,
            delegation_id=delegation_id,
            parent_session_id=parent_session_id,
            parent_message_id=parent_message_id,
            parent_run_id=parent_run_id,
            parent_tool_call_correlation_id=correlation_id,
            parent_agent_id=parent_agent_id,
            child_session_id=child_session.id,
            child_message_id=child_message.id,
            child_run_id=child_run.id,
            child_agent_id=child_agent_id,
            status=DelegationStatus.QUEUED.value,
            depth=depth,
            delegation_kind=delegation_kind,
            task_text=task_text,
            context_payload=context_payload,
        )
        self.repository.append_event(
            db,
            delegation_id=record.id,
            event_kind="queued",
            status=record.status,
            actor_kind="parent_run",
            actor_ref=parent_run_id,
            payload={"child_run_id": child_run.id, "child_session_id": child_session.id},
        )
        return DelegationCreateResult(
            delegation_id=record.id,
            child_session_id=record.child_session_id,
            child_run_id=record.child_run_id,
            status=record.status,
            child_agent_id=record.child_agent_id,
        )

    def mark_child_run_running(self, db: Session, *, child_run_id: str) -> None:
        delegation = self.repository.get_by_child_run(db, child_run_id=child_run_id)
        if delegation is None or delegation.status == DelegationStatus.CANCELLED.value:
            return
        self.repository.mark_running(db, delegation_id=delegation.id)
        self.repository.append_event(
            db,
            delegation_id=delegation.id,
            event_kind="started",
            status=DelegationStatus.RUNNING.value,
            actor_kind="child_run",
            actor_ref=child_run_id,
        )

    def handle_child_run_retry(self, db: Session, *, child_run_id: str, error: str, terminal: bool) -> None:
        delegation = self.repository.get_by_child_run(db, child_run_id=child_run_id)
        if delegation is None:
            return
        if terminal:
            self.repository.mark_failed(db, delegation_id=delegation.id, failure_detail=error)
            self.repository.append_event(
                db,
                delegation_id=delegation.id,
                event_kind="failed",
                status=DelegationStatus.FAILED.value,
                actor_kind="child_run",
                actor_ref=child_run_id,
                payload={"error": error},
            )
            return
        self.repository.append_event(
            db,
            delegation_id=delegation.id,
            event_kind="retry_scheduled",
            status=delegation.status,
            actor_kind="child_run",
            actor_ref=child_run_id,
            payload={"error": error},
        )

    def handle_child_run_completed(self, db: Session, *, child_run_id: str) -> DelegationResultPayload | None:
        delegation = self.repository.get_by_child_run(db, child_run_id=child_run_id)
        if delegation is None or delegation.status == DelegationStatus.CANCELLED.value:
            return None
        payload = self.build_result_payload(db, delegation_id=delegation.id)
        parent_session = self.session_repository.get_session(db, delegation.parent_session_id)
        if parent_session is None:
            raise RuntimeError("parent session missing")
        parent_binding = self.agent_profile_service.resolve_binding_for_session(db, session=parent_session)
        content = json.dumps(
            {
                "kind": "delegation_result",
                "delegation_id": payload.delegation_id,
                "child_agent_id": payload.child_agent_id,
                "status": payload.status,
                "summary_text": payload.summary_text,
                "pending_approvals": payload.pending_approvals,
            },
            sort_keys=True,
        )
        message = self.repository.create_or_get_parent_result_message(
            db,
            delegation=delegation,
            sender_id=f"system:delegation_result:{delegation.child_agent_id}",
            content=content,
        )
        run = self.repository.create_or_get_parent_result_run(
            db,
            delegation=delegation,
            parent_result_message_id=message.id,
            agent_id=parent_binding.agent_id,
            model_profile_key=parent_binding.model_profile_key,
            policy_profile_key=parent_binding.policy_profile_key,
            tool_profile_key=parent_binding.tool_profile_key,
            max_attempts=self.settings.execution_run_max_attempts,
            status=(
                "blocked"
                if self.collaboration_service is not None
                and self.collaboration_service.should_block_new_automation(session=parent_session)
                else "queued"
            ),
            blocked_reason=(
                None
                if self.collaboration_service is None
                else self.collaboration_service.blocked_reason_for_session(session=parent_session)
            ),
        )
        self.repository.mark_completed(
            db,
            delegation_id=delegation.id,
            result_payload=payload.model_dump(mode="json"),
            parent_result_message_id=message.id,
            parent_result_run_id=run.id,
        )
        self.repository.append_event(
            db,
            delegation_id=delegation.id,
            event_kind="completed",
            status=DelegationStatus.COMPLETED.value,
            actor_kind="child_run",
            actor_ref=child_run_id,
            payload={"parent_result_run_id": run.id},
        )
        return payload

    def handle_child_run_paused_for_approval(self, db: Session, *, child_run_id: str) -> None:
        """Called when a child run completes but is waiting for human approval.

        Marks the delegation as awaiting_approval and queues a lightweight notification
        run on the parent session so the user sees the pending approval prompt.
        Unlike handle_child_run_completed, this does NOT mark the delegation as
        completed or create a delegation_result run — the lifecycle continues after
        the user approves and the continuation run finishes.
        """
        delegation = self.repository.get_by_child_run(db, child_run_id=child_run_id)
        if delegation is None or delegation.status == DelegationStatus.CANCELLED.value:
            return

        pending_approvals = [
            self._json_safe_value(item)
            for item in self.session_repository.list_pending_approvals(db, session_id=delegation.child_session_id)
        ]

        parent_session = self.session_repository.get_session(db, delegation.parent_session_id)
        if parent_session is None:
            raise RuntimeError("parent session missing")
        parent_binding = self.agent_profile_service.resolve_binding_for_session(db, session=parent_session)

        content = json.dumps(
            {
                "kind": "delegation_result",
                "delegation_id": delegation.id,
                "child_agent_id": delegation.child_agent_id,
                "status": DelegationStatus.AWAITING_APPROVAL.value,
                "summary_text": "",
                "pending_approvals": pending_approvals,
            },
            sort_keys=True,
        )
        notification_message = self.session_repository.append_message(
            db,
            parent_session,
            role="system",
            content=content,
            external_message_id=None,
            sender_id=f"system:delegation_approval:{delegation.child_agent_id}",
            last_activity_at=datetime.now(timezone.utc),
        )

        run_status = (
            "blocked"
            if self.collaboration_service is not None
            and self.collaboration_service.should_block_new_automation(session=parent_session)
            else "queued"
        )
        blocked_reason = (
            None
            if self.collaboration_service is None
            else self.collaboration_service.blocked_reason_for_session(session=parent_session)
        )
        notification_run = self.jobs_repository.create_or_get_execution_run(
            db,
            session_id=delegation.parent_session_id,
            message_id=notification_message.id,
            agent_id=parent_binding.agent_id,
            model_profile_key=parent_binding.model_profile_key,
            policy_profile_key=parent_binding.policy_profile_key,
            tool_profile_key=parent_binding.tool_profile_key,
            trigger_kind="delegation_approval_prompt",
            trigger_ref=f"{delegation.id}:{child_run_id}",
            lane_key=delegation.parent_session_id,
            max_attempts=self.settings.execution_run_max_attempts,
            status=run_status,
            blocked_reason=blocked_reason,
        )

        self.repository.mark_awaiting_approval(db, delegation_id=delegation.id)
        self.repository.append_event(
            db,
            delegation_id=delegation.id,
            event_kind="awaiting_approval",
            status=DelegationStatus.AWAITING_APPROVAL.value,
            actor_kind="child_run",
            actor_ref=child_run_id,
            payload={
                "pending_approval_count": len(pending_approvals),
                "notification_run_id": notification_run.id,
                "notification_message_id": notification_message.id,
            },
        )

    def cancel_delegation(self, db: Session, *, delegation_id: str, cancel_reason: str) -> None:
        delegation = self.repository.get_delegation(db, delegation_id=delegation_id)
        if delegation is None or delegation.status == DelegationStatus.CANCELLED.value:
            return
        self.repository.mark_cancelled(db, delegation_id=delegation_id, cancel_reason=cancel_reason)
        child_run = self.jobs_repository.get_execution_run(db, delegation.child_run_id)
        if child_run is not None and child_run.status in {
            ExecutionRunStatus.QUEUED.value,
            ExecutionRunStatus.RETRY_WAIT.value,
            ExecutionRunStatus.CLAIMED.value,
        }:
            child_run.status = ExecutionRunStatus.CANCELLED.value
        self.repository.append_event(
            db,
            delegation_id=delegation_id,
            event_kind="cancelled",
            status=DelegationStatus.CANCELLED.value,
            actor_kind="system",
            payload={"reason": cancel_reason},
        )

    def build_result_payload(self, db: Session, *, delegation_id: str) -> DelegationResultPayload:
        delegation = self.repository.get_delegation(db, delegation_id=delegation_id)
        if delegation is None:
            raise RuntimeError("delegation not found")
        messages = self.session_repository.list_messages(
            db,
            session_id=delegation.child_session_id,
            limit=100,
            before_message_id=None,
        )
        artifacts = self.session_repository.list_artifacts(db, session_id=delegation.child_session_id)
        assistant_messages = [message for message in messages if message.role == "assistant"]
        pending_approvals = [
            self._json_safe_value(item)
            for item in self.session_repository.list_pending_approvals(db, session_id=delegation.child_session_id)
        ]
        summary_text = ""
        if assistant_messages:
            summary_text = assistant_messages[-1].content.strip()
        elif artifacts:
            last = artifacts[-1]
            summary_text = f"Child completed with artifact `{last.artifact_kind}`."
        elif delegation.failure_detail:
            summary_text = delegation.failure_detail
        else:
            summary_text = "Child run completed without a final assistant message."
        if len(summary_text) > self.settings.delegation_package_max_chars:
            summary_text = summary_text[: self.settings.delegation_package_max_chars - 3] + "..."
        return DelegationResultPayload(
            delegation_id=delegation.id,
            child_session_id=delegation.child_session_id,
            child_run_id=delegation.child_run_id,
            child_agent_id=delegation.child_agent_id,
            status=delegation.status if delegation.status != DelegationStatus.QUEUED.value else "completed",
            summary_text=summary_text,
            pending_approvals=pending_approvals,
            tool_event_count=len([item for item in artifacts if item.artifact_kind == "tool_result"]),
            outbound_intent_count=len([item for item in artifacts if item.artifact_kind == "outbound_intent"]),
            error=delegation.failure_detail,
        )

    def _json_safe_value(self, value):
        if isinstance(value, datetime):
            return value.isoformat().replace("+00:00", "Z")
        if isinstance(value, dict):
            return {key: self._json_safe_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._json_safe_value(item) for item in value]
        return value

    def _build_context_package(
        self,
        db: Session,
        *,
        parent_session_id: str,
        parent_message_id: int,
        parent_run_id: str,
        parent_agent_id: str,
        child_agent_id: str,
        depth: int,
        delegation_kind: str,
        task_text: str,
        expected_output: str | None,
        notes: str | None,
        ) -> tuple[dict[str, object], str]:
        summary = self.session_repository.get_latest_summary_snapshot_for_session(db, session_id=parent_session_id)
        transcript = self.session_repository.list_messages(
            db,
            session_id=parent_session_id,
            limit=self.settings.delegation_package_transcript_turns,
            before_message_id=None,
        )
        payload: dict[str, object] = {
            "parent_session_id": parent_session_id,
            "parent_message_id": parent_message_id,
            "parent_run_id": parent_run_id,
            "parent_agent_id": parent_agent_id,
            "child_agent_id": child_agent_id,
            "depth": depth,
            "delegation_kind": delegation_kind,
            "task_text": task_text.strip(),
            "expected_output": expected_output.strip() if expected_output else None,
            "notes": notes.strip() if notes else None,
            "summary_text": None if summary is None else summary.summary_text,
            "recent_transcript": [
                {"role": row.role, "sender_id": row.sender_id, "content": row.content}
                for row in transcript
            ],
        }
        content = self._build_child_instruction(
            parent_agent_id=parent_agent_id,
            child_agent_id=child_agent_id,
            delegation_kind=delegation_kind,
            task_text=task_text,
            expected_output=expected_output,
            notes=notes,
            transcript=[
                {"role": row.role, "sender_id": row.sender_id, "content": row.content}
                for row in transcript
            ],
            summary_text=None if summary is None else summary.summary_text,
        )
        if len(content) > self.settings.delegation_package_max_chars:
            payload["recent_transcript"] = payload["recent_transcript"][-max(1, self.settings.delegation_package_transcript_turns // 2) :]
            content = self._build_child_instruction(
                parent_agent_id=parent_agent_id,
                child_agent_id=child_agent_id,
                delegation_kind=delegation_kind,
                task_text=task_text,
                expected_output=expected_output,
                notes=notes,
                transcript=payload["recent_transcript"],
                summary_text=payload.get("summary_text"),
            )
            if len(content) > self.settings.delegation_package_max_chars:
                payload["summary_text"] = (payload.get("summary_text") or "")[: self.settings.delegation_package_max_chars // 3]
                content = self._build_child_instruction(
                    parent_agent_id=parent_agent_id,
                    child_agent_id=child_agent_id,
                    delegation_kind=delegation_kind,
                    task_text=task_text,
                    expected_output=expected_output,
                    notes=notes,
                    transcript=payload["recent_transcript"],
                    summary_text=payload.get("summary_text"),
                )[: self.settings.delegation_package_max_chars]
        return payload, content

    def _build_child_instruction(
        self,
        *,
        parent_agent_id: str,
        child_agent_id: str,
        delegation_kind: str,
        task_text: str,
        expected_output: str | None,
        notes: str | None,
        transcript: list[dict[str, object]],
        summary_text: str | None,
    ) -> str:
        lines = [
            f"You are `{child_agent_id}` handling a delegated `{delegation_kind}` task from `{parent_agent_id}`.",
            "",
            "Task:",
            task_text.strip(),
        ]
        if expected_output and expected_output.strip():
            lines.extend(["", "Expected output:", expected_output.strip()])
        if notes and notes.strip():
            lines.extend(["", "Notes:", notes.strip()])
        if summary_text and summary_text.strip():
            lines.extend(["", "Parent session summary:", summary_text.strip()])
        if transcript:
            lines.extend(["", "Recent parent transcript:"])
            for item in transcript:
                role = str(item.get("role") or "message")
                content = str(item.get("content") or "").strip()
                if content:
                    lines.append(f"- {role}: {content}")
        lines.extend(
            [
                "",
                "If an available tool can perform the requested action, use the tool instead of describing the action in prose.",
                "If the action requires approval, still emit the tool request so the backend can create the proposal.",
            ]
        )
        return "\n".join(lines)

    def _tool_context_stub(self, session_id: str, message_id: int, agent_id: str):
        from src.graphs.state import ToolRuntimeContext, ToolRuntimeServices

        return ToolRuntimeContext(
            session_id=session_id,
            message_id=message_id,
            agent_id=agent_id,
            channel_kind="internal",
            sender_id=agent_id,
            policy_context={},
            runtime_services=ToolRuntimeServices(),
        )
