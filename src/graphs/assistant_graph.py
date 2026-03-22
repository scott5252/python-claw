from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.graphs.nodes import GraphDependencies, assemble_state, execute_turn
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
        return execute_turn(db=db, state=state, dependencies=self.dependencies)


@dataclass
class GraphFactory:
    dependencies: GraphDependencies

    def build(self) -> AssistantGraph:
        return AssistantGraph(dependencies=self.dependencies)
