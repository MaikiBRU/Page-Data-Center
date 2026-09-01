"""Production hardening: docs exposure, brute force, reset token leakage.

These check observable behaviour -- what a caller gets back, what ends up in a
log -- not how the limiter is implemented.
"""

import io
import logging
import re

import pytest

from conftest import auth, make_admin

from app.core.config import Settings, settings
from app.services.rate_limit import (
    RateLimitExceeded,
    SlidingWindowLimiter,
    client_ip,
    hash_key,
)


def build_settings(**overrides) -> Settings:
    return Settings(_env_file=None, secret_key="x" * 40, database_url="sqlite://", **overrides)


@pytest.fixture(autouse=True)
def clean_limiters():
    from app.api.routes.auth import reset_rate_limiters

    reset_rate_limiters()
    yield
    reset_rate_limiters()


# --- 1. API documentation ---------------------------------------------------


def test_documentation_is_available_in_development():
    assert build_settings(environment="development").docs_enabled is True


def test_documentation_is_off_in_production():
    assert build_settings(environment="production").docs_enabled is False
    assert build_settings(environment="prod").docs_enabled is False


def test_documentation_can_be_turned_back_on_deliberately():
    assert build_settings(environment="production", expose_api_docs=True).docs_enabled is True


def test_documentation_can_be_turned_off_in_development():
    assert build_settings(environment="development", expose_api_docs=False).docs_enabled is False


def test_the_running_app_serves_documentation_in_this_test_environment(client):
    """The suite runs as development, so the routes exist and work."""
    assert settings.docs_enabled is True
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_a_production_app_exposes_no_documentation_routes():
    """Built the same way main.py builds it, with production settings."""
    from fastapi import FastAPI

    prod = build_settings(environment="production")
    app = FastAPI(
        title="t",
        docs_url="/docs" if prod.docs_enabled else None,
        redoc_url="/redoc" if prod.docs_enabled else None,
        openapi_url="/openapi.json" if prod.docs_enabled else None,
    )
    paths = {route.path for route in app.routes}
    assert "/docs" not in paths
    assert "/redoc" not in paths
    assert "/openapi.json" not in paths


# --- 2. login brute force ---------------------------------------------------


def test_repeated_wrong_passwords_are_eventually_refused(client, db):
    make_admin(db, email="victima@example.com")
    limit = settings.login_max_attempts_per_account

    codes = []
    for _ in range(limit + 4):
        response = client.post(
            "/auth/login", json={"email": "victima@example.com", "password": "incorrecta"}
        )
        codes.append(response.status_code)

    assert codes[:limit] == [401] * limit, "attempts within the allowance are judged normally"
    assert codes[limit] == 429, "the next one is refused"
    assert set(codes[limit:]) == {429}


def test_the_refusal_says_nothing_about_the_account(client, db):
    """An unknown address must be refused exactly like a known one."""
    make_admin(db, email="existe@example.com")
    limit = settings.login_max_attempts_per_account

    def exhaust(email: str) -> dict:
        for _ in range(limit):
            client.post("/auth/login", json={"email": email, "password": "incorrecta"})
        response = client.post("/auth/login", json={"email": email, "password": "incorrecta"})
        return {"status": response.status_code, "body": response.json(), "headers": dict(response.headers)}

    known = exhaust("existe@example.com")
    from app.api.routes.auth import reset_rate_limiters

    reset_rate_limiters()
    unknown = exhaust("noexiste@example.com")

    assert known["status"] == unknown["status"] == 429
    assert known["body"] == unknown["body"]
    detail = known["body"]["detail"].lower()
    for leak in ("usuario", "email", "existe", "password", "contrasena"):
        assert leak not in detail, f"the message must not mention {leak}"


def test_a_refusal_tells_the_client_when_to_retry(client, db):
    make_admin(db, email="reintento@example.com")
    for _ in range(settings.login_max_attempts_per_account + 1):
        response = client.post(
            "/auth/login", json={"email": "reintento@example.com", "password": "mala"}
        )
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0


