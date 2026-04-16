from datetime import datetime, timedelta

from sqlalchemy import Column, DateTime, Integer, String

from app.db.base import Base


class EmailVerification(Base):
    __tablename__ = "email_verifications"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), index=True, nullable=False)
    code = Column(String(10), nullable=False)
    password_hash = Column(String(255), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at

    @staticmethod
    def expiry(minutes: int = 10) -> datetime:
        return datetime.utcnow() + timedelta(minutes=minutes)
