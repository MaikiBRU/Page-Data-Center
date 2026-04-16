from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_permission
from app.models.user import User
from app.models.audit_log import AuditLog
from app.schemas.user import (
    AuditLogOut,
    UserAdminCreate,
    UserAdminOut,
    UserAdminUpdate,
    UserPasswordReset,
)
from app.services.security import get_password_hash

router = APIRouter(prefix="/users", tags=["users"])


def _require_admin(current_user: User, db: Session) -> None:
    if not current_user.is_admin:
        try:
            log = AuditLog(
                actor_id=current_user.id,
                action="permission_denied",
                target_user_id=None,
                meta={"action": "users:manage", "role": current_user.role},
            )
            db.add(log)
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")


def _role_valid(role: str) -> bool:
    return role in {"admin", "analyst", "viewer"}


def _log_action(
    db: Session,
    actor_id: int,
    action: str,
    target_user_id: int | None = None,
    meta: dict | None = None,
) -> None:
    log = AuditLog(
        actor_id=actor_id,
        action=action,
        target_user_id=target_user_id,
        meta=meta,
    )
    db.add(log)


def _password_valid(password: str) -> bool:
    if len(password) < 8:
        return False
    if len(password.encode("utf-8")) > 256:
        return False
    if not any(char.isdigit() for char in password):
        return False
    if not any(char.isalpha() for char in password):
        return False
    return True


@router.get("", response_model=list[UserAdminOut])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user, db)
    return db.query(User).order_by(User.created_at.desc()).all()


@router.get("/assignable")
def list_assignable(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("users:assignable")),
):
    users = (
        db.query(User)
        .filter(User.is_active == True)  # noqa: E712
        .order_by(User.created_at.asc())
        .all()
    )
    return [
        {
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "is_admin": user.is_admin,
        }
        for user in users
    ]


@router.get("/audit", response_model=list[AuditLogOut])
def list_audit(
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user, db)
    logs = (
        db.query(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .limit(min(limit, 200))
        .all()
    )
    user_ids = {log.actor_id for log in logs}
    user_ids.update({log.target_user_id for log in logs if log.target_user_id})
    users = {}
    if user_ids:
        rows = db.query(User).filter(User.id.in_(user_ids)).all()
        users = {row.id: row.email for row in rows}
    return [
        AuditLogOut(
            id=log.id,
            action=log.action,
            actor_email=users.get(log.actor_id),
            target_email=users.get(log.target_user_id),
            meta=log.meta,
            created_at=log.created_at,
        )
        for log in logs
    ]


@router.post("", response_model=UserAdminOut, status_code=201)
def create_user(
    payload: UserAdminCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user, db)
    if not _password_valid(payload.password):
        raise HTTPException(
            status_code=400,
            detail="Password must be 8-256 chars, include letters and numbers",
        )
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    role = payload.role if _role_valid(payload.role) else "viewer"
    if payload.is_admin or role == "admin":
        role = "admin"
        payload.is_admin = True
    user = User(
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
        is_active=True,
        is_verified=True,
        is_admin=payload.is_admin,
        role=role,
    )
    db.add(user)
    db.flush()
    _log_action(
        db,
        actor_id=current_user.id,
        action="user_create",
        target_user_id=user.id,
        meta={"is_admin": payload.is_admin},
    )
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserAdminOut)
def update_user(
    user_id: int,
    payload: UserAdminUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user, db)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    changes: dict[str, dict[str, bool]] = {}
    if payload.is_active is not None and payload.is_active != user.is_active:
        if user.is_admin and payload.is_active is False:
            other_admins = (
                db.query(User)
                .filter(User.is_admin == True, User.id != user.id)  # noqa: E712
                .count()
            )
            if other_admins == 0:
                raise HTTPException(status_code=400, detail="Cannot deactivate last admin")
        changes["is_active"] = {"from": user.is_active, "to": payload.is_active}
        user.is_active = payload.is_active
        user.token_version += 1
    if payload.is_admin is not None and payload.is_admin != user.is_admin:
        if user.is_admin and payload.is_admin is False:
            other_admins = (
                db.query(User)
                .filter(User.is_admin == True, User.id != user.id)  # noqa: E712
                .count()
            )
            if other_admins == 0:
                raise HTTPException(status_code=400, detail="Cannot remove last admin")
        changes["is_admin"] = {"from": user.is_admin, "to": payload.is_admin}
        user.is_admin = payload.is_admin
        if payload.is_admin:
            user.role = "admin"
        if not payload.is_admin and user.role == "admin":
            user.role = "viewer"
    if payload.role and _role_valid(payload.role) and payload.role != user.role:
        if user.is_admin and payload.role != "admin":
            other_admins = (
                db.query(User)
                .filter(User.is_admin == True, User.id != user.id)  # noqa: E712
                .count()
            )
            if other_admins == 0:
                raise HTTPException(status_code=400, detail="Cannot remove last admin")
        if payload.role == "admin":
            user.is_admin = True
        changes["role"] = {"from": user.role, "to": payload.role}
        user.role = payload.role
    if changes:
        _log_action(
            db,
            actor_id=current_user.id,
            action="user_update",
            target_user_id=user.id,
            meta={"changes": changes},
        )
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: int,
    payload: UserPasswordReset,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user, db)
    if not _password_valid(payload.password):
        raise HTTPException(
            status_code=400,
            detail="Password must be 8-256 chars, include letters and numbers",
        )
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.hashed_password = get_password_hash(payload.password)
    user.token_version += 1
    _log_action(
        db,
        actor_id=current_user.id,
        action="user_reset_password",
        target_user_id=user.id,
    )
    db.commit()
    return {"status": "password_reset"}
