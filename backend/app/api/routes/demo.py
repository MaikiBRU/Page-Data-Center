"""Public entry point for the portfolio demo sandbox.

``POST /demo/session`` is the only unauthenticated write in the demo surface.
It mints a sandbox, seeds it with three analysed datasets so the visitor lands
on a populated dashboard, and returns a bearer token scoped to that sandbox.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_db, get_principal, require_demo
from app.core.config import settings
from app.models.dataset import Dataset
from app.models.demo_session import DemoSession
from app.schemas.demo import (
    DemoConfigOut,
    DemoLimitsOut,
    DemoSessionOut,
    DemoSessionStateOut,
    DemoStartOut,
)
from app.services import demo_session as demo_service
from app.services.data_generator import generate_dataset_csv
from app.services.dataset_storage import store_demo_file
from app.services.quality_run import execute_quality_run
from app.services.security import create_demo_token

router = APIRouter(prefix="/demo", tags=["demo"])

_SEED_DATASETS = (
    ("Pedidos ecommerce", "ecommerce"),
    ("Logistica ultima milla", "logistica"),
    ("Operacion integrada", "ecommerce-logistica"),
)


def _limits() -> DemoLimitsOut:
    return DemoLimitsOut(
        max_datasets=settings.demo_max_datasets,
        max_file_size_mb=settings.demo_max_file_size_mb,
        max_storage_mb=settings.demo_max_storage_mb,
        max_runs=settings.demo_max_runs,
        max_exports=settings.demo_max_exports,
        session_ttl_minutes=settings.demo_session_ttl_minutes,
        idle_timeout_minutes=settings.demo_idle_timeout_minutes,
    )


def _state_out(db: Session, session: DemoSession) -> DemoSessionStateOut:
    state = demo_service.describe(db, session)
    return DemoSessionStateOut(
        label=state.label,
        expires_at=state.expires_at,
        seconds_remaining=state.seconds_remaining,
        idle_seconds_remaining=state.idle_seconds_remaining,
        datasets_used=state.datasets_used,
        datasets_max=state.datasets_max,
        runs_used=state.runs_used,
        runs_max=state.runs_max,
        exports_used=state.exports_used,
        exports_max=state.exports_max,
        storage_bytes=state.storage_bytes,
        storage_max_bytes=state.storage_max_bytes,
        max_file_size_bytes=state.max_file_size_bytes,
    )


def _client_ip(request: Request) -> str | None:
    # Cloudflare and App Runner both sit in front of the API, so the socket
    # address is a proxy. Prefer the forwarded chain, first hop only.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _require_enabled() -> None:
    if not settings.demo_enabled:
        raise HTTPException(status_code=404, detail="Not found")


def seed_sandbox(db: Session, session: DemoSession) -> int:
    """Populate a fresh sandbox with analysed datasets.

    Reuses the existing generator and the shared quality pipeline rather than
    keeping a parallel copy of either. Each session gets its own random seed
    so two visitors do not see byte-identical numbers.
    """
    created = 0
    for index, (name, domain) in enumerate(_SEED_DATASETS[: settings.demo_max_datasets]):
        dataset = Dataset(
            name=name,
            domain=domain,
            source_type="generated",
            created_by=None,
            demo_session_id=session.id,
        )
        db.add(dataset)
        db.commit()
        db.refresh(dataset)

        payload = generate_dataset_csv(
            settings.demo_seed_rows,
            settings.demo_seed_anomaly_rate,
            seed=secrets.randbelow(1_000_000) + index,
        ).encode("utf-8")
        store_demo_file(db, dataset, "dataset-demo.csv", payload)
        execute_quality_run(db, dataset)
        created += 1

    demo_service.recalculate_storage(db, session)
    return created


@router.get("/config", response_model=DemoConfigOut)
def demo_config():
    """Public: lets the landing page render limits without a session."""
    return DemoConfigOut(enabled=settings.demo_enabled, limits=_limits())


@router.post("/session", response_model=DemoStartOut, status_code=status.HTTP_201_CREATED)
def start_demo_session(request: Request, db: Session = Depends(get_db)):
    _require_enabled()
    try:
        session = demo_service.create_session(db, client_ip=_client_ip(request))
    except demo_service.DemoDisabled:
        raise HTTPException(status_code=404, detail="Not found") from None
    except demo_service.DemoRateLimited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas sesiones de demo desde este origen. Volve a intentar en un rato.",
        ) from None
    except demo_service.DemoCapacityReached:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La demo esta en su capacidad maxima. Volve a intentar en unos minutos.",
        ) from None

    try:
        seed_sandbox(db, session)
    except Exception:
        # Never hand back a half-built sandbox; leave nothing behind either.
        db.rollback()
        demo_service.end_session(db, session)
        raise HTTPException(
            status_code=500, detail="No se pudo preparar la demo. Intenta nuevamente."
        ) from None

    token = create_demo_token(session.id, session.expires_at)
    return DemoStartOut(
        access_token=token,
        session=DemoSessionOut(state=_state_out(db, session), limits=_limits()),
    )


@router.get("/session", response_model=DemoSessionOut)
def read_demo_session(
    session: DemoSession = Depends(require_demo), db: Session = Depends(get_db)
):
    return DemoSessionOut(state=_state_out(db, session), limits=_limits())


@router.post("/session/end")
def end_demo_session(
    session: DemoSession = Depends(require_demo), db: Session = Depends(get_db)
):
    """Let a visitor wipe their sandbox immediately instead of waiting."""
    removed = demo_service.end_session(db, session)
    return {"status": "ended", "removed": removed}


@router.post("/session/reset", response_model=DemoSessionOut)
def reset_demo_session(
    session: DemoSession = Depends(require_demo), db: Session = Depends(get_db)
):
    """Wipe the sandbox contents and reseed, keeping the same session."""
    demo_service.purge_session_data(db, session.id)
    seed_sandbox(db, session)
    return DemoSessionOut(state=_state_out(db, session), limits=_limits())


@router.get("/whoami")
def demo_whoami(principal: Principal = Depends(get_principal)):
    """Reports whether the caller's token is a demo one.

    The interface does not call this: it reads the same three fields from
    /auth/me, which it already needs for permissions. Kept as a standalone
    probe for debugging a sandbox token without an account.
    """
    return {"is_demo": principal.is_demo, "role": principal.role, "label": principal.email}


@router.post("/maintenance/cleanup")
def maintenance_cleanup(
    x_demo_maintenance_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Out-of-band cleanup trigger.

    Guarded by a shared secret and disabled when that secret is unset, so it
    is never reachable by default. Exists so cleanup can also be driven from
    outside the process (an uptime pinger, a scheduled job) if the in-process
    loop is turned off.
    """
    expected = settings.demo_maintenance_token
    if not expected:
        raise HTTPException(status_code=404, detail="Not found")
    if not x_demo_maintenance_token or not secrets.compare_digest(
        x_demo_maintenance_token, expected
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    removed = demo_service.cleanup_expired(db)
    return {"status": "ok", "removed": removed}
