from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from app.db.base import Base

# JSONB on PostgreSQL, plain JSON elsewhere so the test suite can run on
# SQLite without a database container.
JsonColumn = JSONB().with_variant(JSON(), "sqlite")


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    domain = Column(String(50), nullable=False)
    source_type = Column(String(50), default="upload", nullable=False)
    file_path = Column(String(500), nullable=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_run_at = Column(DateTime, nullable=True)
    quality_summary = Column(JsonColumn, nullable=True)
    anomaly_summary = Column(JsonColumn, nullable=True)
    rules_config = Column(JsonColumn, nullable=True)
    assignment_mode = Column(String(20), default="manual", nullable=False)
    assignment_owner = Column(String(120), nullable=True)
    assignment_cursor = Column(Integer, default=0, nullable=False)

    # NULL  -> owned by the authenticated application
    # value -> owned by that demo sandbox session and invisible to everyone else
    demo_session_id = Column(String(64), index=True, nullable=True)