def test_a_legitimate_user_is_not_locked_out_by_earlier_typos(client, db):
    """The count for an account is cleared once its owner proves ownership."""
    make_admin(db, email="dueno@example.com")
    limit = settings.login_max_attempts_per_account

    for _ in range(limit - 1):
        client.post("/auth/login", json={"email": "dueno@example.com", "password": "mala"})

    good = client.post("/auth/login", json={"email": "dueno@example.com", "password": "Admin1234"})
    assert good.status_code == 200

    # The window was reset, so there is room to get it wrong again.
    again = client.post("/auth/login", json={"email": "dueno@example.com", "password": "mala"})
    assert again.status_code == 401


def test_attacking_many_accounts_from_one_address_is_also_capped(client, db):
    """Spreading the guesses across mailboxes must not dodge the limit."""
    make_admin(db, email="a@example.com")
    per_ip = settings.login_max_attempts_per_ip

    refused = 0
    for index in range(per_ip + 5):
        response = client.post(
            "/auth/login", json={"email": f"objetivo{index}@example.com", "password": "mala"}
        )
        if response.status_code == 429:
            refused += 1
    assert refused > 0, "the per-address window must eventually bite"


def test_a_successful_login_still_returns_a_token(client, db):
    make_admin(db, email="ok@example.com")
    response = client.post("/auth/login", json={"email": "ok@example.com", "password": "Admin1234"})
    assert response.status_code == 200
    assert response.json()["access_token"]


# --- 3. forgot password abuse ----------------------------------------------


def test_forgot_password_is_rate_limited(client, db):
    make_admin(db, email="olvide@example.com")
    limit = settings.forgot_password_max_per_account

    codes = [
        client.post("/auth/forgot-password", json={"email": "olvide@example.com"}).status_code
        for _ in range(limit + 3)
    ]
    assert codes[:limit] == [200] * limit
    assert set(codes[limit:]) == {429}


def test_forgot_password_answers_the_same_for_known_and_unknown_addresses(client, db):
    make_admin(db, email="conocido@example.com")

    known = client.post("/auth/forgot-password", json={"email": "conocido@example.com"})
    unknown = client.post("/auth/forgot-password", json={"email": "nadie@example.com"})

    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json() == {"status": "ok"}


def test_being_rate_limited_does_not_reveal_whether_the_address_exists(client, db):
    """The limiter runs before the lookup, so both are refused identically."""
    make_admin(db, email="existe2@example.com")
    limit = settings.forgot_password_max_per_account
    from app.api.routes.auth import reset_rate_limiters

    def exhaust(email: str):
        for _ in range(limit):
            client.post("/auth/forgot-password", json={"email": email})
        return client.post("/auth/forgot-password", json={"email": email})

    known = exhaust("existe2@example.com")
    reset_rate_limiters()
    unknown = exhaust("fantasma@example.com")

    assert known.status_code == unknown.status_code == 429
    assert known.json() == unknown.json()


# --- 4. the reset token never reaches a log --------------------------------


def _captured_logs(client, email: str) -> tuple[str, str]:
    """Run a reset and return (log output, stdout)."""
    import contextlib

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("datacenter.auth")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    stdout = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout):
            client.post("/auth/forgot-password", json={"email": email})
    finally:
        logger.removeHandler(handler)
    return stream.getvalue(), stdout.getvalue()


def test_no_reset_token_or_link_reaches_the_logs(client, db):
    user, _ = make_admin(db, email="secreto@example.com")
    logged, printed = _captured_logs(client, "secreto@example.com")

    db.expire_all()
    refreshed = db.query(type(user)).filter_by(id=user.id).one()
    assert refreshed.reset_token_hash, "the reset really was issued"

    combined = logged + printed
    assert "reset-password?token=" not in combined
    assert "token=" not in combined
    assert not re.search(r"[A-Za-z0-9_-]{40,}", combined), "no token-length string may appear"


