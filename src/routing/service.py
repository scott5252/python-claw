from __future__ import annotations

from dataclasses import dataclass


class RoutingValidationError(ValueError):
    pass


@dataclass(frozen=True)
class RoutingInput:
    channel_kind: str
    channel_account_id: str
    sender_id: str
    peer_id: str | None = None
    group_id: str | None = None


@dataclass(frozen=True)
class RoutingResult:
    channel_kind: str
    channel_account_id: str
    sender_id: str
    peer_id: str | None
    group_id: str | None
    scope_kind: str
    scope_name: str
    session_key: str


def _trim_required(value: str, field_name: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise RoutingValidationError(f"{field_name} must not be empty after trimming")
    return trimmed


def normalize_routing_input(raw: RoutingInput) -> RoutingResult:
    channel_kind = _trim_required(raw.channel_kind, "channel_kind")
    if channel_kind != channel_kind.lower():
        raise RoutingValidationError("channel_kind must be lowercase")

    channel_account_id = _trim_required(raw.channel_account_id, "channel_account_id")
    sender_id = _trim_required(raw.sender_id, "sender_id")

    peer_id = raw.peer_id.strip() if raw.peer_id is not None else None
    group_id = raw.group_id.strip() if raw.group_id is not None else None

    if peer_id == "":
        raise RoutingValidationError("peer_id must not be empty after trimming")
    if group_id == "":
        raise RoutingValidationError("group_id must not be empty after trimming")
    if (peer_id is None) == (group_id is None):
        raise RoutingValidationError("exactly one of peer_id or group_id is required")

    if peer_id is not None:
        return RoutingResult(
            channel_kind=channel_kind,
            channel_account_id=channel_account_id,
            sender_id=sender_id,
            peer_id=peer_id,
            group_id=None,
            scope_kind="direct",
            scope_name="main",
            session_key=f"{channel_kind}:{channel_account_id}:direct:{peer_id}:main",
        )

    return RoutingResult(
        channel_kind=channel_kind,
        channel_account_id=channel_account_id,
        sender_id=sender_id,
        peer_id=None,
        group_id=group_id,
        scope_kind="group",
        scope_name=group_id,
        session_key=f"{channel_kind}:{channel_account_id}:group:{group_id}",
    )
