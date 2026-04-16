from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.db.base import Base


class Case(Base):
    __tablename__ = "cases"

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, index=True, nullable=False)
    title = Column(String(255), nullable=False)
    severity = Column(String(20), default="medium", nullable=False)
    status = Column(String(20), default="open", nullable=False)
    assignee = Column(String(120), nullable=True)
    summary = Column(Text, nullable=True)
    recommendation = Column(Text, nullable=True)
    due_date = Column(DateTime, nullable=True)
    sla_hours = Column(Integer, nullable=True)
    blocked_reason = Column(Text, nullable=True)
    blocked_until = Column(DateTime, nullable=True)
    escalated_reason = Column(Text, nullable=True)
    escalated_level = Column(Integer, nullable=True)
    escalated_to = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
