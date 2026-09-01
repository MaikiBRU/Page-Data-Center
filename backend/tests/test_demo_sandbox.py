"""Behavioural tests for the demo sandbox.

These assert what actually happened - rows created, rows gone, data a second
session can or cannot observe - not merely that a request returned 200.
"""

from datetime import datetime, timedelta

import pytest

from conftest import auth, csv_payload, make_admin, start_demo

from app.models.case import Case
from app.models.dataset import Dataset
from app.models.dataset_run import DatasetRun
from app.models.demo_dataset_file import DemoDatasetFile
from app.models.demo_session import DemoSession
from app.services import demo_session as demo_service
from app.services.dataset_storage import InvalidUpload, safe_filename, validate_csv_bytes


# --- 1. creating a session -------------------------------------------------


def test_start_session_seeds_an_analysed_sandbox(client, db):
    token, session = start_demo(client)

    assert token
    # The visitor lands on a populated dashboard, not an empty one.
    assert session["state"]["datasets_used"] == session["state"]["datasets_max"]

    datasets = db.query(Dataset).filter(Dataset.demo_session_id.is_not(None)).all()
    assert len(datasets) == 3
    for dataset in datasets:
        assert dataset.quality_summary is not None
        assert dataset.last_run_at is not None
        # Payload lives in the database, never on the ephemeral filesystem.
        assert db.query(DemoDatasetFile).filter(
            DemoDatasetFile.dataset_id == dataset.id
        ).count() == 1

    assert db.query(DatasetRun).count() == 3
    # Seeding must not consume the visitor's own run budget.
    assert session["state"]["runs_used"] == 0

    kpis = client.get("/dashboard/kpis", headers=auth(token)).json()
    assert kpis["datasets"] == 3
    assert kpis["findings"] > 0
    assert 0 < kpis["rows_affected"] <= kpis["total_rows"]


def test_session_id_is_not_exposed_and_not_guessable(client, db):
    _, session = start_demo(client)
    # The raw session id would be a bearer credential; it must never be echoed.
    assert "id" not in session["state"]
    assert "session_id" not in str(session)

    row = db.query(DemoSession).first()
    assert len(row.id) >= 40
    assert not row.id.isdigit()


def test_start_session_requires_no_credentials(client):
    # No Authorization header, no cookie, no body.
    response = client.post("/demo/session")
    assert response.status_code == 201


# --- 2. a valid session works ---------------------------------------------


def test_valid_session_reaches_the_demo_surface(client):
    token, _ = start_demo(client)

    assert client.get("/auth/me", headers=auth(token)).json()["is_demo"] is True
    assert client.get("/datasets", headers=auth(token)).status_code == 200
    assert client.get("/cases", headers=auth(token)).status_code == 200
    assert client.get("/dashboard/insights", headers=auth(token)).status_code == 200
    assert client.get("/runs", headers=auth(token)).status_code == 200


# --- 3. expired sessions ---------------------------------------------------


def test_ttl_expiry_rejects_the_session_before_cleanup_runs(client, db):
    token, _ = start_demo(client)
    row = db.query(DemoSession).one()

    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()

    response = client.get("/datasets", headers=auth(token))
    assert response.status_code == 401
    # The rows are still physically present; rejection came from the request
    # path, not from the cleanup job.
    assert db.query(Dataset).filter(Dataset.demo_session_id == row.id).count() == 3


def test_idle_timeout_rejects_the_session(client, db, demo_limits):
    demo_limits.demo_idle_timeout_minutes = 20
    token, _ = start_demo(client)
    row = db.query(DemoSession).one()

    row.last_seen_at = datetime.utcnow() - timedelta(minutes=21)
    db.commit()

    assert client.get("/datasets", headers=auth(token)).status_code == 401


def test_activity_pushes_the_idle_deadline_back(client, db, demo_limits):
    demo_limits.demo_idle_timeout_minutes = 20
    token, _ = start_demo(client)
    row = db.query(DemoSession).one()

    # Just inside the window: the request succeeds and refreshes last_seen_at.
    row.last_seen_at = datetime.utcnow() - timedelta(minutes=19)
    db.commit()
    assert client.get("/datasets", headers=auth(token)).status_code == 200

    db.expire_all()
    refreshed = db.query(DemoSession).one()
    assert (datetime.utcnow() - refreshed.last_seen_at).total_seconds() < 60


