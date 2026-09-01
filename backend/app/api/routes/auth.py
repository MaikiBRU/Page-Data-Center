from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy.orm import Session
import json
import logging
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import urllib.parse
import urllib.request
import urllib.error

from app.api.deps import Principal, get_current_user, get_db, get_principal
from app.core.config import settings
from app.models.user import User
from app.models.audit_log import AuditLog
from app.schemas.user import (
    GoogleLoginRequest,
    ForgotPasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
    SetPasswordRequest,
    IdentityOut,
    Token,
    TokenWithFlags,
    UserOut,
)
from app.services.rate_limit import (
    RateLimitExceeded,
    SlidingWindowLimiter,
    client_ip,
    hash_key,
)
from app.services.security import create_access_token, get_password_hash, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
_OAUTH_STATE: dict[str, float] = {}
_STATE_TTL_SECONDS = 600
_RESET_TOKEN_TTL_MINUTES = 30

_BASE_DIR = Path(__file__).resolve().parents[4]
_LOG_DIR = _BASE_DIR / "logs"
_RESET_LOG = _LOG_DIR / "password_reset.log"

logger = logging.getLogger("datacenter.auth")

# Two windows per endpoint. The per-account one stops somebody grinding a
# single mailbox; the per-address one stops them spreading the same volume
# across many accounts. See services/rate_limit for the single-process caveat.
_login_account_limiter = SlidingWindowLimiter(
    settings.login_max_attempts_per_account,
    settings.login_rate_window_seconds,
    name="login:account",
)
_login_ip_limiter = SlidingWindowLimiter(
    settings.login_max_attempts_per_ip,
    settings.login_rate_window_seconds,
    name="login:ip",
)
_forgot_account_limiter = SlidingWindowLimiter(
    settings.forgot_password_max_per_account,
    settings.forgot_password_rate_window_seconds,
    name="forgot:account",
)
_forgot_ip_limiter = SlidingWindowLimiter(
    settings.forgot_password_max_per_ip,
    settings.forgot_password_rate_window_seconds,
    name="forgot:ip",
)


def reset_rate_limiters() -> None:
    """Clear every window. Test helper."""
    for limiter in (
        _login_account_limiter,
        _login_ip_limiter,
        _forgot_account_limiter,
        _forgot_ip_limiter,
    ):
        limiter.reset()


def _too_many(exc: RateLimitExceeded) -> HTTPException:
    """One message for every rate limited case.

    Deliberately says nothing about whether the account exists, whether the
    password was close, or which of the two windows tripped.
    """
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Demasiados intentos. Espera unos minutos y volve a probar.",
        headers={"Retry-After": str(exc.retry_after)},
    )


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


def _reset_reference(token: str) -> str:
    """Short, non-reversible handle for one reset request.

    Enough to correlate "a reset was issued" with "a reset was used" in the
    logs, useless for actually resetting anything.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def _log_reset_request(email: str, token: str, link: str) -> None:
    """Record that a reset happened, never the token or the link.

    This used to print the full URL to stdout and append it to
    logs/password_reset.log. In production stdout goes to CloudWatch, so
    anyone who could read the logs could take over any account within the
    thirty minute window. The operational record now carries a masked address
    and a truncated hash of the token.

    The full link is still written locally when reset_link_to_logs is on,
    which is forced off in production, so a developer without SendGrid can
    still follow the flow.
    """
    reference = _reset_reference(token)
    logger.info(
        "password reset issued", extra={"reset_ref": reference, "user": _mask_email(email)}
    )

    if not settings.reset_link_logging_enabled:
        return

    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.utcnow().isoformat()
        with _RESET_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} | {email} | {link}\n")
        print(f"[password-reset][dev] {email} -> {link}")
    except Exception:
        logger.warning("could not write the local reset link file")


def _mask_email(email: str) -> str:
    """a...z@example.com -- enough to recognise, not enough to harvest."""
    local, _, domain = (email or "").partition("@")
    if not domain:
        return "***"
    head = local[:1] or "*"
    tail = local[-1:] if len(local) > 2 else ""
    return f"{head}...{tail}@{domain}"


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


# There is no public sign-up endpoint. It existed, unauthenticated, and let
# anyone on the internet create a viewer account with read access to every
# dataset, case and note in the instance -- with no password strength check,
# since the validation below was never applied to it. Nothing in the product
# used it: the demo sandbox needs no account, and real accounts are created by
# an administrator through POST /users.


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


def _resolve_google_user(db: Session, email: str, google_id: str | None) -> User:
    """Find the user behind a verified Google identity.

    Google having authenticated somebody says who they are, not that they are
    allowed in. An unknown email is refused unless auto provisioning is
    switched on or the address is on the allowlist; otherwise any Google
    account in the world could give itself read access to the instance, which
    is the same hole the public sign-up endpoint used to be.
    """
    user = db.query(User).filter(User.email == email).first()

    if user is None:
        allowed = settings.google_auto_provision or email.lower() in settings.google_allowlist
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Esta cuenta no tiene acceso. Pedile a un administrador que la cree.",
            )
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
        return user

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")
    if google_id and user.google_id != google_id:
        user.google_id = google_id
        db.commit()
    return user


@router.post("/login", response_model=Token)
def login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)):
    address = client_ip(request)
    ip_key = hash_key(address)
    account_key = hash_key(address, payload.email)

    # Counted before the password is checked, so a wrong guess costs the same
    # as a right one and the timing gives nothing away.
    try:
        _login_ip_limiter.hit(ip_key)
        _login_account_limiter.hit(account_key)
    except RateLimitExceeded as exc:
        raise _too_many(exc) from None

    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")
    if not user.hashed_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Use Google to sign in")
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # Somebody who proved they own the account should not be held back by
    # their own earlier typos.
    _login_account_limiter.clear(account_key)

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

    user = _resolve_google_user(db, email, google_id)

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

    user = _resolve_google_user(db, email, google_id)

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
def forgot_password(
    request: Request, payload: ForgotPasswordRequest, db: Session = Depends(get_db)
):
    address = client_ip(request)

    # Applied before the lookup, so being rate limited says nothing about
    # whether the address is registered.
    try:
        _forgot_ip_limiter.hit(hash_key(address))
        _forgot_account_limiter.hit(hash_key(address, payload.email))
    except RateLimitExceeded as exc:
        raise _too_many(exc) from None

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
        _log_reset_request(user.email, token, link)
    # Same answer whether or not the address exists.
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


@router.get("/me", response_model=IdentityOut)
def me(principal: Principal = Depends(get_principal)):
    """Identity of the caller: an application user or a demo sandbox."""
    if principal.is_demo:
        return IdentityOut(
            email=principal.email,
            role="demo",
            is_admin=False,
            is_active=True,
            is_demo=True,
            created_at=principal.demo.created_at,
        )
    user = principal.user
    return IdentityOut(
        id=user.id,
        email=user.email,
        role=user.role or "viewer",
        is_admin=bool(user.is_admin),
        is_active=bool(user.is_active),
        is_verified=bool(user.is_verified),
        token_version=user.token_version or 0,
        created_at=user.created_at,
        is_demo=False,
    )
