from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer

from app.db.base import Base


class DatasetRun(Base):
    __tablename__ = "dataset_runs"

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, index=True, nullable=False)
    run_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    duration_ms = Column(Integer, nullable=True)
    total_rows = Column(Integer, nullable=True)
    issue_count = Column(Integer, nullable=True)
    issue_rows = Column(Integer, nullable=True)
    anomaly_count = Column(Integer, nullable=True)
    risk_score = Column(Float, nullable=True)
    quality_score = Column(Float, nullable=True)