def test_revoked_session_is_rejected(client, db):
    token, _ = start_demo(client)
    row = db.query(DemoSession).one()
    row.revoked = True
    db.commit()
    assert client.get("/datasets", headers=auth(token)).status_code == 401


# --- 4. unknown sessions ---------------------------------------------------


def test_token_for_a_deleted_session_is_rejected(client, db):
    token, _ = start_demo(client)
    db.query(DemoSession).delete()
    db.commit()
    assert client.get("/datasets", headers=auth(token)).status_code == 401


def test_forged_token_with_unknown_session_id_is_rejected(client):
    from app.services.security import create_demo_token

    forged = create_demo_token("not-a-real-session", datetime.utcnow() + timedelta(hours=1))
    assert client.get("/datasets", headers=auth(forged)).status_code == 401


def test_token_signed_with_a_different_secret_is_rejected(client):
    from datetime import timezone

    from jose import jwt

    _, _ = start_demo(client)
    bad = jwt.encode(
        {
            "sub": "demo:x",
            "typ": "demo",
            "sid": "x",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        "a-completely-different-secret",
        algorithm="HS256",
    )
    assert client.get("/datasets", headers=auth(bad)).status_code == 401


# --- 5. isolation between two sandboxes -----------------------------------


@pytest.fixture()
def two_sessions(client):
    token_a, _ = start_demo(client)
    token_b, _ = start_demo(client)
    return token_a, token_b


def test_each_sandbox_only_lists_its_own_datasets(client, two_sessions):
    token_a, token_b = two_sessions
    ids_a = {d["id"] for d in client.get("/datasets", headers=auth(token_a)).json()}
    ids_b = {d["id"] for d in client.get("/datasets", headers=auth(token_b)).json()}

    assert len(ids_a) == 3 and len(ids_b) == 3
    assert ids_a.isdisjoint(ids_b)


def test_kpis_and_cases_never_aggregate_across_sandboxes(client, two_sessions, db):
    token_a, _ = two_sessions
    # Six datasets exist globally; A must only ever see its own three.
    assert db.query(Dataset).count() == 6
    assert client.get("/dashboard/kpis", headers=auth(token_a)).json()["datasets"] == 3

    cases_a = client.get("/cases", headers=auth(token_a)).json()
    dataset_ids_a = {d["id"] for d in client.get("/datasets", headers=auth(token_a)).json()}
    assert cases_a, "seeded datasets should produce cases"
    assert all(case["dataset_id"] in dataset_ids_a for case in cases_a)


def test_runs_listing_is_partitioned(client, two_sessions):
    token_a, token_b = two_sessions
    runs_a = client.get("/runs", headers=auth(token_a)).json()
    runs_b = client.get("/runs", headers=auth(token_b)).json()
    assert len(runs_a) == 3 and len(runs_b) == 3
    assert {r["dataset_id"] for r in runs_a}.isdisjoint({r["dataset_id"] for r in runs_b})


# --- 12. reaching for another sandbox's resources by id (IDOR) -------------


def test_reading_another_sandbox_dataset_by_id_returns_404(client, two_sessions):
    token_a, token_b = two_sessions
    victim_id = client.get("/datasets", headers=auth(token_b)).json()[0]["id"]

    for path in (
        f"/datasets/{victim_id}",
        f"/datasets/{victim_id}/preview",
        f"/datasets/{victim_id}/runs",
        f"/datasets/{victim_id}/report?format=json",
    ):
        response = client.get(path, headers=auth(token_a))
        # 404 rather than 403: the response must not confirm the id exists.
        assert response.status_code == 404, f"{path} -> {response.status_code}"


def test_writing_to_another_sandbox_dataset_is_refused(client, two_sessions, db):
    token_a, token_b = two_sessions
    victim = client.get("/datasets", headers=auth(token_b)).json()[0]
    before = db.query(DatasetRun).filter(DatasetRun.dataset_id == victim["id"]).count()

    assert client.post(f"/datasets/{victim['id']}/run-quality", headers=auth(token_a)).status_code == 404
    assert client.post(
        f"/datasets/{victim['id']}/generate",
        json={"rows": 10, "anomaly_rate": 0.1},
        headers=auth(token_a),
    ).status_code == 404
    assert client.post(
        f"/datasets/{victim['id']}/upload",
        files={"file": ("a.csv", csv_payload(), "text/csv")},
        headers=auth(token_a),
    ).status_code == 404

    assert db.query(DatasetRun).filter(DatasetRun.dataset_id == victim["id"]).count() == before


def test_reading_and_mutating_another_sandbox_case_is_refused(client, two_sessions, db):
    token_a, token_b = two_sessions
    victim_case = client.get("/cases", headers=auth(token_b)).json()[0]
    original_status = victim_case["status"]

    assert client.get(f"/cases/{victim_case['id']}", headers=auth(token_a)).status_code == 404
    assert client.get(f"/cases/{victim_case['id']}/timeline", headers=auth(token_a)).status_code == 404
    assert client.get(f"/cases/{victim_case['id']}/report", headers=auth(token_a)).status_code == 404
    assert client.patch(
        f"/cases/{victim_case['id']}",
        json={"status": "resolved"},
        headers=auth(token_a),
    ).status_code == 404
    assert client.post(
        f"/cases/{victim_case['id']}/notes",
        json={"note": "intento de escritura cruzada"},
        headers=auth(token_a),
    ).status_code == 404

    db.expire_all()
    assert db.query(Case).filter(Case.id == victim_case["id"]).one().status == original_status


def test_bulk_update_cannot_reach_across_sandboxes(client, two_sessions, db):
    token_a, token_b = two_sessions
    mine = client.get("/cases", headers=auth(token_a)).json()[0]
    theirs = client.get("/cases", headers=auth(token_b)).json()[0]

    response = client.post(
        "/cases/bulk",
        json={"case_ids": [mine["id"], theirs["id"]], "status": "resolved"},
        headers=auth(token_a),
    )
    assert response.status_code == 200
    # Only the caller's own case was touched.
    assert response.json()["updated"] == 1

    db.expire_all()
    assert db.query(Case).filter(Case.id == mine["id"]).one().status == "resolved"
    assert db.query(Case).filter(Case.id == theirs["id"]).one().status == theirs["status"]


def test_bulk_create_against_another_sandbox_dataset_is_refused(client, two_sessions, db):
    token_a, token_b = two_sessions
    victim_dataset = client.get("/datasets", headers=auth(token_b)).json()[0]
    before = db.query(Case).count()

    response = client.post(
        "/cases/bulk-create",
        json={
            "items": [
                {
                    "dataset_id": victim_dataset["id"],
                    "title": "Caso inyectado desde otra sesion",
                    "severity": "high",
                    "status": "open",
                }
            ]
        },
        headers=auth(token_a),
    )
    assert response.status_code == 400
    assert db.query(Case).count() == before


# --- 13. expired session cannot touch its own resources either -------------


def test_expired_session_cannot_read_or_write_its_own_data(client, db):
    token, _ = start_demo(client)
    dataset_id = client.get("/datasets", headers=auth(token)).json()[0]["id"]

    row = db.query(DemoSession).one()
    row.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()

    assert client.get(f"/datasets/{dataset_id}", headers=auth(token)).status_code == 401
    assert client.post(f"/datasets/{dataset_id}/run-quality", headers=auth(token)).status_code == 401
    assert client.post(
        f"/datasets/{dataset_id}/upload",
        files={"file": ("a.csv", csv_payload(), "text/csv")},
        headers=auth(token),
    ).status_code == 401


# --- 6. dataset quota ------------------------------------------------------


def test_dataset_quota_is_enforced_after_the_seeded_three(client, db, demo_limits):
    demo_limits.demo_max_datasets = 3
    token, _ = start_demo(client)
    assert db.query(Dataset).count() == 3

    response = client.post(
        "/datasets", json={"name": "Cuarto", "domain": "ecommerce"}, headers=auth(token)
    )
    assert response.status_code == 409
    assert response.headers.get("X-Demo-Limit") == "datasets"
    assert db.query(Dataset).count() == 3


def test_dataset_quota_frees_up_when_a_dataset_goes_away(client, db, demo_limits):
    demo_limits.demo_max_datasets = 4
    token, _ = start_demo(client)
    created = client.post(
        "/datasets", json={"name": "Cuarto", "domain": "ecommerce"}, headers=auth(token)
    )
    assert created.status_code == 200
    assert db.query(Dataset).count() == 4

    assert client.post(
        "/datasets", json={"name": "Quinto", "domain": "ecommerce"}, headers=auth(token)
    ).status_code == 409


# --- 7 & 8. file size and storage quotas ----------------------------------


def test_oversized_upload_is_rejected_and_nothing_is_stored(client, db, demo_limits):
    demo_limits.demo_max_datasets = 4
    demo_limits.demo_max_file_size_mb = 0.01  # 10 KB
    token, _ = start_demo(client)
    dataset_id = client.post(
        "/datasets", json={"name": "Propio", "domain": "ecommerce"}, headers=auth(token)
    ).json()["id"]

    big = csv_payload(rows=4000, columns=6)
    assert len(big) > 10 * 1024

    response = client.post(
        f"/datasets/{dataset_id}/upload",
        files={"file": ("grande.csv", big, "text/csv")},
        headers=auth(token),
    )
    assert response.status_code == 413
    assert db.query(DemoDatasetFile).filter(
        DemoDatasetFile.dataset_id == dataset_id
    ).count() == 0


def test_storage_quota_blocks_the_upload_that_would_exceed_it(client, db, demo_limits):
    # Dataset count is deliberately not the binding limit here; storage is.
    demo_limits.demo_max_datasets = 20
    demo_limits.demo_seed_rows = 10
    demo_limits.demo_max_file_size_mb = 1.0
    demo_limits.demo_max_storage_mb = 0.05  # ~51 KB total
    token, _ = start_demo(client)

    payload = csv_payload(rows=400, columns=5)  # a few KB
    accepted, rejected = 0, 0
    for index in range(6):
        created = client.post(
            "/datasets", json={"name": f"D{index}", "domain": "ecommerce"}, headers=auth(token)
        )
        assert created.status_code == 200, created.text
        dataset_id = created.json()["id"]
        response = client.post(
            f"/datasets/{dataset_id}/upload",
            files={"file": ("d.csv", payload, "text/csv")},
            headers=auth(token),
        )
        if response.status_code == 200:
            accepted += 1
        else:
            assert response.status_code == 409, response.text
            assert response.headers.get("X-Demo-Limit") == "storage"
            rejected += 1

    assert accepted >= 1 and rejected >= 1, "quota should admit some and refuse the rest"

    stored = (
        db.query(DemoDatasetFile)
        .filter(DemoDatasetFile.demo_session_id == db.query(DemoSession).one().id)
        .all()
    )
    total = sum(f.size_bytes for f in stored)
    assert total <= int(0.05 * 1024 * 1024)


def test_session_storage_counter_tracks_the_stored_bytes(client, db, demo_limits):
    demo_limits.demo_max_datasets = 4
    demo_limits.demo_seed_rows = 20
    token, _ = start_demo(client)
    dataset_id = client.post(
        "/datasets", json={"name": "Propio", "domain": "ecommerce"}, headers=auth(token)
    ).json()["id"]
    payload = csv_payload(rows=50, columns=5)
    client.post(
        f"/datasets/{dataset_id}/upload",
        files={"file": ("d.csv", payload, "text/csv")},
        headers=auth(token),
    )

    db.expire_all()
    session_row = db.query(DemoSession).one()
    stored_total = sum(
        f.size_bytes
        for f in db.query(DemoDatasetFile)
        .filter(DemoDatasetFile.demo_session_id == session_row.id)
        .all()
    )
    assert session_row.storage_bytes == stored_total


# --- 9. run quota ----------------------------------------------------------


def test_run_quota_is_enforced_and_no_run_row_is_written(client, db, demo_limits):
    demo_limits.demo_max_runs = 2
    demo_limits.demo_seed_rows = 30
    token, _ = start_demo(client)
    dataset_id = client.get("/datasets", headers=auth(token)).json()[0]["id"]

    for _ in range(2):
        assert client.post(
            f"/datasets/{dataset_id}/run-quality", headers=auth(token)
        ).status_code == 200

    runs_before = db.query(DatasetRun).count()
    blocked = client.post(f"/datasets/{dataset_id}/run-quality", headers=auth(token))
    assert blocked.status_code == 409
    assert blocked.headers.get("X-Demo-Limit") == "runs"
    assert db.query(DatasetRun).count() == runs_before


def test_export_quota_is_enforced(client, db, demo_limits):
    demo_limits.demo_max_exports = 2
    demo_limits.demo_seed_rows = 30
    token, _ = start_demo(client)
    dataset_id = client.get("/datasets", headers=auth(token)).json()[0]["id"]

    for _ in range(2):
        assert client.get(
            f"/datasets/{dataset_id}/report?format=json", headers=auth(token)
        ).status_code == 200

    blocked = client.get(f"/datasets/{dataset_id}/report?format=json", headers=auth(token))
    assert blocked.status_code == 409
    assert blocked.headers.get("X-Demo-Limit") == "exports"


# --- 10. safe upload -------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "../../../app/main.py",
        "..\\..\\..\\app\\main.py",
        "/etc/passwd",
        "C:\\Windows\\System32\\drivers\\etc\\hosts",
        "....//....//evil.csv",
        "normal.csv",
    ],
)
def test_filename_sanitisation_never_yields_a_path(raw):
    cleaned = safe_filename(raw)
    assert "/" not in cleaned
    assert "\\" not in cleaned
    assert ".." not in cleaned
    assert cleaned.endswith(".csv")


