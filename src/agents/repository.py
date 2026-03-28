from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import AgentProfileRecord, ModelProfileRecord


class AgentRepository:
    def get_agent_profile(self, db: Session, *, agent_id: str) -> AgentProfileRecord | None:
        return db.get(AgentProfileRecord, agent_id)

    def list_agent_profiles(self, db: Session, *, include_disabled: bool = True) -> list[AgentProfileRecord]:
        stmt = select(AgentProfileRecord).order_by(AgentProfileRecord.agent_id.asc())
        if not include_disabled:
            stmt = stmt.where(AgentProfileRecord.enabled == 1)
        return list(db.scalars(stmt))

    def get_model_profile_by_key(self, db: Session, *, profile_key: str) -> ModelProfileRecord | None:
        return db.scalar(select(ModelProfileRecord).where(ModelProfileRecord.profile_key == profile_key))

    def get_model_profile(self, db: Session, *, profile_id: int) -> ModelProfileRecord | None:
        return db.get(ModelProfileRecord, profile_id)

    def list_model_profiles(self, db: Session, *, include_disabled: bool = True) -> list[ModelProfileRecord]:
        stmt = select(ModelProfileRecord).order_by(ModelProfileRecord.profile_key.asc())
        if not include_disabled:
            stmt = stmt.where(ModelProfileRecord.enabled == 1)
        return list(db.scalars(stmt))
