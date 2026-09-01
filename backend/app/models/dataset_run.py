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
    # Number of distinct findings, i.e. (rule, field) pairs that fired.
    issue_count = Column(Integer, nullable=True)
    # Total rule firings. Can exceed total_rows; not a row count.
    issue_rows = Column(Integer, nullable=True)
    # Distinct rows failing at least one rule / at least one high severity
    # rule. NULL on runs recorded before these were tracked.
    rows_affected = Column(Integer, nullable=True)
    critical_rows = Column(Integer, nullable=True)
    anomaly_count = Column(Integer, nullable=True)
    risk_score = Column(Float, nullable=True)
    quality_score = Column(Float, nullable=True)
