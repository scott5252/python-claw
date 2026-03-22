from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class InboundMessageRequest(BaseModel):
    channel_kind: str
    channel_account_id: str
    external_message_id: str
    sender_id: str
    content: str
    peer_id: str | None = None
    group_id: str | None = None

class InboundMessageResponse(BaseModel):
    session_id: str
    message_id: int
    dedupe_status: Literal["accepted", "duplicate"]


class SessionResponse(BaseModel):
    id: str
    session_key: str
    channel_kind: str
    channel_account_id: str
    scope_kind: str
    peer_id: str | None
    group_id: str | None
    scope_name: str
    created_at: datetime
    last_activity_at: datetime


class MessageResponse(BaseModel):
    id: int
    session_id: str
    role: str
    content: str
    external_message_id: str | None
    sender_id: str
    created_at: datetime


class MessagePageResponse(BaseModel):
    items: list[MessageResponse]
    next_before_message_id: int | None = Field(default=None)
