import pytest

from src.routing.service import RoutingInput, RoutingValidationError, normalize_routing_input


def test_direct_routing_trims_identifiers_but_preserves_case() -> None:
    result = normalize_routing_input(
        RoutingInput(
            channel_kind="slack",
            channel_account_id="  Team-01  ",
            sender_id="  Alice  ",
            peer_id="  Peer ABC  ",
        )
    )

    assert result.channel_account_id == "Team-01"
    assert result.sender_id == "Alice"
    assert result.peer_id == "Peer ABC"
    assert result.scope_kind == "direct"
    assert result.scope_name == "main"
    assert result.session_key == "slack:Team-01:direct:Peer ABC:main"


def test_group_routing_uses_group_scope_name() -> None:
    result = normalize_routing_input(
        RoutingInput(
            channel_kind="telegram",
            channel_account_id="acct",
            sender_id="sender",
            group_id="Room-9",
        )
    )

    assert result.scope_kind == "group"
    assert result.scope_name == "Room-9"
    assert result.session_key == "telegram:acct:group:Room-9"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"peer_id": "peer", "group_id": "group"},
        {},
        {"peer_id": "   "},
        {"group_id": "   "},
    ],
)
def test_invalid_routing_tuples_are_rejected(kwargs: dict[str, str]) -> None:
    with pytest.raises(RoutingValidationError):
        normalize_routing_input(
            RoutingInput(
                channel_kind="web",
                channel_account_id="acct",
                sender_id="sender",
                **kwargs,
            )
        )


def test_channel_kind_must_be_lowercase() -> None:
    with pytest.raises(RoutingValidationError):
        normalize_routing_input(
            RoutingInput(
                channel_kind="Slack",
                channel_account_id="acct",
                sender_id="sender",
                peer_id="peer",
            )
        )