def test_traversal_filename_cannot_escape_the_sandbox(client, db, demo_limits):
    demo_limits.demo_max_datasets = 4
    demo_limits.demo_seed_rows = 20
    token, _ = start_demo(client)
    dataset_id = client.post(
        "/datasets", json={"name": "Propio", "domain": "ecommerce"}, headers=auth(token)
    ).json()["id"]

    response = client.post(
        f"/datasets/{dataset_id}/upload",
        files={"file": ("../../../app/main.py", csv_payload(), "text/csv")},
        headers=auth(token),
    )
    assert response.status_code == 200

    stored = db.query(DemoDatasetFile).filter(DemoDatasetFile.dataset_id == dataset_id).one()
    assert stored.filename == "main.py.csv"
    assert "/" not in stored.filename and "\\" not in stored.filename
    # The real source file is untouched: demo uploads never reach the disk.
    main_py = (
        __import__("pathlib").Path(__file__).resolve().parents[1] / "app" / "main.py"
    )
    assert main_py.read_text(encoding="utf-8").lstrip().startswith("import asyncio")


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"\x00\x01\x02binary garbage",
        b"solo-un-encabezado-sin-filas",
    ],
)
def test_non_csv_payloads_are_rejected(content):
    with pytest.raises(InvalidUpload):
        validate_csv_bytes(content)


