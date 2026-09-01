from datetime import datetime, timedelta

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
ALGORITHM = "HS256"

# Token kinds. The claim is mandatory on demo tokens and absent on legacy user
# tokens, so an old token can never be mistaken for a demo one or vice versa.
TOKEN_TYPE_DEMO = "demo"


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(subject: str, token_version: int = 0) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "exp": expire, "ver": token_version}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_demo_token(session_id: str, expires_at: datetime) -> str:
    """Mint a bearer token bound to one demo sandbox.

    The token carries no privileges of its own: it names a session, and the
    server re-reads that session from the database on every request to decide
    whether it is still alive. Its ``exp`` mirrors the session TTL so an
    orphaned token dies on its own even if the row is gone.
    """
    payload = {
        "sub": f"demo:{session_id}",
        "typ": TOKEN_TYPE_DEMO,
        "sid": session_id,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)
