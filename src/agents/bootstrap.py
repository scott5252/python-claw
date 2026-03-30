from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.repository import AgentRepository
from src.agents.service import AgentProfileService
from src.capabilities.repository import CapabilitiesRepository
from src.config.settings import Settings
from src.db.models import AgentProfileRecord, ExecutionRunRecord, MessageRecord, ModelProfileRecord, ResourceProposalRecord, SessionKind, SessionRecord


DEFAULT_MODEL_PROFILE_KEY = "default"


def bootstrap_agent_profiles(db: Session, *, settings: Settings) -> None:
    repository = AgentRepository()
    model_profile = repository.get_model_profile_by_key(db, profile_key=DEFAULT_MODEL_PROFILE_KEY)
    if model_profile is None:
        model_profile = ModelProfileRecord(
            profile_key=DEFAULT_MODEL_PROFILE_KEY,
            runtime_mode=settings.runtime_mode,
            provider=settings.llm_provider if settings.runtime_mode == "provider" else None,
            model_name=settings.llm_model if settings.runtime_mode == "provider" else None,
            temperature=None if settings.llm_temperature is None else str(settings.llm_temperature),
            max_output_tokens=settings.llm_max_output_tokens,
            timeout_seconds=settings.llm_timeout_seconds,
            tool_call_mode=settings.llm_tool_call_mode,
            streaming_enabled=1 if settings.runtime_streaming_enabled else 0,
            enabled=1,
            base_url=settings.llm_base_url,
        )
        db.add(model_profile)
        db.flush()

    historical_agent_ids = {item for item in db.scalars(select(ExecutionRunRecord.agent_id).distinct()) if item}
    historical_agent_ids.update({item for item in db.scalars(select(SessionRecord.owner_agent_id).distinct()) if item})
    historical_agent_ids.add(settings.default_agent_id)
    historical_agent_ids.update(override.agent_id for override in settings.historical_agent_profile_overrides)

    for agent_id in sorted(historical_agent_ids):
        existing = repository.get_agent_profile(db, agent_id=agent_id)
        if existing is not None:
            continue
        override = settings.get_historical_agent_override(agent_id)
        resolved_model_key = DEFAULT_MODEL_PROFILE_KEY if override is None else override.model_profile_key
        resolved_model = repository.get_model_profile_by_key(db, profile_key=resolved_model_key)
        if resolved_model is None:
            raise RuntimeError(f"model profile not configured for seeded agent {agent_id}")
        db.add(
            AgentProfileRecord(
                agent_id=agent_id,
                display_name=agent_id,
                role_kind="assistant",
                default_model_profile_id=resolved_model.id,
                policy_profile_key="default" if override is None else override.policy_profile_key,
                tool_profile_key="default" if override is None else override.tool_profile_key,
                enabled=1,
            )
        )
    db.flush()

    bootstrap_service = AgentProfileService(repository=repository, settings=settings)
    binding = bootstrap_service.resolve_bootstrap_binding(db, session_kind=SessionKind.PRIMARY.value)
    if binding.agent_id != settings.default_agent_id:
        raise RuntimeError("bootstrap default agent binding mismatch")

    _bootstrap_remote_exec_templates(db, settings=settings)


def _bootstrap_remote_exec_templates(db: Session, *, settings: Settings) -> None:
    if not settings.remote_exec_agent_templates:
        return

    capabilities_repository = CapabilitiesRepository()

    for template in settings.remote_exec_agent_templates:
        session_key = f"__bootstrap_remote_exec__:{template.agent_id}"

        # Get or create bootstrap session for this agent
        bootstrap_session = db.scalar(select(SessionRecord).where(SessionRecord.session_key == session_key))
        if bootstrap_session is None:
            bootstrap_session = SessionRecord(
                session_key=session_key,
                channel_kind="system",
                channel_account_id="bootstrap",
                scope_kind="peer",
                peer_id=f"bootstrap:{template.agent_id}",
                group_id=None,
                scope_name="",
                owner_agent_id=template.agent_id,
                session_kind=SessionKind.SYSTEM.value,
            )
            db.add(bootstrap_session)
            db.flush()

        # Check if a NodeCommandTemplate already exists for this agent (approved, from bootstrap session)
        existing_proposal = db.scalar(
            select(ResourceProposalRecord).where(
                ResourceProposalRecord.session_id == bootstrap_session.id,
                ResourceProposalRecord.resource_kind == "node_command_template",
                ResourceProposalRecord.agent_id == template.agent_id,
            )
        )
        if existing_proposal is not None:
            continue

        # Create a bootstrap system message to satisfy the FK constraint on message_id
        bootstrap_message = MessageRecord(
            session_id=bootstrap_session.id,
            role="system",
            content="system:bootstrap node_command_template",
            external_message_id=None,
            sender_id="system:bootstrap",
        )
        db.add(bootstrap_message)
        db.flush()

        template_payload = {
            "executable": template.executable,
            "argv_template": template.argv_template,
            "env_allowlist": template.env_allowlist,
            "working_dir": template.working_dir,
            "workspace_binding_kind": template.workspace_binding_kind,
            "fixed_workspace_key": template.fixed_workspace_key,
            "workspace_mount_mode": template.workspace_mount_mode,
            "typed_action_id": "tool.remote_exec",
            "sandbox_profile_key": template.sandbox_profile_key,
            "timeout_seconds": template.timeout_seconds,
        }

        capabilities_repository.create_remote_exec_capability(
            db,
            session_id=bootstrap_session.id,
            message_id=bootstrap_message.id,
            agent_id=template.agent_id,
            requested_by="system:bootstrap",
            approver_id="system:bootstrap",
            template_payload=template_payload,
            invocation_arguments={},
        )
