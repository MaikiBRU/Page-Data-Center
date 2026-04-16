from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.db.base import Base


class CaseNote(Base):
    __tablename__ = "case_notes"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, index=True, nullable=False)
    author = Column(String(255), nullable=False)
    note = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