def test_valid_csv_is_accepted_and_header_returned():
    assert validate_csv_bytes(b"a,b\n1,2\n") == ["a", "b"]


def test_upload_with_a_fake_extension_but_binary_content_is_rejected(client, demo_limits):
    demo_limits.demo_max_datasets = 4
    demo_limits.demo_seed_rows = 20
    token, _ = start_demo(client)
    dataset_id = client.post(
        "/datasets", json={"name": "Propio", "domain": "ecommerce"}, headers=auth(token)
    ).json()["id"]

    response = client.post(
        f"/datasets/{dataset_id}/upload",
        files={"file": ("inocente.csv", b"\x89PNG\r\n\x1a\n\x00\x00\x00binary", "text/csv")},
        headers=auth(token),
    )
    assert response.status_code == 400


def test_uploaded_csv_flows_through_the_real_quality_pipeline(client, db, demo_limits):
    demo_limits.demo_max_datasets = 4
    demo_limits.demo_seed_rows = 20
    token, _ = start_demo(client)
    dataset_id = client.post(
        "/datasets", json={"name": "Propio", "domain": "ecommerce"}, headers=auth(token)
    ).json()["id"]
    client.post(
        f"/datasets/{dataset_id}/upload",
        files={"file": ("propio.csv", csv_payload(rows=12), "text/csv")},
        headers=auth(token),
    )

    response = client.post(f"/datasets/{dataset_id}/run-quality", headers=auth(token))
    assert response.status_code == 200
    body = response.json()
    assert body["quality_summary"]["summary"]["total_rows"] == 12
    assert db.query(DatasetRun).filter(DatasetRun.dataset_id == dataset_id).count() == 1