def test_the_log_records_that_a_reset_happened(client, db):
    make_admin(db, email="rastro@example.com")
    logged, _ = _captured_logs(client, "rastro@example.com")
    assert "password reset issued" in logged


def test_the_logged_address_is_masked(client, db):
    make_admin(db, email="rastro2@example.com")
    from app.api.routes.auth import _mask_email

    masked = _mask_email("rastro2@example.com")
    assert masked.endswith("@example.com")
    assert "rastro2" not in masked


def test_the_local_link_file_is_off_by_default():
    """It writes a working token to disk; production must never enable it."""
    assert settings.reset_link_to_logs is False
    assert build_settings(environment="production", reset_link_to_logs=True).reset_link_logging_enabled is False
    assert build_settings(environment="development", reset_link_to_logs=True).reset_link_logging_enabled is True


def test_reset_password_still_works_end_to_end(client, db):
    """The token is unusable from the logs, and perfectly usable by its owner."""
    from app.api.routes.auth import _hash_reset_token
    from app.models.user import User

    user, _ = make_admin(db, email="flujo@example.com")
    assert client.post("/auth/forgot-password", json={"email": "flujo@example.com"}).status_code == 200

    # Stand in for the email the user would receive.
    db.expire_all()
    stored = db.query(User).filter(User.id == user.id).one()
    assert stored.reset_token_hash

    token = "un-token-de-prueba-suficientemente-largo"
    stored.reset_token_hash = _hash_reset_token(token)
    db.commit()

    response = client.post(
        "/auth/reset-password",
        json={"email": "flujo@example.com", "token": token, "password": "NuevaClave1"},
    )
    assert response.status_code == 200
    assert client.post(
        "/auth/login", json={"email": "flujo@example.com", "password": "NuevaClave1"}
    ).status_code == 200


# --- the limiter itself -----------------------------------------------------


def test_the_limiter_allows_up_to_the_limit_then_refuses():
    limiter = SlidingWindowLimiter(limit=3, window_seconds=60)
    for _ in range(3):
        limiter.hit("k")
    with pytest.raises(RateLimitExceeded):
        limiter.hit("k")


def test_the_limiter_keys_are_independent():
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
    limiter.hit("a")
    limiter.hit("b")  # must not raise
    with pytest.raises(RateLimitExceeded):
        limiter.hit("a")


def test_clearing_a_key_frees_its_allowance():
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
    limiter.hit("k")
    limiter.clear("k")
    limiter.hit("k")


def test_an_unidentifiable_client_is_allowed_rather_than_blocking_everyone():
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
    for _ in range(5):
        limiter.hit(None)  # must not raise


def test_a_limit_of_zero_disables_the_limiter():
    limiter = SlidingWindowLimiter(limit=0, window_seconds=60)
    for _ in range(50):
        limiter.hit("k")


def test_the_window_slides(monkeypatch):
    import app.services.rate_limit as module

    clock = {"now": 1000.0}
    monkeypatch.setattr(module.time, "time", lambda: clock["now"])

    limiter = SlidingWindowLimiter(limit=2, window_seconds=60)
    limiter.hit("k")
    limiter.hit("k")
    with pytest.raises(RateLimitExceeded):
        limiter.hit("k")

    clock["now"] += 61  # the first two fall out of the window
    limiter.hit("k")


def test_keys_are_hashed_so_addresses_are_not_held_in_the_clear():
    key = hash_key("203.0.113.7", "persona@example.com")
    assert key and len(key) == 64
    assert "203.0.113.7" not in key
    assert "persona@example.com" not in key
    # Same inputs, same bucket; case and spacing do not create a new one.
    assert key == hash_key(" 203.0.113.7 ", "Persona@Example.com")
    assert hash_key(None, None) is None


