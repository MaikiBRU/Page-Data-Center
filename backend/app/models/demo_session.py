from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.db.base import Base


class DemoSession(Base):
    """A short lived, anonymous sandbox for a portfolio visitor.

    The primary key is a 43 character URL-safe random token, not a sequence,
    so session identifiers cannot be enumerated or guessed. Every demo owned
    row in the database references this id.
    """

    __tablename__ = "demo_sessions"

    id = Column(String(64), primary_key=True, index=True)
    label = Column(String(60), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)

    # Quota counters. Incremented server side only.
    runs_used = Column(Integer, default=0, nullable=False)
    exports_used = Column(Integer, default=0, nullable=False)
    storage_bytes = Column(Integer, default=0, nullable=False)

    # Coarse abuse signal. Never returned by the API.
    created_ip_hash = Column(String(64), nullable=True)