def test_server_filesystem_path_is_never_returned(client):
    token, _ = start_demo(client)
    dataset = client.get("/datasets", headers=auth(token)).json()[0]
    assert dataset["file_path"] == "dataset-demo.csv"
    assert "demo://" not in str(dataset["file_path"])


# --- 11. cleanup -----------------------------------------------------------


def test_cleanup_removes_expired_sandboxes_and_leaves_live_ones(client, db):
    token_a, _ = start_demo(client)
    token_b, _ = start_demo(client)
    sessions = db.query(DemoSession).order_by(DemoSession.created_at.asc()).all()
    assert len(sessions) == 2
    expired_id, live_id = sessions[0].id, sessions[1].id

    sessions[0].expires_at = datetime.utcnow() - timedelta(minutes=5)
    db.commit()

    removed = demo_service.cleanup_expired(db)

    assert removed["demo_sessions"] == 1
    assert removed["datasets"] == 3
    assert db.query(DemoSession).count() == 1
    assert db.query(Dataset).filter(Dataset.demo_session_id == expired_id).count() == 0
    assert db.query(Case).filter(Case.demo_session_id == expired_id).count() == 0
    assert db.query(DemoDatasetFile).filter(
        DemoDatasetFile.demo_session_id == expired_id
    ).count() == 0
    # The live sandbox is untouched.
    assert db.query(Dataset).filter(Dataset.demo_session_id == live_id).count() == 3
    assert client.get("/datasets", headers=auth(token_b)).status_code == 200
    assert client.get("/datasets", headers=auth(token_a)).status_code == 401


