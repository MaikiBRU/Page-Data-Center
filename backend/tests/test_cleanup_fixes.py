"""Regression tests for the cleanup phase.

Each test pins a defect that was found and fixed, so it cannot come back
quietly.
"""

import csv
import io

import pytest

from conftest import auth, make_admin

from app.core.config import settings
from app.models.user import User
from app.services.data_generator import generate_dataset_csv
from app.services.data_quality import (
    DEFAULT_DOMAIN,
    DOMAIN_PROFILES,
    UnknownDomainError,
    _profile,
    run_anomaly_detection,
    run_quality_checks,
)
from app.services.quality_run import compute_scores


def clean_row(index: int, **overrides) -> dict:
    row = {
        "order_id": f"A{index}",
        "customer_id": "C1",
        "sku": "S1",
        "price": "100",
        "quantity": "2",
        "stock": "10",
        "address": "Calle 123 numero 4",
        "city": "CABA",
        "postal_code": "1425",
        "channel": "web",
        "payment_method": "card",
        "discount_pct": "10",
    }
    row.update(overrides)
    return row


def codes(issues) -> dict:
    return {(i["code"], i.get("field")): i["count"] for i in issues}


# --- 1. the public sign-up endpoint ----------------------------------------


def test_the_public_signup_endpoint_no_longer_exists(client, db):
    response = client.post(
        "/auth/register", json={"email": "intruso@example.com", "password": "Intruso123"}
    )
    assert response.status_code == 404
    assert db.query(User).filter(User.email == "intruso@example.com").count() == 0


def test_no_unauthenticated_endpoint_can_create_a_user(client, db):
    """The whole point: account creation requires an administrator."""
    from app.main import app as fastapi_app

    before = db.query(User).count()
    public_writes = [
        (route.path, method)
        for route in fastapi_app.routes
        for method in getattr(route, "methods", set())
        if method in {"POST", "PUT", "PATCH"} and not getattr(route, "dependant", None) is None
    ]
    # Exercise every public POST under /auth with a user-shaped payload.
    for path, method in public_writes:
        if not path.startswith("/auth"):
            continue
        client.request(
            method, path, json={"email": "colado@example.com", "password": "Colado1234"}
        )
    assert db.query(User).count() == before
    assert db.query(User).filter(User.email == "colado@example.com").count() == 0


def test_an_administrator_can_still_create_users(client, db):
    _, token = make_admin(db)
    response = client.post(
        "/users",
        json={"email": "analista@example.com", "password": "Analista1", "role": "analyst"},
        headers=auth(token),
    )
    assert response.status_code == 201
    assert db.query(User).filter(User.email == "analista@example.com").count() == 1


