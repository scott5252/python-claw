from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.repository import AgentRepository
from src.agents.service import AgentProfileService
from src.config.settings import Settings
from src.db.models import AgentProfileRecord, ExecutionRunRecord, ModelProfileRecord, SessionKind, SessionRecord


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