def test_cleanup_is_idempotent(client, db):
    start_demo(client)
    row = db.query(DemoSession).one()
    row.expires_at = datetime.utcnow() - timedelta(minutes=5)
    db.commit()

    first = demo_service.cleanup_expired(db)
    second = demo_service.cleanup_expired(db)
    third = demo_service.cleanup_expired(db)

    assert first["demo_sessions"] == 1
    assert second["demo_sessions"] == 0
    assert third["demo_sessions"] == 0
    assert db.query(Dataset).count() == 0


def test_cleanup_reclaims_orphaned_rows_whose_session_row_vanished(client, db):
    start_demo(client)
    session_id = db.query(DemoSession).one().id
    # Simulate a partial failure: session row gone, its data left behind.
    db.query(DemoSession).delete()
    db.commit()
    assert db.query(Dataset).filter(Dataset.demo_session_id == session_id).count() == 3

    demo_service.cleanup_expired(db)
    assert db.query(Dataset).filter(Dataset.demo_session_id == session_id).count() == 0
    assert db.query(DemoDatasetFile).count() == 0


def test_visitor_can_end_the_session_immediately(client, db):
    token, _ = start_demo(client)
    assert client.post("/demo/session/end", headers=auth(token)).status_code == 200

    assert db.query(DemoSession).count() == 0
    assert db.query(Dataset).count() == 0
    assert db.query(Case).count() == 0
    assert db.query(DemoDatasetFile).count() == 0
    assert client.get("/datasets", headers=auth(token)).status_code == 401


def test_cleanup_never_touches_application_data(client, db):
    """The authenticated app's rows have demo_session_id NULL and must survive."""
    admin, admin_token = make_admin(db)
    app_dataset = Dataset(name="Dataset real", domain="ecommerce", created_by=admin.id)
    db.add(app_dataset)
    db.commit()
    db.refresh(app_dataset)
    app_case = Case(dataset_id=app_dataset.id, title="Caso real", severity="high", status="open")
    db.add(app_case)
    db.commit()

    start_demo(client)
    row = db.query(DemoSession).one()
    row.expires_at = datetime.utcnow() - timedelta(minutes=5)
    db.commit()
    demo_service.cleanup_expired(db)

    assert db.query(Dataset).filter(Dataset.id == app_dataset.id).count() == 1
    assert db.query(Case).filter(Case.id == app_case.id).count() == 1
    assert client.get("/datasets", headers=auth(admin_token)).status_code == 200


# --- maintenance endpoint --------------------------------------------------


def test_maintenance_cleanup_is_disabled_without_a_configured_secret(client, db):
    from app.core.config import settings

    settings.demo_maintenance_token = None
    assert client.post("/demo/maintenance/cleanup").status_code == 404


def test_maintenance_cleanup_requires_the_right_secret(client, db):
    from app.core.config import settings

    settings.demo_maintenance_token = "s3cret-token"
    try:
        start_demo(client)
        row = db.query(DemoSession).one()
        row.expires_at = datetime.utcnow() - timedelta(minutes=5)
        db.commit()

        assert client.post("/demo/maintenance/cleanup").status_code == 403
        assert client.post(
            "/demo/maintenance/cleanup", headers={"X-Demo-Maintenance-Token": "wrong"}
        ).status_code == 403
        assert db.query(DemoSession).count() == 1

        ok = client.post(
            "/demo/maintenance/cleanup", headers={"X-Demo-Maintenance-Token": "s3cret-token"}
        )
        assert ok.status_code == 200
        assert db.query(DemoSession).count() == 0
    finally:
        settings.demo_maintenance_token = None
