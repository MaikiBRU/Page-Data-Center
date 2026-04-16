from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy.orm import Session
import json
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import urllib.parse
import urllib.request
import urllib.error

from app.api.deps import get_db, get_current_user
from app.core.config import settings
from app.models.user import User
from app.models.audit_log import AuditLog
from app.schemas.user import (
    GoogleLoginRequest,
    ForgotPasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
    SetPasswordRequest,
    Token,
    TokenWithFlags,
    UserCreate,
    UserOut,
)
from app.services.security import create_access_token, get_password_hash, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
_OAUTH_STATE: dict[str, float] = {}
_STATE_TTL_SECONDS = 600
_RESET_TOKEN_TTL_MINUTES = 30

_BASE_DIR = Path(__file__).resolve().parents[4]
_LOG_DIR = _BASE_DIR / "logs"
_RESET_LOG = _LOG_DIR / "password_reset.log"


def _register_state() -> str:
    state = secrets.token_urlsafe(18)
    _OAUTH_STATE[state] = time.time()
    return state


def _consume_state(state: str | None) -> bool:
    if not state:
        return False
    created = _OAUTH_STATE.pop(state, None)
    if not created:
        return False
    return (time.time() - created) <= _STATE_TTL_SECONDS


def _get_redirect_uri(request: Request) -> str:
    if settings.google_redirect_uri:
        return settings.google_redirect_uri
    return str(request.url_for("google_callback"))


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _log_reset_link(email: str, link: str) -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().isoformat()
    line = f"{stamp} | {email} | {link}\n"
    try:
        with _RESET_LOG.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except Exception:
        pass
    print(f"[password-reset] {email} -> {link}")


def _log_audit(db: Session, actor_id: int, action: str, meta: dict | None = None) -> None:
    log = AuditLog(actor_id=actor_id, action=action, meta=meta)
    db.add(log)


def _exchange_code_for_token(code: str, redirect_uri: str) -> dict:
    if not settings.google_client_secret:
        raise HTTPException(status_code=500, detail="Google client secret not configured")
    payload = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else ""
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {}
        err = payload.get("error") or "unknown_error"
        desc = payload.get("error_description") or "No details"
        detail = f"Google token exchange failed ({err}: {desc})"
        raise HTTPException(status_code=401, detail=detail) from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Google token exchange failed") from exc


@router.post("/register", response_model=UserOut)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
        is_active=True,
        role="viewer",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


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


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")
    if not user.hashed_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Use Google to sign in")
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(subject=user.email, token_version=user.token_version)
    return Token(access_token=token)


@router.post("/google", response_model=TokenWithFlags)
def login_google(payload: GoogleLoginRequest, db: Session = Depends(get_db)):
    if not settings.google_client_id:
        raise HTTPException(status_code=500, detail="Google client id not configured")
    try:
        id_info = google_id_token.verify_oauth2_token(
            payload.id_token,
            google_requests.Request(),
            settings.google_client_id,
            clock_skew_in_seconds=10,
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid Google token") from exc

    email = id_info.get("email")
    google_id = id_info.get("sub")
    if not email:
        raise HTTPException(status_code=400, detail="Google account missing email")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            email=email,
            hashed_password=None,
            google_id=google_id,
            is_active=True,
            is_verified=True,
            role="viewer",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")
        if google_id and user.google_id != google_id:
            user.google_id = google_id
            db.commit()

    token = create_access_token(subject=user.email, token_version=user.token_version)
    return TokenWithFlags(access_token=token, needs_password_setup=not bool(user.hashed_password))


@router.get("/google/start")
def google_start(request: Request):
    if not settings.google_client_id:
        raise HTTPException(status_code=500, detail="Google client id not configured")
    if not settings.google_client_secret:
        raise HTTPException(status_code=500, detail="Google client secret not configured")

    redirect_uri = _get_redirect_uri(request)
    state = _register_state()
    params = urllib.parse.urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
            "access_type": "offline",
        }
    )
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{params}"
    return RedirectResponse(url)


@router.get("/google/callback", name="google_callback")
def google_callback(
    request: Request, code: str | None = None, state: str | None = None, db: Session = Depends(get_db)
):
    if not code:
        raise HTTPException(status_code=400, detail="Missing code")
    if not _consume_state(state):
        raise HTTPException(status_code=400, detail="Invalid state")
    if not settings.google_client_id:
        raise HTTPException(status_code=500, detail="Google client id not configured")

    redirect_uri = _get_redirect_uri(request)
    token_payload = _exchange_code_for_token(code, redirect_uri)
    id_token = token_payload.get("id_token")
    if not id_token:
        raise HTTPException(status_code=401, detail="Missing id_token")

    try:
        id_info = google_id_token.verify_oauth2_token(
            id_token,
            google_requests.Request(),
            settings.google_client_id,
            clock_skew_in_seconds=10,
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {exc}") from exc

    email = id_info.get("email")
    google_id = id_info.get("sub")
    if not email:
        raise HTTPException(status_code=400, detail="Google account missing email")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            email=email,
            hashed_password=None,
            google_id=google_id,
            is_active=True,
            is_verified=True,
            role="viewer",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")
        if google_id and user.google_id != google_id:
            user.google_id = google_id
            db.commit()

    token = create_access_token(subject=user.email, token_version=user.token_version)
    needs_password_setup = not bool(user.hashed_password)
    frontend_url = settings.frontend_url.rstrip("/")
    redirect = (
        f"{frontend_url}/login/google-callback?token="
        f"{urllib.parse.quote(token)}&needs_password_setup={'1' if needs_password_setup else '0'}"
    )
    return RedirectResponse(redirect)


@router.get("/google-config")
def google_config():
    return {"client_id": settings.google_client_id}


@router.post("/set-password")
def set_password(
    payload: SetPasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not _password_valid(payload.password):
        raise HTTPException(
            status_code=400,
            detail="Password must be 8-256 chars, include letters and numbers",
        )
    current_user.hashed_password = get_password_hash(payload.password)
    db.commit()
    return {"status": "password_set"}


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if user and user.is_active:
        token = secrets.token_urlsafe(32)
        user.reset_token_hash = _hash_reset_token(token)
        user.reset_requested_at = datetime.utcnow()
        user.reset_token_expires_at = datetime.utcnow() + timedelta(minutes=_RESET_TOKEN_TTL_MINUTES)
        _log_audit(db, actor_id=user.id, action="password_reset_request", meta={"channel": "email"})
        db.commit()
        frontend_url = settings.frontend_url.rstrip("/")
        link = f"{frontend_url}/reset-password?token={urllib.parse.quote(token)}&email={urllib.parse.quote(user.email)}"
        _log_reset_link(user.email, link)
    return {"status": "ok"}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    if not _password_valid(payload.password):
        raise HTTPException(
            status_code=400,
            detail="Password must be 8-256 chars, include letters and numbers",
        )
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=400, detail="Invalid reset token")
    if not user.reset_token_hash or not user.reset_token_expires_at:
        raise HTTPException(status_code=400, detail="Invalid reset token")
    if user.reset_token_expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Reset token expired")
    if _hash_reset_token(payload.token) != user.reset_token_hash:
        raise HTTPException(status_code=400, detail="Invalid reset token")
    user.hashed_password = get_password_hash(payload.password)
    user.reset_token_hash = None
    user.reset_token_expires_at = None
    user.reset_requested_at = None
    user.token_version += 1
    _log_audit(db, actor_id=user.id, action="password_reset_complete")
    db.commit()
    return {"status": "password_reset"}


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
