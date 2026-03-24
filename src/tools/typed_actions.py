from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TypedAction:
    typed_action_id: str
    capability_name: str
    description: str
    requires_approval: bool
    resource_kind: str = "tool"


TYPED_ACTIONS: dict[str, TypedAction] = {
    "echo_text": TypedAction(
        typed_action_id="tool.echo_text",
        capability_name="echo_text",
        description="Echo text back to the runtime.",
        requires_approval=False,
    ),
    "send_message": TypedAction(
        typed_action_id="tool.send_message",
        capability_name="send_message",
        description="Send an outbound message through the local messaging adapter.",
        requires_approval=True,
    ),
    "remote_exec": TypedAction(
        typed_action_id="tool.remote_exec",
        capability_name="remote_exec",
        description="Execute an approved remote node command template.",
        requires_approval=True,
        resource_kind="node_command_template",
    ),
}


def get_typed_action(capability_name: str) -> TypedAction | None:
    return TYPED_ACTIONS.get(capability_name)
