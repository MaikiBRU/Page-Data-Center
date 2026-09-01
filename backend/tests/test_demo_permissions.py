"""The demo sandbox must not reach administration or real user data.

The design relies on ``get_current_user`` refusing demo tokens: any endpoint
that was not deliberately opened to the sandbox keeps using it and therefore
fails closed. These tests pin that behaviour down.
"""

from conftest import auth, make_admin, start_demo

from app.api.deps import PERMISSIONS
from app.models.user import User


def test_user_administration_is_unreachable_from_a_sandbox(client, db):
    make_admin(db)
    token, _ = start_demo(client)

    for method, path in (
        ("get", "/users"),
        ("get", "/users/audit"),
        ("get", "/users/assignable"),
    ):
        response = getattr(client, method)(path, headers=auth(token))
        assert response.status_code == 403, f"{path} -> {response.status_code}"


def test_sandbox_cannot_create_or_modify_users(client, db):
    admin, _ = make_admin(db)
    token, _ = start_demo(client)
    before = db.query(User).count()

    assert client.post(
        "/users",
        json={"email": "intruso@example.com", "password": "Intruso123", "is_admin": True},
        headers=auth(token),
    ).status_code == 403
    assert client.patch(
        f"/users/{admin.id}", json={"is_admin": False}, headers=auth(token)
    ).status_code == 403
    assert client.post(
        f"/users/{admin.id}/reset-password",
        json={"password": "Tomado1234"},
        headers=auth(token),
    ).status_code == 403

    db.expire_all()
    assert db.query(User).count() == before
    assert db.query(User).filter(User.id == admin.id).one().is_admin is True


def test_sandbox_cannot_read_real_user_emails_through_case_assignment(client, db):
    make_admin(db, email="analista.real@example.com")
    token, _ = start_demo(client)

    assert client.get("/users/assignable", headers=auth(token)).status_code == 403

    # Nor should any real address leak through the sandbox's own case data.
    body = client.get("/cases", headers=auth(token)).text
    assert "analista.real@example.com" not in body


def test_seeded_demo_cases_are_never_assigned_to_real_users(client, db):
    make_admin(db, email="persona.real@example.com")
    token, _ = start_demo(client)

    cases = client.get("/cases", headers=auth(token)).json()
    assert cases
    assert all(case["assignee"] is None for case in cases)


def test_global_demo_reset_is_admin_only_and_out_of_reach(client, db):
    token, _ = start_demo(client)
    assert client.post("/dashboard/demo/reset", headers=auth(token)).status_code == 403
    assert client.post("/dashboard/demo/regenerate", headers=auth(token)).status_code == 403


def test_admin_demo_reset_cannot_delete_a_live_sandbox(client, db):
    """A "demo" named sandbox dataset must not be caught by the admin reset."""
    from app.models.dataset import Dataset

    _, admin_token = make_admin(db)
    demo_token, _ = start_demo(client)

    # Name a sandbox dataset so it would match the legacy ILIKE '%demo%' filter.
    sandbox_dataset = (
        db.query(Dataset).filter(Dataset.demo_session_id.is_not(None)).first()
    )
    sandbox_dataset.name = "Pedidos demo"
    db.commit()

    assert client.post("/dashboard/demo/reset", headers=auth(admin_token)).status_code == 200

    db.expire_all()
    assert db.query(Dataset).filter(Dataset.demo_session_id.is_not(None)).count() == 3
    assert client.get("/datasets", headers=auth(demo_token)).status_code == 200


def test_schema_and_routing_configuration_stay_out_of_the_sandbox(client, db):
    token, _ = start_demo(client)
    dataset_id = client.get("/datasets", headers=auth(token)).json()[0]["id"]

    assert client.patch(
        f"/datasets/{dataset_id}/domain", json={"domain": "logistica"}, headers=auth(token)
    ).status_code == 403
    assert client.patch(
        f"/datasets/{dataset_id}/rules", json={"disabled_rules": []}, headers=auth(token)
    ).status_code == 403
    assert client.patch(
        f"/datasets/{dataset_id}/assignment", json={"mode": "round_robin"}, headers=auth(token)
    ).status_code == 403


def test_demo_role_is_not_granted_any_administrative_permission(client):
    """Guards against a future edit quietly adding "demo" to a sensitive action."""
    forbidden = {
        "dataset:edit_domain",
        "dataset:edit_rules",
        "dataset:edit_assignment",
        "dashboard:demo",
        "users:assignable",
    }
    for action in forbidden:
        assert "demo" not in PERMISSIONS[action], f"{action} must not be open to demo"


def test_application_user_never_sees_sandbox_data(client, db):
    """Isolation runs both ways: demo rows stay out of the authenticated app."""
    from app.models.dataset import Dataset

    _, admin_token = make_admin(db)
    start_demo(client)
    assert db.query(Dataset).filter(Dataset.demo_session_id.is_not(None)).count() == 3

    assert client.get("/datasets", headers=auth(admin_token)).json() == []
    assert client.get("/cases", headers=auth(admin_token)).json() == []
    assert client.get("/dashboard/kpis", headers=auth(admin_token)).json()["datasets"] == 0
    assert client.get("/runs", headers=auth(admin_token)).json() == []


def test_application_user_cannot_open_a_sandbox_resource_by_id(client, db):
    from app.models.dataset import Dataset

    _, admin_token = make_admin(db)
    start_demo(client)
    sandbox_id = db.query(Dataset).filter(Dataset.demo_session_id.is_not(None)).first().id

    assert client.get(f"/datasets/{sandbox_id}", headers=auth(admin_token)).status_code == 404
    assert (
        client.post(f"/datasets/{sandbox_id}/run-quality", headers=auth(admin_token)).status_code
        == 404
    )


def test_demo_token_is_refused_by_endpoints_that_require_a_real_user(client, db):
    """The fail-closed property itself."""
    from app.api.deps import get_current_user

    make_admin(db)
    token, _ = start_demo(client)
    # /users/audit depends on get_current_user directly.
    response = client.get("/users/audit", headers=auth(token))
    assert response.status_code == 403
    assert "demo" in response.json()["detail"].lower()
    assert callable(get_current_user)