def test_the_forwarded_header_is_preferred_over_the_socket_address():
    class FakeClient:
        host = "10.0.0.1"

    class FakeRequest:
        headers = {"x-forwarded-for": "203.0.113.7, 10.0.0.1"}
        client = FakeClient()

    assert client_ip(FakeRequest()) == "203.0.113.7"

    class NoHeader:
        headers: dict = {}
        client = FakeClient()

    assert client_ip(NoHeader()) == "10.0.0.1"


# --- 5. ephemeral storage fails explicitly ---------------------------------


def test_a_dataset_whose_file_vanished_reports_why(client, db):
    """A restart on ephemeral storage leaves the row and loses the file."""
    import os

    from app.models.dataset import Dataset

    _, token = make_admin(db)
    created = client.post(
        "/datasets", json={"name": "perdido", "domain": "ecommerce"}, headers=auth(token)
    )
    dataset_id = created.json()["id"]
    body = b"order_id,price\nA1,100\nA2,200\n"
    client.post(
        f"/datasets/{dataset_id}/upload",
        files={"file": ("d.csv", body, "text/csv")},
        headers=auth(token),
    )

    db.expire_all()
    stored = db.query(Dataset).filter(Dataset.id == dataset_id).one()
    os.remove(stored.file_path)  # what a redeploy does

    for response in (
        client.get(f"/datasets/{dataset_id}/preview", headers=auth(token)),
        client.post(f"/datasets/{dataset_id}/run-quality", headers=auth(token)),
    ):
        # 409, not 404: the dataset exists, its bytes do not.
        assert response.status_code == 409
        detail = response.json()["detail"].lower()
        assert "instancia" in detail, "the message must name the cause"
        assert "volve a subir" in detail, "and say what to do about it"


def test_a_dataset_that_never_had_a_file_is_still_a_404(client, db):
    _, token = make_admin(db)
    created = client.post(
        "/datasets", json={"name": "vacio", "domain": "ecommerce"}, headers=auth(token)
    )
    dataset_id = created.json()["id"]
    assert client.post(f"/datasets/{dataset_id}/run-quality", headers=auth(token)).status_code == 404


def test_demo_datasets_are_unaffected_because_they_live_in_the_database(client, db):
    from conftest import start_demo

    token, _ = start_demo(client)
    dataset_id = client.get("/datasets", headers=auth(token)).json()[0]["id"]
    # No filesystem involved: this keeps working across restarts.
    assert client.get(f"/datasets/{dataset_id}/preview", headers=auth(token)).status_code == 200
    assert client.post(f"/datasets/{dataset_id}/run-quality", headers=auth(token)).status_code == 200


# --- 7. the generator is reproducible --------------------------------------


def test_the_same_seed_produces_the_same_dataset():
    from app.services.data_generator import generate_dataset_csv

    assert generate_dataset_csv(300, 0.12, seed=7) == generate_dataset_csv(300, 0.12, seed=7)


def test_different_seeds_produce_different_datasets():
    from app.services.data_generator import generate_dataset_csv

    assert generate_dataset_csv(300, 0.12, seed=7) != generate_dataset_csv(300, 0.12, seed=8)


def test_identifiers_and_dates_are_seeded_too():
    """Both used to bypass random.seed: uuid4 and utcnow."""
    import csv as _csv

    from app.services.data_generator import generate_dataset_csv

    a = list(_csv.DictReader(io.StringIO(generate_dataset_csv(120, 0.12, seed=11))))
    b = list(_csv.DictReader(io.StringIO(generate_dataset_csv(120, 0.12, seed=11))))

    assert [r["order_id"] for r in a] == [r["order_id"] for r in b]
    assert [r["shipped_at"] for r in a] == [r["shipped_at"] for r in b]
    assert [r["delivered_at"] for r in a] == [r["delivered_at"] for r in b]


