import asyncio
import contextlib
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import api_router
from app.core.config import settings
from sqlalchemy import text
from sqlalchemy import inspect

from app.db.base import Base
from app.db.session import SessionLocal
import app.models  # noqa: F401
from app.db.session import engine
from app.services import demo_session as demo_service

logger = logging.getLogger("datacenter")

# The interactive documentation lists every route and payload shape. It stays
# available in development and is off in production, where it is an inventory
# for anyone who finds the host.
app = FastAPI(
    title=settings.app_name,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.allowed_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

app.include_router(api_router)


def run_legacy_schema_sync() -> None:
    """Pre-Alembic schema reconciliation, kept so existing deployments keep
    booting unchanged. New schema changes go through Alembic instead; nothing
    for the demo sandbox is created here.
    """
    Base.metadata.create_all(bind=engine)
    # The statements below are PostgreSQL specific DDL written before Alembic
    # existed. Skip them on any other dialect so the test suite can run the
    # real application against SQLite.
    if engine.dialect.name != "postgresql":
        return
    inspector = inspect(engine)
    if "users" in inspector.get_table_names():
        columns = {col["name"] for col in inspector.get_columns("users")}
        with engine.begin() as connection:
            if "google_id" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN google_id VARCHAR(255)"))
            if "is_verified" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN is_verified BOOLEAN DEFAULT TRUE"))
            if "is_admin" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE"))
            if "token_version" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN token_version INTEGER DEFAULT 0"))
            if "role" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'viewer'"))
            if "reset_token_hash" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN reset_token_hash VARCHAR(255)"))
            if "reset_token_expires_at" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN reset_token_expires_at TIMESTAMP"))
            if "reset_requested_at" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN reset_requested_at TIMESTAMP"))
            if "hashed_password" in columns:
                connection.execute(text("ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL"))
            connection.execute(text("UPDATE users SET is_verified = TRUE WHERE is_verified IS NULL"))
            connection.execute(text("UPDATE users SET is_admin = FALSE WHERE is_admin IS NULL"))
            connection.execute(text("UPDATE users SET token_version = 0 WHERE token_version IS NULL"))
            connection.execute(text("UPDATE users SET role = 'viewer' WHERE role IS NULL"))
            connection.execute(text("UPDATE users SET role = 'admin' WHERE is_admin = TRUE"))
        # Promote a *named* account when the instance has no administrator.
        # This used to promote whichever user had the lowest id, which meant
        # that on a rebuilt database the first person to sign up became
        # administrator -- a stranger, back when sign-up was public.
        if settings.bootstrap_admin_email:
            with engine.begin() as connection:
                result = connection.execute(
                    text("SELECT COUNT(*) FROM users WHERE is_admin = TRUE")
                )
                if (result.scalar() or 0) == 0:
                    connection.execute(
                        text(
                            "UPDATE users SET is_admin = TRUE, role = 'admin' "
                            "WHERE lower(email) = lower(:email)"
                        ),
                        {"email": settings.bootstrap_admin_email},
                    )
    if "cases" in inspector.get_table_names():
        columns = {col["name"] for col in inspector.get_columns("cases")}
        if "assignee" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE cases ADD COLUMN assignee VARCHAR(120)"))
        if "due_date" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE cases ADD COLUMN due_date TIMESTAMP"))
        if "sla_hours" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE cases ADD COLUMN sla_hours INTEGER"))
        with engine.begin() as connection:
            if "blocked_reason" not in columns:
                connection.execute(text("ALTER TABLE cases ADD COLUMN blocked_reason TEXT"))
            if "blocked_until" not in columns:
                connection.execute(text("ALTER TABLE cases ADD COLUMN blocked_until TIMESTAMP"))
            if "escalated_reason" not in columns:
                connection.execute(text("ALTER TABLE cases ADD COLUMN escalated_reason TEXT"))
            if "escalated_level" not in columns:
                connection.execute(text("ALTER TABLE cases ADD COLUMN escalated_level INTEGER"))
            if "escalated_to" not in columns:
                connection.execute(text("ALTER TABLE cases ADD COLUMN escalated_to VARCHAR(120)"))

    if "case_status_logs" in inspector.get_table_names():
        columns = {col["name"] for col in inspector.get_columns("case_status_logs")}
        if "reason" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE case_status_logs ADD COLUMN reason VARCHAR(400)"))

    if "datasets" in inspector.get_table_names():
        columns = {col["name"] for col in inspector.get_columns("datasets")}
        if "rules_config" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE datasets ADD COLUMN rules_config JSONB"))
        with engine.begin() as connection:
            if "assignment_mode" not in columns:
                connection.execute(
                    text("ALTER TABLE datasets ADD COLUMN assignment_mode VARCHAR(20) DEFAULT 'manual'")
                )
            if "assignment_owner" not in columns:
                connection.execute(text("ALTER TABLE datasets ADD COLUMN assignment_owner VARCHAR(120)"))
            if "assignment_cursor" not in columns:
                connection.execute(
                    text("ALTER TABLE datasets ADD COLUMN assignment_cursor INTEGER DEFAULT 0")
                )
            connection.execute(
                text("UPDATE datasets SET assignment_mode = 'manual' WHERE assignment_mode IS NULL")
            )
            connection.execute(
                text("UPDATE datasets SET assignment_cursor = 0 WHERE assignment_cursor IS NULL")
            )

    if "dataset_runs" not in inspector.get_table_names():
        Base.metadata.create_all(bind=engine)


async def _demo_cleanup_loop() -> None:
    """Delete lapsed sandboxes on a timer.

    Runs inside the API process because App Runner offers no scheduler and a
    portfolio demo does not justify standing up one. Requests already reject
    expired sessions on their own, so this loop only reclaims storage; if it
    stops, the demo stays correct and merely accumulates rows until the next
    restart or a call to the maintenance endpoint.
    """
    interval = settings.demo_cleanup_interval_seconds
    while True:
        try:
            await asyncio.sleep(interval)
            db = SessionLocal()
            try:
                removed = demo_service.cleanup_expired(db)
                if removed.get("demo_sessions"):
                    logger.info("demo cleanup removed %s", removed)
            finally:
                db.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Never let a transient database error kill the loop.
            logger.exception("demo cleanup iteration failed")


@app.on_event("startup")
async def on_startup() -> None:
    run_legacy_schema_sync()
    if settings.demo_enabled and settings.demo_cleanup_interval_seconds > 0:
        app.state.demo_cleanup_task = asyncio.create_task(_demo_cleanup_loop())


@app.on_event("shutdown")
async def on_shutdown() -> None:
    task = getattr(app.state, "demo_cleanup_task", None)
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/health")
def health():
    """Readiness probe that actually touches the database."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return {"status": "degraded", "database": False}
    return {"status": "ok", "database": True}
