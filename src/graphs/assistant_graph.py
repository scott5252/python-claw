from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.agents.service import AgentExecutionBinding, ResolvedModelProfile
from src.config.settings import PolicyProfileConfig, ToolProfileConfig
from src.graphs.nodes import GraphDependencies, assemble_state, execute_turn_with_options, persist_final_state
from src.graphs.state import AssistantState


@dataclass
class AssistantGraph:
    dependencies: GraphDependencies

    def invoke(
        self,
        *,
        db: Session,
        session_id: str,
        message_id: int,
        agent_id: str,
        channel_kind: str,
        sender_id: str,
        user_text: str,
        execution_binding: AgentExecutionBinding | None = None,
        execution_run_id: str | None = None,
        persist_final_message: bool = True,
    ) -> AssistantState:
        resolved_binding = execution_binding or AgentExecutionBinding(
            agent_id=agent_id,
            session_kind="primary",
            model_profile_key="default",
            policy_profile_key="default",
            tool_profile_key="default",
            model=ResolvedModelProfile(
                profile_key="default",
                runtime_mode="rule_based",
                provider=None,
                model_name="rule-based-adapter",
                temperature=None,
                max_output_tokens=None,
                timeout_seconds=30,
                tool_call_mode="auto",
                streaming_enabled=True,
                base_url=None,
            ),
            policy_profile=PolicyProfileConfig(key="default"),
            tool_profile=ToolProfileConfig(
                key="default",
                allowed_capability_names=["echo_text", "remote_exec", "send_message"],
            ),
            allowed_capabilities=set(),
        )
        state = assemble_state(
            db=db,
            dependencies=self.dependencies,
            session_id=session_id,
            message_id=message_id,
            agent_id=agent_id,
            channel_kind=channel_kind,
            sender_id=sender_id,
            user_text=user_text,
            execution_binding=resolved_binding,
        )
        if execution_run_id is not None:
            state.context_manifest["execution_run_id"] = execution_run_id
        return execute_turn_with_options(
            db=db,
            state=state,
            dependencies=self.dependencies,
            persist_final_message=persist_final_message,
        )

    def persist_final_state(self, *, db: Session, state: AssistantState) -> AssistantState:
        return persist_final_state(db=db, state=state, dependencies=self.dependencies)


@dataclass
class GraphFactory:
    dependencies: GraphDependencies

    def build(self) -> AssistantGraph:
        return AssistantGraph(dependencies=self.dependencies)
