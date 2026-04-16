import os
import re
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings(
    "ignore",
    message="urllib3 .* doesn't match a supported version!",
)


ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://app:app@127.0.0.1:5432/data_quality")

ADMIN_EMAIL = "admin@datacontrol.app"
ADMIN_PASSWORD = "Admin1234"

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.main import app
from app.models.user import User
from app.services.security import get_password_hash


def _assert(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[ok] {label}")


def _get_admin(db: Session) -> User:
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


def _login(client: TestClient, email: str, password: str) -> str:
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
    stamp = int(time.time())
    user_email = f"smoke_{stamp}@example.com"
    user_password = "Smoke1234"
    user_password_2 = "Reset1234"

    with SessionLocal() as db:
        _get_admin(db)

    client = TestClient(app)
    admin_token = _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)

    response = client.post(
        "/auth/register",
        json={"email": user_email, "password": user_password},
    )
    _assert(response.status_code == 200, "auth register")

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
