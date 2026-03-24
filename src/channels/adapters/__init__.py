from src.channels.adapters.base import ChannelAdapter, ChannelCapabilities, SendResult
from src.channels.adapters.slack import SlackAdapter
from src.channels.adapters.telegram import TelegramAdapter
from src.channels.adapters.webchat import WebchatAdapter

__all__ = [
    "ChannelAdapter",
    "ChannelCapabilities",
    "SendResult",
    "SlackAdapter",
    "TelegramAdapter",
    "WebchatAdapter",
]