def test_password_login_still_works(client, db):
    """Removing sign-up must not touch the sign-in path."""
    user, _ = make_admin(db, email="dueno@example.com")
    response = client.post(
        "/auth/login", json={"email": "dueno@example.com", "password": "Admin1234"}
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_the_demo_sandbox_still_needs_no_account(client, db):
    before = db.query(User).count()
    response = client.post("/demo/session")
    assert response.status_code == 201
    # A sandbox is not a user account.
    assert db.query(User).count() == before


# --- Google sign-in no longer provisions strangers --------------------------


def test_google_signin_does_not_create_an_account_by_default(db):
    from fastapi import HTTPException

    from app.api.routes.auth import _resolve_google_user

    assert settings.google_auto_provision is False
    with pytest.raises(HTTPException) as excinfo:
        _resolve_google_user(db, "cualquiera@gmail.com", "google-123")
    assert excinfo.value.status_code == 403
    assert db.query(User).filter(User.email == "cualquiera@gmail.com").count() == 0


def test_google_signin_authenticates_an_existing_account(db):
    from app.api.routes.auth import _resolve_google_user

    user, _ = make_admin(db, email="conocido@example.com")
    resolved = _resolve_google_user(db, "conocido@example.com", "google-456")
    assert resolved.id == user.id
    assert resolved.google_id == "google-456"


def test_the_allowlist_lets_a_named_address_in(db):
    from app.api.routes.auth import _resolve_google_user

    saved = settings.google_allowed_emails
    settings.google_allowed_emails = "Dueno@Example.com , otro@example.com"
    try:
        created = _resolve_google_user(db, "dueno@example.com", "google-789")
        assert created.id is not None
        assert created.role == "viewer"
    finally:
        settings.google_allowed_emails = saved


def test_an_inactive_user_cannot_sign_in_with_google(db):
    from fastapi import HTTPException

    from app.api.routes.auth import _resolve_google_user

    user, _ = make_admin(db, email="baja@example.com")
    user.is_active = False
    db.commit()
    with pytest.raises(HTTPException) as excinfo:
        _resolve_google_user(db, "baja@example.com", "g")
    assert excinfo.value.status_code == 403


# --- 2. order_id counted once ----------------------------------------------


def test_an_empty_order_id_produces_exactly_one_finding():
    records = [clean_row(i) for i in range(8)] + [clean_row(90, order_id="") for _ in range(2)]
    summary, issues = run_quality_checks(records, domain="ecommerce")

    found = codes(issues)
    assert found.get(("missing_value", "order_id")) == 2
    # The separate `missing_order_id` finding reported the same rows again.
    assert not any(i["code"] == "missing_order_id" for i in issues)


def test_the_three_order_id_conditions_have_distinct_semantics():
    # empty
    empty = run_quality_checks(
        [clean_row(i) for i in range(8)] + [clean_row(0, order_id="") for _ in range(2)],
        domain="ecommerce",
    )[1]
    assert codes(empty).get(("missing_value", "order_id")) == 2
    assert ("duplicate_order_id", None) not in codes(empty)

    # duplicated
    duplicated = run_quality_checks(
        [clean_row(i) for i in range(8)] + [clean_row(1), clean_row(1)], domain="ecommerce"
    )[1]
    assert codes(duplicated).get(("duplicate_order_id", None)) == 2
    assert ("missing_value", "order_id") not in codes(duplicated)


def test_an_absent_order_id_column_is_a_schema_problem_not_a_rule_problem():
    from app.services.schema_check import STATUS_INCOMPATIBLE, check_schema

    records = [{k: v for k, v in clean_row(i).items() if k != "order_id"} for i in range(20)]
    report = check_schema(list(records[0].keys()), records, domain="ecommerce")
    assert report.status == STATUS_INCOMPATIBLE


def test_removing_the_duplicate_does_not_move_the_scores():
    """rows_affected counts rows, so dropping a duplicate finding cannot shift it."""
    records = [clean_row(i) for i in range(8)] + [clean_row(90, order_id="") for _ in range(2)]
    summary, _ = run_quality_checks(records, domain="ecommerce")

    risk, quality = compute_scores(
        summary["rows_affected"], summary["critical_rows"], summary["total_rows"]
    )
    assert summary["rows_affected"] == 2
    assert summary["critical_rows"] == 2  # a missing order_id is high severity
    assert quality == 80.0
    assert risk == 20.0


def test_duplicate_detection_still_works_with_empty_ids_present():
    """Empty ids must not be treated as duplicates of each other."""
    records = [clean_row(i) for i in range(5)] + [clean_row(0, order_id="") for _ in range(3)]
    _, issues = run_quality_checks(records, domain="ecommerce")
    assert ("duplicate_order_id", None) not in codes(issues)


# --- 3. invalid_address -----------------------------------------------------


@pytest.mark.parametrize(
    "address",
    ["Av 9", "Ruta 8 km 5", "Calle 1", "Sarmiento 1234", "9 de Julio 500", "Mitre 45 piso 2"],
)
def test_legitimate_addresses_are_accepted(address):
    """Short ones included: the old rule rejected anything under six characters."""
    records = [clean_row(i, address=address) for i in range(10)]
    _, issues = run_quality_checks(records, domain="ecommerce")
    assert ("invalid_address", None) not in codes(issues)


@pytest.mark.parametrize("address", ["Sarmiento", "sin numero", "1234", "----"])
def test_addresses_missing_a_street_name_or_a_number_are_rejected(address):
    records = [clean_row(i, address=address) for i in range(10)]
    _, issues = run_quality_checks(records, domain="ecommerce")
    assert codes(issues).get(("invalid_address", None)) == 10


def test_an_empty_address_is_reported_once_as_missing_not_twice():
    records = [clean_row(i) for i in range(7)] + [
        clean_row(50 + i, address="") for i in range(3)
    ]
    summary, issues = run_quality_checks(records, domain="ecommerce")

    found = codes(issues)
    assert found.get(("missing_value", "address")) == 3
    # It used to also fire invalid_address, because "" is shorter than six.
    assert ("invalid_address", None) not in found
    assert summary["rows_affected"] == 3


def test_the_old_length_heuristic_is_gone():
    """A five character address with a name and a number is now accepted."""
    records = [clean_row(i, address="Av 91") for i in range(10)]
    _, issues = run_quality_checks(records, domain="ecommerce")
    assert ("invalid_address", None) not in codes(issues)


# --- 4. unknown domain ------------------------------------------------------


def test_an_unknown_domain_raises_instead_of_silently_defaulting():
    with pytest.raises(UnknownDomainError) as excinfo:
        _profile("marketing")
    assert "marketing" in str(excinfo.value)
    # The message names the domains that do exist.
    for known in DOMAIN_PROFILES:
        assert known in str(excinfo.value)


def test_no_domain_at_all_resolves_to_the_documented_default():
    assert _profile(None) is DOMAIN_PROFILES[DEFAULT_DOMAIN]


@pytest.mark.parametrize("domain", ["ecommerce", "logistica", "ecommerce-logistica"])
def test_every_known_domain_still_resolves(domain):
    assert _profile(domain) is DOMAIN_PROFILES[domain]


def test_the_quality_and_anomaly_entry_points_reject_an_unknown_domain():
    records = [clean_row(i) for i in range(20)]
    with pytest.raises(UnknownDomainError):
        run_quality_checks(records, domain="inventado")
    with pytest.raises(UnknownDomainError):
        run_anomaly_detection(records, domain="inventado")


def test_the_api_rejects_a_dataset_created_with_an_unknown_domain(client, db):
    _, token = make_admin(db)
    response = client.post(
        "/datasets", json={"name": "raro", "domain": "marketing"}, headers=auth(token)
    )
    assert response.status_code == 400
    from app.models.dataset import Dataset

    assert db.query(Dataset).count() == 0


# --- no regression in the generated demo dataset ---------------------------


def test_the_demo_dataset_still_produces_the_same_scores():
    """The deduplication removes findings, never rows, so scores must hold."""
    records = list(csv.DictReader(io.StringIO(generate_dataset_csv(400, 0.12, seed=9001))))
    summary, issues = run_quality_checks(records, domain="ecommerce-logistica")
    risk, quality = compute_scores(
        summary["rows_affected"], summary["critical_rows"], summary["total_rows"]
    )

    # Re-baselined when the generator became fully deterministic: seeding the
    # identifiers and the dates changed which rows get which injection, so the
    # absolute figures moved. What matters is unchanged and asserted below.
    assert summary["total_rows"] == 400
    assert summary["rows_affected"] == 336
    assert summary["critical_rows"] == 122
    assert quality == 16.0
    assert risk == 30.5
    # The duplicate address finding stays gone.
    assert summary["issue_count"] == 13
    assert summary["rule_violations"] == 620
    assert not any(i["code"] == "invalid_address" for i in issues)
    assert not any(i["code"] == "missing_order_id" for i in issues)
