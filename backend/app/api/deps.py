"""Request-scoped dependencies: identity, authorisation and tenant scoping.

Two kinds of caller reach the API:

* an authenticated ``User`` (email/password or Google), unchanged from before;
* an anonymous demo sandbox, represented by a ``DemoSession``.

Both are wrapped in a :class:`Principal`. The important property is that
:func:`get_current_user` **rejects demo tokens outright**. Every endpoint that
has not been explicitly opened to the sandbox keeps using it and is therefore
closed to demo callers by default — forgetting to harden an endpoint fails
closed, not open.

Reads are scoped through :func:`scope_datasets` / :func:`scope_cases`, which
partition the tables: a demo session sees only its own rows, and the
authenticated app sees only rows with no session (never demo data).
"""

from typing import Generator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.audit_log import AuditLog
from app.models.case import Case
from app.models.dataset import Dataset
from app.models.demo_session import DemoSession
from app.models.user import User
from app.services import demo_session as demo_service
from app.services.security import TOKEN_TYPE_DEMO

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _decode(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except JWTError as exc:
        raise _credentials_exception() from exc


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    """Resolve an authenticated application user.

    Demo tokens are refused here. This is the safety net that keeps the
    sandbox out of every endpoint that was not deliberately opened to it.
    """
    payload = _decode(token)
    if payload.get("typ") == TOKEN_TYPE_DEMO:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta funcionalidad no esta disponible en la demo",
        )

    subject: str | None = payload.get("sub")
    token_version: int = int(payload.get("ver", 0))
    if subject is None:
        raise _credentials_exception()

    user = db.query(User).filter(User.email == subject).first()
    if user is None:
        raise _credentials_exception()
    if user.token_version != token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")
    return user


class Principal:
    """Whoever is making the request: a real user or a demo sandbox."""

    __slots__ = ("user", "demo")

    def __init__(self, user: User | None = None, demo: DemoSession | None = None) -> None:
        self.user = user
        self.demo = demo

    @property
    def is_demo(self) -> bool:
        return self.demo is not None

    @property
    def demo_session_id(self) -> str | None:
        return self.demo.id if self.demo else None

    @property
    def email(self) -> str:
        if self.demo:
            return f"demo-{self.demo.label}"
        return self.user.email if self.user else "unknown"

    @property
    def role(self) -> str:
        if self.demo:
            return "demo"
        return (self.user.role if self.user else "viewer") or "viewer"

    @property
    def is_admin(self) -> bool:
        return bool(self.user and self.user.is_admin)

    @property
    def user_id(self) -> int | None:
        return self.user.id if self.user else None


def get_principal(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Principal:
    """Resolve either identity. Used by endpoints the sandbox may reach."""
    payload = _decode(token)

    if payload.get("typ") == TOKEN_TYPE_DEMO:
        session_id = payload.get("sid")
        if not isinstance(session_id, str) or not session_id:
            raise _credentials_exception()
        session = demo_service.load_active_session(db, session_id)
        if session is None:
            # Covers unknown, revoked, TTL-expired and idle-expired sessions.
            # Deliberately one message for all four so probing cannot tell
            # "never existed" apart from "expired".
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="La sesion de demo expiro o no es valida",
                headers={"WWW-Authenticate": "Bearer"},
            )
        demo_service.touch(db, session)
        request.state.demo_session_id = session.id
        return Principal(demo=session)

    return Principal(user=get_current_user(token=token, db=db))


def require_demo(principal: Principal = Depends(get_principal)) -> DemoSession:
    """Endpoints that only make sense inside a sandbox."""
    if not principal.is_demo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Demo session required")
    return principal.demo


# --- authorisation ---------------------------------------------------------

PERMISSIONS: dict[str, set[str]] = {
    "dataset:create": {"admin", "analyst", "demo"},
    "dataset:upload": {"admin", "analyst", "demo"},
    "dataset:generate": {"admin", "analyst", "demo"},
    "dataset:run_quality": {"admin", "analyst", "demo"},
    # Schema and routing configuration stay out of the sandbox: they change
    # how results are produced and are not needed to evaluate the project.
    "dataset:edit_domain": {"admin"},
    "dataset:edit_rules": {"admin"},
    "dataset:edit_assignment": {"admin"},
    "case:create": {"admin", "analyst", "demo"},
    "case:update": {"admin", "analyst", "demo"},
    "case:add_note": {"admin", "analyst", "demo"},
    # Demo seeding has its own endpoint; the global demo reset stays admin-only
    # because it operates on the authenticated application's datasets.
    "dashboard:demo": {"admin", "analyst"},
    # Would leak the email addresses of real users.
    "users:assignable": {"admin", "analyst"},
}


def require_permission(action: str):
    def _guard(
        request: Request,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Principal:
        if principal.is_admin:
            return principal
        allowed = PERMISSIONS.get(action, set())
        if principal.role not in allowed:
            if not principal.is_demo:
                try:
                    log = AuditLog(
                        actor_id=principal.user_id,
                        action="permission_denied",
                        target_user_id=None,
                        meta={
                            "action": action,
                            "path": request.url.path,
                            "role": principal.role,
                        },
                    )
                    db.add(log)
                    db.commit()
                except Exception:
                    db.rollback()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
            )
        return principal

    return _guard


# --- tenant scoping --------------------------------------------------------


def scope_datasets(query, principal: Principal):
    """Restrict a Dataset query to the caller's own partition."""
    if principal.is_demo:
        return query.filter(Dataset.demo_session_id == principal.demo_session_id)
    return query.filter(Dataset.demo_session_id.is_(None))


def scope_cases(query, principal: Principal):
    """Restrict a Case query to the caller's own partition."""
    if principal.is_demo:
        return query.filter(Case.demo_session_id == principal.demo_session_id)
    return query.filter(Case.demo_session_id.is_(None))


def get_scoped_dataset(db: Session, principal: Principal, dataset_id: int) -> Dataset:
    """Load one dataset or 404.

    A dataset belonging to somebody else returns 404, not 403, so the response
    does not confirm that the id exists.
    """
    dataset = scope_datasets(db.query(Dataset).filter(Dataset.id == dataset_id), principal).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


def get_scoped_case(db: Session, principal: Principal, case_id: int) -> Case:
    case = scope_cases(db.query(Case).filter(Case.id == case_id), principal).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


def demo_quota_error(exc: demo_service.DemoQuotaExceeded) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=exc.message,
        headers={"X-Demo-Limit": exc.limit_name},
    )
