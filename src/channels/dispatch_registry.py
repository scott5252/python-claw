from __future__ import annotations

from src.channels.adapters import SlackAdapter, TelegramAdapter, WebchatAdapter
from src.channels.dispatch import OutboundDispatcher
from src.config.settings import Settings


def build_dispatcher(settings: Settings) -> OutboundDispatcher:
    adapters = {
        "webchat": WebchatAdapter(),
        "slack": SlackAdapter(),
        "telegram": TelegramAdapter(),
    }
    return OutboundDispatcher(adapters=adapters, settings=settings)
