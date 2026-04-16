from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=True)
    google_id = Column(String(255), nullable=True)
    is_verified = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    token_version = Column(Integer, default=0)
    role = Column(String(20), default="viewer")
    reset_token_hash = Column(String(255), nullable=True)
    reset_token_expires_at = Column(DateTime, nullable=True)
    reset_requested_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
