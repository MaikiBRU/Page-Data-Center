from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import api_router
from app.core.config import settings
from sqlalchemy import text
from sqlalchemy import inspect

from app.db.base import Base
import app.models  # noqa: F401
from app.db.session import engine


app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.allowed_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

app.include_router(api_router)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
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
        with engine.begin() as connection:
            result = connection.execute(text("SELECT COUNT(*) FROM users WHERE is_admin = TRUE"))
            admin_count = result.scalar() or 0
            if admin_count == 0:
                connection.execute(
                    text(
                        "UPDATE users SET is_admin = TRUE, role = 'admin' WHERE id = (SELECT id FROM users ORDER BY id ASC LIMIT 1)"
                    )
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


@app.get("/")
def root():
    return {"status": "ok"}
