"""End to end smoke test against a local instance.

This script *writes* to whatever database it is pointed at: it creates or
resets an administrator account and then exercises the API. Two guards make
that safe to run by hand:

* the administrator password comes from ``SMOKE_ADMIN_PASSWORD`` and has no
  default, so the repository never carries a working credential;
* the target database must be on loopback, so pointing it at a managed
  instance aborts before anything is written.

Usage::

    SMOKE_ADMIN_PASSWORD='<a password you choose>' python scripts/smoke_test.py
"""

import ipaddress
import os
import re
import socket
import sys
import time
import warnings
from pathlib import Path
from urllib.parse import urlsplit

warnings.filterwarnings(
    "ignore",
    message="urllib3 .* doesn't match a supported version!",
)


ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

ADMIN_EMAIL = "admin@datacontrol.app"
PASSWORD_ENV_VAR = "SMOKE_ADMIN_PASSWORD"


class SmokeTestRefused(RuntimeError):
    """The script declined to run. Carries a message meant for a human."""


def require_admin_password(environ: dict | None = None) -> str:
    """Read the administrator password, or refuse to continue.

    There is deliberately no default. A literal in this file would be a
    working administrator credential published in the repository, and this
    script is what creates that account.
    """
    environ = os.environ if environ is None else environ
    password = (environ.get(PASSWORD_ENV_VAR) or "").strip()
    if not password:
        raise SmokeTestRefused(
            f"Falta la variable de entorno {PASSWORD_ENV_VAR}.\n"
            f"Este script crea o resetea el usuario {ADMIN_EMAIL}, asi que la "
            "contrasena tiene que venir de afuera y no del repositorio.\n"
            f"Ejemplo:  {PASSWORD_ENV_VAR}='<elegi-una>' python scripts/smoke_test.py"
        )
    if len(password) < 8:
        raise SmokeTestRefused(
            f"{PASSWORD_ENV_VAR} debe tener al menos 8 caracteres."
        )
    return password


