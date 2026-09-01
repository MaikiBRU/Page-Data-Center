"""Test harness for the demo sandbox.

Runs the real FastAPI application against an in-memory SQLite database so the
suite needs no container. Only the database dependency is swapped; routing,
dependencies, authorisation and the quality pipeline are the production ones.
"""

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Must be set before app.core.config is imported anywhere.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "test-secret-key-not-used-anywhere-else"
os.environ["DEMO_ENABLED"] = "true"
os.environ["DEMO_CLEANUP_INTERVAL_SECONDS"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.api.deps import get_db  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.core.config import settings  # noqa: E402
import app.main as app_main  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import demo_session as demo_service  # noqa: E402
from app.services.security import create_access_token, get_password_hash  # noqa: E402
import app.models  # noqa: F401,E402


@pytest.fixture()
def db_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def session_factory(db_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=db_engine)


@pytest.fixture()
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(session_factory):
    def _get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    fastapi_app.dependency_overrides[get_db] = _get_db
    demo_service.reset_rate_limits()

    # The fixtures already created the schema on the test engine. Neutralise
    # the legacy startup sync so it does not spin up a second, unused engine.
    original_sync = app_main.run_legacy_schema_sync
    app_main.run_legacy_schema_sync = lambda: None
    try:
        with TestClient(fastapi_app) as test_client:
            yield test_client
    finally:
        app_main.run_legacy_schema_sync = original_sync
        fastapi_app.dependency_overrides.clear()


@pytest.fixture()
def demo_limits():
    """Snapshot and restore quota settings so a test can tighten them."""
    keys = (
        "demo_max_datasets",
        "demo_max_file_size_mb",
        "demo_max_storage_mb",
        "demo_max_runs",
        "demo_max_exports",
        "demo_session_ttl_minutes",
        "demo_idle_timeout_minutes",
        "demo_seed_rows",
        "demo_rate_limit_per_hour",
    )
    saved = {key: getattr(settings, key) for key in keys}
    yield settings
    for key, value in saved.items():
        setattr(settings, key, value)


def start_demo(client) -> tuple[str, dict]:
    """Create a sandbox and return (bearer token, session payload)."""
    response = client.post("/demo/session")
    assert response.status_code == 201, response.text
    body = response.json()
    return body["access_token"], body["session"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make_admin(db, email: str = "admin@example.com") -> tuple[User, str]:
    user = User(
        email=email,
        hashed_password=get_password_hash("Admin1234"),
        is_active=True,
        is_verified=True,
        is_admin=True,
        role="admin",
        token_version=0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, create_access_token(subject=user.email, token_version=0)


def csv_payload(rows: int = 5, columns: int = 4) -> bytes:
    header = ",".join(f"col{i}" for i in range(columns))
    body = "\n".join(",".join(str(r * 10 + c) for c in range(columns)) for r in range(rows))
    return f"{header}\n{body}\n".encode("utf-8")
