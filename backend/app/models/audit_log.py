from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from app.db.base import Base

JsonColumn = JSONB().with_variant(JSON(), "sqlite")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    actor_id = Column(Integer, nullable=False)
    action = Column(String(120), nullable=False)
    target_user_id = Column(Integer, nullable=True)
    meta = Column(JsonColumn, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
