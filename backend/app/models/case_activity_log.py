from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, JSON

from app.db.base import Base


class CaseActivityLog(Base):
    __tablename__ = "case_activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, index=True, nullable=False)
    event_type = Column(String(30), nullable=False)
    actor_email = Column(String(120), nullable=True)
    meta = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
