from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, LargeBinary, String

from app.db.base import Base


class DemoDatasetFile(Base):
    """CSV payload for a demo dataset, stored in PostgreSQL.

    Demo files never touch the filesystem. App Runner's disk is ephemeral, so
    anything written there is lost on restart while the dataset row survives,
    leaving a broken pointer. Keeping the bytes in the database makes the file
    disappear atomically with the session that owns it, and the demo quota
    (6 MB per session) keeps the storage cost negligible.
    """

    __tablename__ = "demo_dataset_files"

    id = Column(Integer, primary_key=True, index=True)
    demo_session_id = Column(String(64), index=True, nullable=False)
    dataset_id = Column(Integer, index=True, nullable=False, unique=True)
    filename = Column(String(255), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    content = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
