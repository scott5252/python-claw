from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

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
        execution_run_id: str | None = None,
        persist_final_message: bool = True,
    ) -> AssistantState:
        state = assemble_state(
            db=db,
            dependencies=self.dependencies,
            session_id=session_id,
            message_id=message_id,
            agent_id=agent_id,
            channel_kind=channel_kind,
            sender_id=sender_id,
            user_text=user_text,
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
