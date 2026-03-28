from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from src.agents.repository import AgentRepository
from src.config.settings import PolicyProfileConfig, Settings, ToolProfileConfig
from src.db.models import SessionKind


@dataclass(frozen=True)
class ResolvedModelProfile:
    profile_key: str
    runtime_mode: str
    provider: str | None
    model_name: str | None
    temperature: float | None
    max_output_tokens: int | None
    timeout_seconds: int
    tool_call_mode: str
    streaming_enabled: bool
    base_url: str | None


@dataclass(frozen=True)
class AgentExecutionBinding:
    agent_id: str
    session_kind: str
    model_profile_key: str
    policy_profile_key: str
    tool_profile_key: str
    model: ResolvedModelProfile
    policy_profile: PolicyProfileConfig
    tool_profile: ToolProfileConfig
    allowed_capabilities: set[str] = field(default_factory=set)


class AgentProfileService:
    def __init__(self, *, repository: AgentRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    def resolve_bootstrap_agent_id(self) -> str:
        return self.settings.default_agent_id.strip()

    def resolve_binding_for_agent(
        self,
        db: Session,
        *,
        agent_id: str,
        session_kind: str = SessionKind.PRIMARY.value,
        model_profile_key: str | None = None,
        policy_profile_key: str | None = None,
        tool_profile_key: str | None = None,
    ) -> AgentExecutionBinding:
        profile = self.repository.get_agent_profile(db, agent_id=agent_id)
        if profile is None:
            raise RuntimeError(f"agent profile not found for {agent_id}")
        if profile.enabled != 1:
            raise RuntimeError(f"agent profile is disabled for {agent_id}")

        resolved_model = (
            self.repository.get_model_profile_by_key(db, profile_key=model_profile_key)
            if model_profile_key is not None
            else self.repository.get_model_profile(db, profile_id=profile.default_model_profile_id)
        )
        if resolved_model is None:
            raise RuntimeError(f"model profile not found for agent {agent_id}")
        if resolved_model.enabled != 1:
            raise RuntimeError(f"model profile is disabled for agent {agent_id}")

        resolved_policy_key = policy_profile_key or profile.policy_profile_key
        resolved_tool_key = tool_profile_key or profile.tool_profile_key
        policy_profile = self.settings.get_policy_profile(resolved_policy_key)
        tool_profile = self.settings.get_tool_profile(resolved_tool_key)

        temperature = None if resolved_model.temperature is None else float(resolved_model.temperature)
        return AgentExecutionBinding(
            agent_id=profile.agent_id,
            session_kind=session_kind,
            model_profile_key=resolved_model.profile_key,
            policy_profile_key=policy_profile.key,
            tool_profile_key=tool_profile.key,
            model=ResolvedModelProfile(
                profile_key=resolved_model.profile_key,
                runtime_mode=resolved_model.runtime_mode,
                provider=resolved_model.provider,
                model_name=resolved_model.model_name,
                temperature=temperature,
                max_output_tokens=resolved_model.max_output_tokens,
                timeout_seconds=resolved_model.timeout_seconds,
                tool_call_mode=resolved_model.tool_call_mode,
                streaming_enabled=resolved_model.streaming_enabled == 1,
                base_url=resolved_model.base_url,
            ),
            policy_profile=policy_profile,
            tool_profile=tool_profile,
            allowed_capabilities=set(tool_profile.allowed_capability_names),
        )

    def resolve_bootstrap_binding(self, db: Session, *, session_kind: str = SessionKind.PRIMARY.value) -> AgentExecutionBinding:
        return self.resolve_binding_for_agent(
            db,
            agent_id=self.resolve_bootstrap_agent_id(),
            session_kind=session_kind,
        )

    def resolve_binding_for_session(self, db: Session, *, session) -> AgentExecutionBinding:
        return self.resolve_binding_for_agent(
            db,
            agent_id=session.owner_agent_id,
            session_kind=session.session_kind,
        )

    def resolve_binding_for_run(self, db: Session, *, run, session) -> AgentExecutionBinding:
        return self.resolve_binding_for_agent(
            db,
            agent_id=run.agent_id,
            session_kind=session.session_kind,
            model_profile_key=run.model_profile_key,
            policy_profile_key=run.policy_profile_key,
            tool_profile_key=run.tool_profile_key,
        )