def _addresses_for(host: str) -> list[str]:
    """Every address the host resolves to. Empty when it does not resolve."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return []
    return [info[4][0] for info in infos]


def database_host(url: str) -> str | None:
    """Host of a SQLAlchemy URL, or None when there is no network target.

    SQLite and other file or memory backends have no host, so there is
    nothing to protect against.
    """
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme.split("+", 1)[0] in {"sqlite", ""}:
        return None
    return parsed.hostname


def is_local_database(url: str) -> bool:
    """True when the URL points at this machine.

    Decided by resolving the host and checking the addresses, not by matching
    text: ``localhost``, ``127.0.0.1`` and ``::1`` are all accepted, and a
    hostname that happens to contain "local" but resolves elsewhere is not.
    Every resolved address must be a loopback address, so a name with both a
    loopback and a public record is refused.
    """
    host = database_host(url)
    if host is None:
        return True

    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass  # not a literal address, resolve it below

    addresses = _addresses_for(host)
    if not addresses:
        return False
    try:
        return all(ipaddress.ip_address(a).is_loopback for a in addresses)
    except ValueError:
        return False


def require_local_database(url: str) -> None:
    """Refuse to touch anything that is not on this machine.

    The script resets an administrator password and writes datasets and
    cases. Run against a deployed database it would plant a known credential
    in it.
    """
    if is_local_database(url):
        return
    host = database_host(url) or "?"
    raise SmokeTestRefused(
        f"La base de datos apunta a '{host}', que no es loopback.\n"
        "Este script escribe en la base (crea un admin, datasets y casos), asi "
        "que solo corre contra una instancia local.\n"
        "Levantala con:  docker compose up -d db"
    )


def preflight() -> str:
    """Run both guards before anything imports the application."""
    password = require_admin_password()
    # The effective URL is whatever the app will use: an exported variable
    # wins over backend/.env, so read it through the settings object rather
    # than guessing.
    from app.core.config import settings

    require_local_database(settings.database_url)
    return password


ADMIN_PASSWORD = ""  # set by main() from the environment


def _assert(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[ok] {label}")


def _get_admin(db):
    invalid_users = [user for user in db.query(User).all() if user.email.endswith(".local")]
    changed = False
    for user in invalid_users:
        local_part = user.email.split("@", 1)[0]
        fallback_email = f"{local_part}+legacy{user.id}@datacontrol.app"
        if user.email == "admin@datacontrol.local" and not db.query(User).filter(User.email == ADMIN_EMAIL).first():
            user.email = ADMIN_EMAIL
        else:
            user.email = fallback_email
        changed = True
    if changed:
        db.commit()

    admin = db.query(User).filter(User.email == ADMIN_EMAIL).first()
    if admin:
        admin.hashed_password = get_password_hash(ADMIN_PASSWORD)
        admin.is_active = True
        admin.is_verified = True
        admin.is_admin = True
        admin.role = "admin"
        db.commit()
        db.refresh(admin)
        return admin
    admin = User(
        email=ADMIN_EMAIL,
        hashed_password=get_password_hash(ADMIN_PASSWORD),
        is_active=True,
        is_verified=True,
        is_admin=True,
        role="admin",
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def _login(client, email: str, password: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": password})
    _assert(response.status_code == 200, f"login {email}")
    token = response.json()["access_token"]
    _assert(bool(token), f"token returned for {email}")
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _read_reset_token(email: str) -> str:
    log_file = ROOT / "logs" / "password_reset.log"
    _assert(log_file.exists(), "password reset log exists")
    content = log_file.read_text(encoding="utf-8")
    matches = [
        line for line in content.splitlines()
        if f"| {email} |" in line and "token=" in line
    ]
    _assert(bool(matches), "password reset entry written")
    match = re.search(r"token=([^&]+)", matches[-1])
    _assert(match is not None, "reset token present in log")
    return match.group(1)


def main() -> None:
    global ADMIN_PASSWORD
    try:
        ADMIN_PASSWORD = preflight()
    except SmokeTestRefused as refusal:
        print(f"[abortado] {refusal}", file=sys.stderr)
        raise SystemExit(2) from None

    global TestClient, SessionLocal, app, User, get_password_hash
    from fastapi.testclient import TestClient
    from app.db.session import SessionLocal
    from app.main import app, run_legacy_schema_sync
    from app.models.user import User
    from app.services.security import get_password_hash

    # Create the schema before anything queries it. TestClient only runs the
    # application's startup hook when used as a context manager, which this
    # script does not do, so on an empty database _get_admin below used to
    # fail with "no such table: users". Against an existing PostgreSQL
    # instance this is a no-op: create_all skips tables that are there and
    # the legacy statements check the catalogue before altering anything.
    run_legacy_schema_sync()

    # The reset link is only written to logs/password_reset.log when this is
    # on, and it is off by default so production never records a live token.
    # The guards above already proved this is a local database.
    from app.core.config import settings as _settings

    _settings.reset_link_to_logs = True

    stamp = int(time.time())
    user_email = f"smoke_{stamp}@example.com"
    # Derived from the operator supplied password so no credential is
    # literal here either; the account is throwaway and unique per run.
    user_password = f"{ADMIN_PASSWORD}-u{stamp}"
    user_password_2 = f"{ADMIN_PASSWORD}-r{stamp}"

    with SessionLocal() as db:
        _get_admin(db)

    client = TestClient(app)
    admin_token = _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)

    # Accounts are created by an administrator: the public sign-up endpoint was
    # removed because it let anyone provision themselves read access.
    response = client.post(
        "/users",
        json={"email": user_email, "password": user_password, "role": "viewer"},
        headers=_auth(admin_token),
    )
    _assert(response.status_code == 201, "admin creates user")

    user_token = _login(client, user_email, user_password)

    response = client.get("/auth/me", headers=_auth(user_token))
    _assert(response.status_code == 200, "auth me")

    response = client.post("/auth/forgot-password", json={"email": user_email})
    _assert(response.status_code == 200, "forgot password")
    reset_token = _read_reset_token(user_email)

    response = client.post(
        "/auth/reset-password",
        json={"email": user_email, "token": reset_token, "password": user_password_2},
    )
    _assert(response.status_code == 200, "reset password")

    user_token = _login(client, user_email, user_password_2)

    response = client.post(
        "/datasets",
        json={"name": f"Smoke Dataset {stamp}", "domain": "ecommerce-logistica"},
        headers=_auth(admin_token),
    )
    _assert(response.status_code == 200, "dataset create")
    dataset_id = response.json()["id"]

    response = client.post(
        f"/datasets/{dataset_id}/generate",
        json={"rows": 120, "anomaly_rate": 0.12},
        headers=_auth(admin_token),
    )
    _assert(response.status_code == 200, "dataset generate")

    response = client.get(f"/datasets/{dataset_id}/preview", headers=_auth(user_token))
    _assert(response.status_code == 200, "dataset preview")

    response = client.post(
        f"/datasets/{dataset_id}/run-quality",
        headers=_auth(admin_token),
    )
    _assert(response.status_code == 200, "dataset run quality")

    response = client.get(f"/datasets/{dataset_id}/runs", headers=_auth(user_token))
    _assert(response.status_code == 200 and len(response.json()) >= 1, "dataset runs")

    response = client.get(
        f"/datasets/{dataset_id}/report?format=json",
        headers=_auth(user_token),
    )
    _assert(response.status_code == 200, "dataset report json")

    response = client.get(
        f"/datasets/{dataset_id}/report?format=csv",
        headers=_auth(user_token),
    )
    _assert(response.status_code == 200, "dataset report csv")

    response = client.get("/dashboard/kpis", headers=_auth(user_token))
    _assert(response.status_code == 200, "dashboard kpis")

    response = client.get("/dashboard/insights", headers=_auth(user_token))
    _assert(response.status_code == 200, "dashboard insights")

    response = client.get("/dashboard/report", headers=_auth(user_token))
    _assert(response.status_code == 200, "dashboard report")

    response = client.get("/users/assignable", headers=_auth(admin_token))
    _assert(response.status_code == 200, "users assignable")

    assignees = response.json()
    assignee_email = assignees[0]["email"] if assignees else None

    response = client.post(
        "/cases",
        json={
            "dataset_id": dataset_id,
            "title": "Smoke case for validation",
            "severity": "high",
            "status": "open",
            "assignee": assignee_email,
            "summary": "Caso de prueba para validar el flujo completo del modulo.",
            "recommendation": "Revisar el dataset, ejecutar correcciones y documentar el hallazgo.",
            "sla_hours": 24,
        },
        headers=_auth(admin_token),
    )
    _assert(response.status_code == 201, "case create")
    case_id = response.json()["id"]

    response = client.get("/cases", headers=_auth(user_token))
    _assert(response.status_code == 200, "cases list")

    response = client.get("/cases/summary", headers=_auth(user_token))
    _assert(response.status_code == 200, "cases summary")

    response = client.get(f"/cases/{case_id}", headers=_auth(user_token))
    _assert(response.status_code == 200, "case detail")

    response = client.get(f"/cases/{case_id}/timeline", headers=_auth(user_token))
    _assert(response.status_code == 200, "case timeline")

    response = client.post(
        f"/cases/{case_id}/notes",
        json={"note": "Nota automatica del smoke test para validar timeline."},
        headers=_auth(admin_token),
    )
    _assert(response.status_code == 200, "case add note")

    response = client.patch(
        f"/cases/{case_id}",
        json={"status": "in_progress", "assignee": assignee_email},
        headers=_auth(admin_token),
    )
    _assert(response.status_code == 200, "case update")

    response = client.get("/cases/export?format=json", headers=_auth(user_token))
    _assert(response.status_code == 200, "cases export json")

    response = client.get("/users", headers=_auth(admin_token))
    _assert(response.status_code == 200, "users list admin")

    print("\nSmoke test completed.")


if __name__ == "__main__":
    main()
