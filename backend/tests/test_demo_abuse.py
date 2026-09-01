"""Abuse controls around session creation."""

from conftest import auth, start_demo

from app.models.demo_session import DemoSession
from app.services import demo_session as demo_service


def test_session_creation_is_rate_limited_per_client(client, db, demo_limits):
    demo_limits.demo_rate_limit_per_hour = 3
    demo_service.reset_rate_limits()

    accepted = 0
    for _ in range(6):
        response = client.post("/demo/session")
        if response.status_code == 201:
            accepted += 1
        else:
            assert response.status_code == 429, response.text

    assert accepted == 3
    # The refused attempts left nothing behind.
    assert db.query(DemoSession).count() == 3


def test_rate_limit_counts_distinct_clients_separately(client, db, demo_limits):
    demo_limits.demo_rate_limit_per_hour = 2
    demo_service.reset_rate_limits()

    for _ in range(2):
        assert client.post("/demo/session", headers={"X-Forwarded-For": "203.0.113.10"}).status_code == 201
    assert client.post("/demo/session", headers={"X-Forwarded-For": "203.0.113.10"}).status_code == 429

    # A different origin still gets its own budget.
    assert client.post("/demo/session", headers={"X-Forwarded-For": "203.0.113.99"}).status_code == 201


def test_global_capacity_cap_is_enforced(client, db, demo_limits):
    from app.core.config import settings

    demo_service.reset_rate_limits()
    saved = settings.demo_max_active_sessions
    settings.demo_max_active_sessions = 2
    try:
        assert client.post("/demo/session").status_code == 201
        assert client.post("/demo/session").status_code == 201
        overflow = client.post("/demo/session")
        assert overflow.status_code == 503
        assert db.query(DemoSession).count() == 2
    finally:
        settings.demo_max_active_sessions = saved


def test_demo_config_is_public_and_reports_the_limits(client, demo_limits):
    demo_limits.demo_max_datasets = 3
    response = client.get("/demo/config")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["limits"]["max_datasets"] == 3
    assert body["limits"]["session_ttl_minutes"] > 0


def test_demo_can_be_switched_off_entirely(client, db):
    from app.core.config import settings

    settings.demo_enabled = False
    try:
        assert client.post("/demo/session").status_code == 404
        assert client.get("/demo/config").json()["enabled"] is False
        assert db.query(DemoSession).count() == 0
    finally:
        settings.demo_enabled = True


def test_reset_rebuilds_the_sandbox_without_changing_the_session(client, db, demo_limits):
    from app.models.case import Case
    from app.models.dataset import Dataset

    demo_limits.demo_seed_rows = 20
    demo_limits.demo_max_datasets = 4
    token, _ = start_demo(client)
    session_id = db.query(DemoSession).one().id

    # Something the visitor made themselves, which reset must discard.
    extra = client.post(
        "/datasets", json={"name": "Trabajo del visitante", "domain": "ecommerce"},
        headers=auth(token),
    )
    assert extra.status_code == 200
    assert db.query(Dataset).filter(Dataset.demo_session_id == session_id).count() == 4
    cases_before = db.query(Case).filter(Case.demo_session_id == session_id).count()
    assert cases_before > 0

    response = client.post("/demo/session/reset", headers=auth(token))
    assert response.status_code == 200

    db.expire_all()
    # Same session, so the token the browser holds keeps working.
    assert db.query(DemoSession).one().id == session_id
    assert client.get("/datasets", headers=auth(token)).status_code == 200

    # Contents were replaced, not appended to.
    names = {d["name"] for d in client.get("/datasets", headers=auth(token)).json()}
    assert "Trabajo del visitante" not in names
    assert db.query(Dataset).filter(Dataset.demo_session_id == session_id).count() == 3
    assert db.query(Dataset).count() == 3
