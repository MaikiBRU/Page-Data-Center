"""Lifecycle for anonymous portfolio demo sandboxes.

A demo session is a short lived, self-contained tenant. Every row it creates
carries its session id, and every read is filtered by that id, so two visitors
can never observe each other. Sessions expire by absolute TTL and by idle
timeout, and expiry is enforced on every request rather than relying on the
cleanup job having already run.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.case import Case
from app.models.case_activity_log import CaseActivityLog
from app.models.case_note import CaseNote
from app.models.case_status_log import CaseStatusLog
from app.models.dataset import Dataset
from app.models.dataset_run import DatasetRun
from app.models.demo_dataset_file import DemoDatasetFile
from app.models.demo_session import DemoSession
from app.services.rate_limit import RateLimitExceeded, SlidingWindowLimiter

_ADJECTIVES = ("agil", "claro", "nitido", "sereno", "vivo", "pulcro", "firme", "lucido")
_NOUNS = ("delta", "cauce", "prisma", "vertice", "umbral", "nodo", "cardinal", "matiz")


class DemoDisabled(Exception):
    """The demo sandbox is switched off by configuration."""


class DemoRateLimited(Exception):
    """Too many sessions requested from the same origin."""


class DemoCapacityReached(Exception):
    """The global cap on concurrent sandboxes is full."""


class DemoQuotaExceeded(Exception):
    """A per-session limit was hit. Carries a user facing message."""

    def __init__(self, message: str, limit_name: str) -> None:
        super().__init__(message)
        self.message = message
        self.limit_name = limit_name


@dataclass(frozen=True)
class SessionState:
    """Snapshot of a sandbox, safe to serialise to the client."""

    id: str
    label: str
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime
    seconds_remaining: int
    idle_seconds_remaining: int
    datasets_used: int
    datasets_max: int
    runs_used: int
    runs_max: int
    exports_used: int
    exports_max: int
    storage_bytes: int
    storage_max_bytes: int
    max_file_size_bytes: int


# --- abuse control ---------------------------------------------------------
# Session creation is limited per client address by the same in-process
# limiter the auth endpoints use. It is per-process: with more than one
# instance the effective allowance multiplies. Redis is not worth it for a
# portfolio demo, and the limit that actually has to hold globally --
# DEMO_MAX_ACTIVE_SESSIONS -- is enforced with a database count in
# create_session below, so it holds regardless of instance count.
#
# The remaining abuse surfaces are capped per session, in the database:
# datasets, storage bytes, quality runs and exports (see the assert_* helpers).
_session_limiter = SlidingWindowLimiter(
    settings.demo_rate_limit_per_hour, 3600, name="demo:session"
)


def hash_client(value: str | None) -> str | None:
    if not value:
        return None
    salted = f"{settings.secret_key}:{value}".encode("utf-8")
    return hashlib.sha256(salted).hexdigest()


def _check_rate_limit(client_key: str | None) -> None:
    if not client_key or settings.demo_rate_limit_per_hour <= 0:
        return
    # The limiter is built once, so a test that changes the setting has to be
    # reflected here too.
    _session_limiter.limit = settings.demo_rate_limit_per_hour
    try:
        _session_limiter.hit(client_key)
    except RateLimitExceeded:
        raise DemoRateLimited() from None


def reset_rate_limits() -> None:
    """Test helper."""
    _session_limiter.reset()


# --- creation --------------------------------------------------------------


def _label() -> str:
    return f"{secrets.choice(_ADJECTIVES)}-{secrets.choice(_NOUNS)}-{secrets.randbelow(90) + 10}"


def create_session(db: Session, client_ip: str | None = None) -> DemoSession:
    if not settings.demo_enabled:
        raise DemoDisabled()

    client_key = hash_client(client_ip)
    _check_rate_limit(client_key)

    now = datetime.utcnow()
    active = (
        db.query(func.count(DemoSession.id))
        .filter(DemoSession.revoked.is_(False))
        .filter(DemoSession.expires_at > now)
        .scalar()
        or 0
    )
    if active >= settings.demo_max_active_sessions:
        raise DemoCapacityReached()

    session = DemoSession(
        # 32 random bytes -> 43 URL-safe characters. Not enumerable.
        id=secrets.token_urlsafe(32),
        label=_label(),
        created_at=now,
        expires_at=now + timedelta(minutes=settings.demo_session_ttl_minutes),
        last_seen_at=now,
        revoked=False,
        runs_used=0,
        exports_used=0,
        storage_bytes=0,
        created_ip_hash=client_key,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


# --- validation ------------------------------------------------------------


def is_expired(session: DemoSession, now: datetime | None = None) -> bool:
    now = now or datetime.utcnow()
    if session.revoked:
        return True
    if session.expires_at <= now:
        return True
    idle_limit = settings.demo_idle_timeout_minutes
    if idle_limit > 0 and session.last_seen_at + timedelta(minutes=idle_limit) <= now:
        return True
    return False


def load_active_session(db: Session, session_id: str) -> DemoSession | None:
    """Return the session only if it exists and is still usable.

    Expiry is decided here, at request time, so a session stops working the
    moment it lapses even if the cleanup job has not deleted its rows yet.
    """
    if not settings.demo_enabled or not session_id:
        return None
    session = db.query(DemoSession).filter(DemoSession.id == session_id).first()
    if session is None:
        return None
    if is_expired(session):
        return None
    return session


def touch(db: Session, session: DemoSession) -> None:
    """Refresh the idle timer, at most once every 30 seconds."""
    now = datetime.utcnow()
    if (now - session.last_seen_at).total_seconds() < 30:
        return
    session.last_seen_at = now
    db.commit()


# --- quotas ----------------------------------------------------------------


def dataset_count(db: Session, session_id: str) -> int:
    return (
        db.query(func.count(Dataset.id)).filter(Dataset.demo_session_id == session_id).scalar()
        or 0
    )


def assert_can_add_dataset(db: Session, session: DemoSession) -> None:
    if dataset_count(db, session.id) >= settings.demo_max_datasets:
        raise DemoQuotaExceeded(
            f"La demo permite hasta {settings.demo_max_datasets} datasets por sesion.",
            "datasets",
        )


def assert_can_run(session: DemoSession) -> None:
    if (session.runs_used or 0) >= settings.demo_max_runs:
        raise DemoQuotaExceeded(
            f"La demo permite hasta {settings.demo_max_runs} corridas de calidad por sesion.",
            "runs",
        )


def assert_can_export(session: DemoSession) -> None:
    if (session.exports_used or 0) >= settings.demo_max_exports:
        raise DemoQuotaExceeded(
            f"La demo permite hasta {settings.demo_max_exports} exportaciones por sesion.",
            "exports",
        )


def assert_storage_available(session: DemoSession, incoming_bytes: int) -> None:
    if incoming_bytes > settings.demo_max_file_size_bytes:
        raise DemoQuotaExceeded(
            f"El archivo supera el maximo de {settings.demo_max_file_size_mb} MB por archivo.",
            "file_size",
        )
    if (session.storage_bytes or 0) + incoming_bytes > settings.demo_max_storage_bytes:
        raise DemoQuotaExceeded(
            f"La demo permite hasta {settings.demo_max_storage_mb} MB de almacenamiento por sesion.",
            "storage",
        )


def register_run(db: Session, session: DemoSession) -> None:
    session.runs_used = (session.runs_used or 0) + 1
    db.commit()


def register_export(db: Session, session: DemoSession) -> None:
    session.exports_used = (session.exports_used or 0) + 1
    db.commit()


def recalculate_storage(db: Session, session: DemoSession) -> None:
    total = (
        db.query(func.coalesce(func.sum(DemoDatasetFile.size_bytes), 0))
        .filter(DemoDatasetFile.demo_session_id == session.id)
        .scalar()
        or 0
    )
    session.storage_bytes = int(total)
    db.commit()


def describe(db: Session, session: DemoSession) -> SessionState:
    now = datetime.utcnow()
    idle_limit = settings.demo_idle_timeout_minutes
    if idle_limit > 0:
        idle_deadline = session.last_seen_at + timedelta(minutes=idle_limit)
    else:
        idle_deadline = session.expires_at
    return SessionState(
        id=session.id,
        label=session.label,
        created_at=session.created_at,
        expires_at=session.expires_at,
        last_seen_at=session.last_seen_at,
        seconds_remaining=max(0, int((session.expires_at - now).total_seconds())),
        idle_seconds_remaining=max(0, int((idle_deadline - now).total_seconds())),
        datasets_used=dataset_count(db, session.id),
        datasets_max=settings.demo_max_datasets,
        runs_used=session.runs_used or 0,
        runs_max=settings.demo_max_runs,
        exports_used=session.exports_used or 0,
        exports_max=settings.demo_max_exports,
        storage_bytes=session.storage_bytes or 0,
        storage_max_bytes=settings.demo_max_storage_bytes,
        max_file_size_bytes=settings.demo_max_file_size_bytes,
    )


# --- teardown --------------------------------------------------------------


def purge_session_data(db: Session, session_id: str) -> dict[str, int]:
    """Delete every artefact owned by a sandbox.

    Idempotent: running it twice on the same id deletes nothing the second
    time and raises nothing. Ordered leaves-first so no step depends on rows
    another step already removed.

    Raises:
        ValueError: if ``session_id`` is empty. Every filter below compares
            ``demo_session_id`` to it, and SQLAlchemy turns ``column == None``
            into ``IS NULL`` -- which is exactly how the authenticated
            application's rows are marked. A None slipping through would
            therefore select the whole application partition and delete it,
            and the commit at the end of this function makes that
            unrecoverable. No caller can currently do it; this makes it
            impossible rather than merely unlikely.
    """
    if not session_id:
        raise ValueError("purge_session_data requires a demo session id")

    removed: dict[str, int] = {}

    dataset_ids = [
        row[0] for row in db.query(Dataset.id).filter(Dataset.demo_session_id == session_id).all()
    ]
    case_ids = [
        row[0] for row in db.query(Case.id).filter(Case.demo_session_id == session_id).all()
    ]

    if case_ids:
        removed["case_notes"] = (
            db.query(CaseNote)
            .filter(CaseNote.case_id.in_(case_ids))
            .delete(synchronize_session=False)
        )
        removed["case_status_logs"] = (
            db.query(CaseStatusLog)
            .filter(CaseStatusLog.case_id.in_(case_ids))
            .delete(synchronize_session=False)
        )
        removed["case_activity_logs"] = (
            db.query(CaseActivityLog)
            .filter(CaseActivityLog.case_id.in_(case_ids))
            .delete(synchronize_session=False)
        )

    removed["cases"] = (
        db.query(Case).filter(Case.demo_session_id == session_id).delete(synchronize_session=False)
    )

    if dataset_ids:
        removed["dataset_runs"] = (
            db.query(DatasetRun)
            .filter(DatasetRun.dataset_id.in_(dataset_ids))
            .delete(synchronize_session=False)
        )

    removed["demo_dataset_files"] = (
        db.query(DemoDatasetFile)
        .filter(DemoDatasetFile.demo_session_id == session_id)
        .delete(synchronize_session=False)
    )
    removed["datasets"] = (
        db.query(Dataset)
        .filter(Dataset.demo_session_id == session_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return removed


def end_session(db: Session, session: DemoSession) -> dict[str, int]:
    """Visitor-triggered teardown: wipe the data and drop the session row."""
    removed = purge_session_data(db, session.id)
    db.query(DemoSession).filter(DemoSession.id == session.id).delete(synchronize_session=False)
    db.commit()
    removed["demo_sessions"] = 1
    return removed


def cleanup_expired(db: Session, now: datetime | None = None) -> dict[str, int]:
    """Remove every lapsed sandbox and its data. Safe to run repeatedly."""
    now = now or datetime.utcnow()
    stale = [session for session in db.query(DemoSession).all() if is_expired(session, now)]

    totals: dict[str, int] = {"demo_sessions": 0}
    for session in stale:
        removed = purge_session_data(db, session.id)
        for key, value in removed.items():
            totals[key] = totals.get(key, 0) + value
        db.query(DemoSession).filter(DemoSession.id == session.id).delete(
            synchronize_session=False
        )
        totals["demo_sessions"] += 1
    db.commit()

    # Safety net: demo rows whose session row is already gone (for example a
    # partial failure in an earlier pass) would otherwise linger forever.
    live_ids = {row[0] for row in db.query(DemoSession.id).all()}
    orphan_ids = {
        row[0]
        for row in db.query(Dataset.demo_session_id)
        .filter(Dataset.demo_session_id.is_not(None))
        .distinct()
        .all()
    } - live_ids
    for orphan in orphan_ids:
        removed = purge_session_data(db, orphan)
        for key, value in removed.items():
            totals[key] = totals.get(key, 0) + value
    return totals
