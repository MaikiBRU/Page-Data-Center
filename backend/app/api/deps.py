from typing import Generator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.user import User
from app.models.audit_log import AuditLog

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        subject: str | None = payload.get("sub")
        token_version: int = int(payload.get("ver", 0))
        if subject is None:
            raise credentials_exception
    except JWTError as exc:
        raise credentials_exception from exc

    user = db.query(User).filter(User.email == subject).first()
    if user is None:
        raise credentials_exception
    if user.token_version != token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")
    return user


def require_roles(*roles: str):
    def _guard(user: User = Depends(get_current_user)) -> User:
        if user.is_admin:
            return user
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return _guard


PERMISSIONS: dict[str, set[str]] = {
    "dataset:create": {"admin", "analyst"},
    "dataset:upload": {"admin", "analyst"},
    "dataset:generate": {"admin", "analyst"},
    "dataset:run_quality": {"admin", "analyst"},
    "dataset:edit_domain": {"admin"},
    "dataset:edit_rules": {"admin"},
    "dataset:edit_assignment": {"admin"},
    "case:create": {"admin", "analyst"},
    "case:update": {"admin", "analyst"},
    "case:add_note": {"admin", "analyst"},
    "dashboard:demo": {"admin", "analyst"},
    "users:assignable": {"admin", "analyst"},
}


def require_permission(action: str):
    def _guard(
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if user.is_admin:
            return user
        allowed = PERMISSIONS.get(action, set())
        if user.role not in allowed:
            try:
                log = AuditLog(
                    actor_id=user.id,
                    action="permission_denied",
                    target_user_id=None,
                    meta={"action": action, "path": request.url.path, "role": user.role},
                )
                db.add(log)
                db.commit()
            except Exception:
                db.rollback()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return _guard
