from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import ToolAuditEventRecord


@dataclass
class ToolAuditEvent:
    session_id: str
    correlation_id: str
    capability_name: str
    event_kind: str
    status: str | None
    payload: dict[str, Any]


class ToolAuditSink:
    def record(self, db: Session, event: ToolAuditEvent) -> None:
        db.add(
            ToolAuditEventRecord(
                session_id=event.session_id,
                correlation_id=event.correlation_id,
                capability_name=event.capability_name,
                event_kind=event.event_kind,
                status=event.status,
                payload_json=json.dumps(event.payload, sort_keys=True),
            )
        )
        db.flush()
