from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from app.db.base import Base


class CaseStatusLog(Base):
    __tablename__ = "case_status_logs"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, index=True, nullable=False)
    from_status = Column(String(20), nullable=True)
    to_status = Column(String(20), nullable=False)
    actor_email = Column(String(120), nullable=True)
    reason = Column(String(400), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