def test_identifiers_are_unique_within_a_dataset():
    import csv as _csv

    from app.services.data_generator import generate_dataset_csv

    rows = list(_csv.DictReader(io.StringIO(generate_dataset_csv(500, 0.12, seed=13))))
    assert len({r["order_id"] for r in rows}) == len(rows)


def test_the_injections_are_reproducible():
    from app.services.data_generator import generate_dataset_csv

    first: list[dict] = []
    second: list[dict] = []
    generate_dataset_csv(200, 0.12, seed=17, labels=first)
    generate_dataset_csv(200, 0.12, seed=17, labels=second)
    assert first == second


def test_a_caller_can_still_anchor_the_dates_to_a_chosen_moment():
    import csv as _csv
    from datetime import datetime

    from app.services.data_generator import generate_dataset_csv

    text = generate_dataset_csv(30, 0.0, seed=3, reference_date=datetime(2030, 6, 15))
    rows = list(_csv.DictReader(io.StringIO(text)))
    assert all(row["shipped_at"].startswith("2030-0") for row in rows)


def test_anomaly_evaluation_still_works_on_the_deterministic_generator():
    """The ground truth harness must survive the change."""
    import csv as _csv

    from app.services.data_generator import OUTLIER_INJECTIONS, generate_dataset_csv
    from app.services.data_quality import run_anomaly_detection

    labels: list[dict] = []
    rows = list(
        _csv.DictReader(io.StringIO(generate_dataset_csv(600, 0.12, seed=19, labels=labels)))
    )
    injected = sum(
        1 for label in labels for kind in label["injected"] if kind in OUTLIER_INJECTIONS
    )
    assert injected > 0
    result = run_anomaly_detection(rows, domain="ecommerce-logistica")
    assert result["anomaly_count"] > 0
    assert result["threshold"] == 3.5


# --- 8. the dashboard tells the two blank cases apart ----------------------


def test_dataset_health_reports_the_schema_status(client, db):
    from app.models.dataset import Dataset

    _, token = make_admin(db)
    db.add(
        Dataset(
            name="incompatible",
            domain="ecommerce",
            last_run_at=__import__("datetime").datetime.utcnow(),
            quality_summary={
                "schema": {"status": "incompatible"},
                "summary": {"schema_status": "incompatible", "total_rows": 50},
                "issues": [],
            },
        )
    )
    db.add(
        Dataset(
            name="nunca-analizado",
            domain="ecommerce",
            quality_summary=None,
        )
    )
    db.commit()

    health = {
        item["name"]: item
        for item in client.get("/dashboard/insights", headers=auth(token)).json()["dataset_health"]
    }

    # Both have no score, and the reason is now distinguishable.
    assert health["incompatible"]["score"] is None
    assert health["incompatible"]["schema_status"] == "incompatible"
    assert health["nunca-analizado"]["score"] is None
    assert health["nunca-analizado"]["schema_status"] is None


def test_a_compatible_dataset_reports_its_status_and_score(client, db):
    _, token = make_admin(db)
    created = client.post(
        "/datasets", json={"name": "sano", "domain": "ecommerce"}, headers=auth(token)
    )
    dataset_id = created.json()["id"]
    header = "order_id,customer_id,sku,price,quantity,stock,address,city,postal_code,channel,payment_method,discount_pct\n"
    body = header + "".join(
        f"A{i},C1,S1,100,2,10,Calle 123 numero 4,CABA,1425,web,card,10\n" for i in range(12)
    )
    client.post(
        f"/datasets/{dataset_id}/upload",
        files={"file": ("d.csv", body.encode(), "text/csv")},
        headers=auth(token),
    )
    client.post(f"/datasets/{dataset_id}/run-quality", headers=auth(token))

    health = client.get("/dashboard/insights", headers=auth(token)).json()["dataset_health"][0]
    assert health["schema_status"] == "compatible"
    assert health["score"] == 100.0
