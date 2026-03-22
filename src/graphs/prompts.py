from __future__ import annotations

from src.graphs.state import AssistantState


def render_prompt(state: AssistantState) -> str:
    lines = [f"{message.role}: {message.content}" for message in state.messages]
    lines.append(f"user: {state.user_text}")
    return "\n".join(lines)
