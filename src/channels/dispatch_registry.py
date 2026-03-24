from __future__ import annotations

from src.channels.adapters import SlackAdapter, TelegramAdapter, WebchatAdapter
from src.channels.dispatch import OutboundDispatcher


def build_dispatcher() -> OutboundDispatcher:
    adapters = {
        "webchat": WebchatAdapter(),
        "slack": SlackAdapter(),
        "telegram": TelegramAdapter(),
    }
    return OutboundDispatcher(adapters=adapters)
