"""Behavioural tests for the dashboard metrics.

Each test states the arithmetic it expects, so a change in a formula fails
here with the actual numbers rather than passing because a request returned
200.
"""

from datetime import datetime, timedelta

import pytest

from conftest import auth, make_admin

from app.models.dataset import Dataset
from app.models.dataset_run import DatasetRun
from app.services.data_quality import run_quality_checks, severity_for
from app.services.quality_run import compute_scores, rule_violations


# --------------------------------------------------------------- helpers ---


def clean_row(**overrides) -> dict:
    """A row that violates no rule of the ecommerce profile."""
    row = {
        "order_id": "A1",
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


def analyse(records, domain="ecommerce"):
    summary, issues = run_quality_checks(records, domain=domain)
    risk, quality = compute_scores(
        summary["rows_affected"], summary["critical_rows"], summary["total_rows"]
    )
    return summary, issues, risk, quality


# ----------------------------------------------- definitions of the terms ---


def test_clean_dataset_has_no_findings_and_perfect_quality():
    summary, issues, risk, quality = analyse([clean_row(order_id=f"A{i}") for i in range(10)])

    assert issues == []
    assert summary["issue_count"] == 0
    assert summary["rule_violations"] == 0
    assert summary["rows_affected"] == 0
    assert summary["critical_rows"] == 0
    assert quality == 100.0
    assert risk == 0.0


def test_one_row_breaking_several_rules_counts_as_one_affected_row():
    """The defect this whole change exists for.

    Three of ten rows are broken, and each breaks two rules through two
    mechanisms, so the per-finding counts add up to twelve. Twelve was
    previously divided by ten rows and reported as a quality score of zero on
    a dataset that is 70% clean.
    """
    records = [clean_row(order_id=f"A{i}") for i in range(7)]
    records += [clean_row(order_id=f"B{i}", address="", price="") for i in range(3)]

    summary, issues, risk, quality = analyse(records)

    assert summary["total_rows"] == 10
    assert summary["rows_affected"] == 3
    # Three rows x three rules: missing price, missing address, invalid price.
    # Still more firings than rows, which is the point of the metric.
    assert summary["rule_violations"] == 9
    assert summary["rule_violations"] == rule_violations(issues)
    assert summary["issue_count"] == 3
    # Unchanged by the deduplication: both scores count rows, not firings.
    assert quality == 70.0
    assert risk == 30.0


def test_rows_affected_never_exceeds_total_rows():
    # Every row breaks as many rules as possible.
    records = [
        clean_row(
            order_id="",
            price="",
            quantity="0",
            stock="-5",
            address="",
            postal_code="xx",
            channel="unknown",
            payment_method="other",
            discount_pct="99",
        )
        for _ in range(25)
    ]
    summary, _, risk, quality = analyse(records)

    assert summary["rule_violations"] > summary["total_rows"]
    assert summary["rows_affected"] == summary["total_rows"] == 25
    assert quality == 0.0
    assert risk == 100.0


def test_critical_rows_are_a_subset_of_affected_rows():
    records = [clean_row(order_id=f"A{i}") for i in range(5)]
    # discount out of range is medium severity, address missing is high
    records.append(clean_row(order_id="B1", discount_pct="95"))
    records.append(clean_row(order_id="B2", address=""))

    summary, _, risk, quality = analyse(records)

    assert summary["rows_affected"] == 2
    assert summary["critical_rows"] == 1
    assert summary["critical_rows"] <= summary["rows_affected"]
    assert quality == round(100 * (1 - 2 / 7), 1)
    assert risk == round(100 * 1 / 7, 1)


def test_severity_policy_is_declared_in_one_place():
    assert severity_for("missing_value", "address") == "high"
    assert severity_for("missing_value", "customer_id") == "medium"
    assert severity_for("invalid_price") == "high"
    assert severity_for("invalid_discount") == "medium"
    assert severity_for("missing_optional", "warehouse") == "low"


# ------------------------------------------------------------ boundaries ---


@pytest.mark.parametrize(
    "rows_affected,critical_rows,total_rows,expected_quality,expected_risk",
    [
        (0, 0, 100, 100.0, 0.0),
        (100, 100, 100, 0.0, 100.0),
        (50, 25, 100, 50.0, 25.0),
        (1, 0, 3, 66.7, 0.0),
        # Defensive: a caller passing nonsense is clamped, never allowed to
        # produce a score outside the scale.
        (500, 500, 100, 0.0, 100.0),
        (-5, -5, 100, 100.0, 0.0),
    ],
)
def test_scores_stay_inside_the_scale(
    rows_affected, critical_rows, total_rows, expected_quality, expected_risk
):
    risk, quality = compute_scores(rows_affected, critical_rows, total_rows)
    assert 0.0 <= quality <= 100.0
    assert 0.0 <= risk <= 100.0
    assert round(quality, 1) == expected_quality
    assert round(risk, 1) == expected_risk


def test_empty_dataset_produces_zero_and_is_reported_as_unmeasured():
    summary, issues, risk, quality = analyse([])
    assert summary["total_rows"] == 0
    assert summary["rows_affected"] == 0
    assert issues == []
    # Zero here means "nothing to judge"; the API marks such datasets as not
    # measured so the UI can say so instead of showing 0% quality.
    assert (risk, quality) == (0.0, 0.0)


# ------------------------------------------------------- the KPI endpoint ---


def _dataset_with_summary(db, name, total_rows, rows_affected, critical_rows, findings, violations,
                          anomalies=0, last_run=True):
    dataset = Dataset(
        name=name,
        domain="ecommerce",
        source_type="generated",
        last_run_at=datetime.utcnow() if last_run else None,
        quality_summary={
            "summary": {
                "total_rows": total_rows,
                "rows_affected": rows_affected,
                "critical_rows": critical_rows,
                "issue_count": findings,
                "rule_violations": violations,
            },
            "issues": [],
            "recommendations": [],
        },
        anomaly_summary={"anomaly_count": anomalies, "anomalies": []},
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


def test_kpis_aggregate_rows_not_findings(client, db):
    _, token = make_admin(db)
    _dataset_with_summary(db, "A", 100, 30, 10, findings=4, violations=90)
    _dataset_with_summary(db, "B", 100, 10, 2, findings=3, violations=25)

    body = client.get("/dashboard/kpis", headers=auth(token)).json()

    assert body["total_rows"] == 200
    assert body["rows_affected"] == 40
    assert body["rows_affected_pct"] == 20.0
    assert body["critical_rows"] == 12
    assert body["critical_rows_pct"] == 6.0
    assert body["quality_score"] == 80.0
    # Findings and violations are reported separately and never mixed with rows.
    assert body["findings"] == 7
    assert body["rule_violations"] == 115
    assert body["datasets_measured"] == 2


def test_kpis_report_no_monetary_or_invented_fields(client, db):
    _, token = make_admin(db)
    _dataset_with_summary(db, "A", 50, 5, 1, findings=2, violations=9)

    body = client.get("/dashboard/kpis", headers=auth(token)).json()

    for banned in ("impact_estimated", "impact", "risk_level", "week", "issues"):
        assert banned not in body, f"{banned} should no longer be exposed"
    serialised = str(body)
    assert "USD" not in serialised and "US$" not in serialised


def test_kpis_use_the_stored_anomaly_count_not_the_truncated_list(client, db):
    """The stored anomaly list is capped at 50; the count is not."""
    _, token = make_admin(db)
    dataset = _dataset_with_summary(db, "A", 500, 100, 20, findings=3, violations=200)
    dataset.anomaly_summary = {"anomaly_count": 137, "anomalies": [{"field": "price"}] * 50}
    db.commit()

    body = client.get("/dashboard/kpis", headers=auth(token)).json()
    assert body["anomalies"] == 137


def test_datasets_without_row_metrics_are_excluded_not_counted_as_clean(client, db):
    """A run stored before row tracking has no recoverable row figure."""
    _, token = make_admin(db)
    _dataset_with_summary(db, "nuevo", 100, 40, 10, findings=3, violations=120)
    legacy = Dataset(
        name="legacy",
        domain="ecommerce",
        last_run_at=datetime.utcnow(),
        quality_summary={"summary": {"total_rows": 900, "issue_count": 5}, "issues": []},
    )
    db.add(legacy)
    db.commit()

    body = client.get("/dashboard/kpis", headers=auth(token)).json()

    assert body["datasets"] == 2
    assert body["datasets_measured"] == 1
    # The legacy dataset's 900 rows must not dilute the percentage.
    assert body["total_rows"] == 100
    assert body["quality_score"] == 60.0


def test_open_cases_matches_the_cases_page_definition(client, db):
    from app.models.case import Case

    _, token = make_admin(db)
    dataset = _dataset_with_summary(db, "A", 10, 1, 0, findings=1, violations=1)
    for status in ("open", "in_progress", "blocked", "escalated", "backlog", "resolved"):
        db.add(Case(dataset_id=dataset.id, title=f"Caso {status}", severity="high", status=status))
    db.commit()

    kpis = client.get("/dashboard/kpis", headers=auth(token)).json()
    summary = client.get("/cases/summary", headers=auth(token)).json()

    # Five of the six are not resolved.
    assert kpis["open_cases"] == 5
    assert kpis["open_cases"] == summary["open"]


# ------------------------------------------------------------- the trend ---


def _run(db, dataset_id, days_ago, total_rows, rows_affected):
    run = DatasetRun(
        dataset_id=dataset_id,
        run_at=datetime.utcnow() - timedelta(days=days_ago),
        total_rows=total_rows,
        rows_affected=rows_affected,
        critical_rows=0,
        issue_count=1,
        issue_rows=rows_affected,
        anomaly_count=0,
        quality_score=round(100 * (1 - rows_affected / total_rows), 1),
        risk_score=0.0,
    )
    db.add(run)
    db.commit()
    return run


def test_trend_is_null_without_a_previous_run(client, db):
    _, token = make_admin(db)
    dataset = _dataset_with_summary(db, "A", 100, 30, 5, findings=2, violations=40)
    _run(db, dataset.id, days_ago=0, total_rows=100, rows_affected=30)

    body = client.get("/dashboard/kpis", headers=auth(token)).json()
    # One run means no baseline. Previously this produced +100% every time.
    assert body["quality_trend"] is None


def test_trend_compares_a_run_against_the_previous_run_of_the_same_dataset(client, db):
    _, token = make_admin(db)
    dataset = _dataset_with_summary(db, "A", 100, 20, 5, findings=2, violations=40)
    _run(db, dataset.id, days_ago=3, total_rows=100, rows_affected=40)  # older: 60%
    _run(db, dataset.id, days_ago=0, total_rows=100, rows_affected=20)  # latest: 80%

    trend = client.get("/dashboard/kpis", headers=auth(token)).json()["quality_trend"]

    assert trend is not None
    assert trend["previous"] == 60.0
    assert trend["current"] == 80.0
    # Percentage points, not a percent change between two percentages.
    assert trend["delta_points"] == 20.0
    assert trend["datasets_compared"] == 1


def test_trend_can_be_negative(client, db):
    _, token = make_admin(db)
    dataset = _dataset_with_summary(db, "A", 100, 70, 5, findings=2, violations=90)
    _run(db, dataset.id, days_ago=2, total_rows=100, rows_affected=10)
    _run(db, dataset.id, days_ago=0, total_rows=100, rows_affected=70)

    trend = client.get("/dashboard/kpis", headers=auth(token)).json()["quality_trend"]
    assert trend["delta_points"] == -60.0


def test_trend_ignores_runs_recorded_before_row_tracking(client, db):
    _, token = make_admin(db)
    dataset = _dataset_with_summary(db, "A", 100, 30, 5, findings=2, violations=40)
    legacy = _run(db, dataset.id, days_ago=5, total_rows=100, rows_affected=10)
    legacy.rows_affected = None  # pre-migration run
    db.commit()
    _run(db, dataset.id, days_ago=0, total_rows=100, rows_affected=30)

    body = client.get("/dashboard/kpis", headers=auth(token)).json()
    # Only one usable run remains, so there is still no honest comparison.
    assert body["quality_trend"] is None


def test_trend_only_counts_datasets_that_actually_have_two_runs(client, db):
    _, token = make_admin(db)
    paired = _dataset_with_summary(db, "A", 100, 20, 5, findings=2, violations=40)
    lonely = _dataset_with_summary(db, "B", 100, 50, 5, findings=2, violations=40)
    _run(db, paired.id, days_ago=1, total_rows=100, rows_affected=40)
    _run(db, paired.id, days_ago=0, total_rows=100, rows_affected=20)
    _run(db, lonely.id, days_ago=0, total_rows=100, rows_affected=50)

    trend = client.get("/dashboard/kpis", headers=auth(token)).json()["quality_trend"]
    assert trend["datasets_compared"] == 1
    assert trend["current"] == 80.0


# ----------------------------------------------------- dataset health -------


def test_dataset_health_uses_the_same_quality_score(client, db):
    _, token = make_admin(db)
    _dataset_with_summary(db, "sano", 100, 5, 0, findings=1, violations=8)
    _dataset_with_summary(db, "roto", 100, 90, 40, findings=6, violations=300)

    health = client.get("/dashboard/insights", headers=auth(token)).json()["dataset_health"]

    scores = {item["name"]: item["score"] for item in health}
    assert scores["sano"] == 95.0
    assert scores["roto"] == 10.0
    # Worst first: that is the order somebody acting on this needs.
    assert health[0]["name"] == "roto"


def test_dataset_health_reports_null_when_rows_were_never_measured(client, db):
    _, token = make_admin(db)
    legacy = Dataset(
        name="legacy",
        domain="ecommerce",
        last_run_at=datetime.utcnow(),
        quality_summary={"summary": {"total_rows": 100, "issue_count": 4}, "issues": []},
    )
    db.add(legacy)
    db.commit()

    health = client.get("/dashboard/insights", headers=auth(token)).json()["dataset_health"]
    assert health[0]["score"] is None
    assert health[0]["rows_affected"] is None


# ----------------------------------------------- end to end through a run ---


def test_a_real_run_persists_row_metrics_consistent_with_the_summary(client, db):
    """Upload a CSV, run quality, and check the stored run against the summary."""
    _, token = make_admin(db)
    created = client.post(
        "/datasets", json={"name": "Propio", "domain": "ecommerce"}, headers=auth(token)
    )
    assert created.status_code == 200
    dataset_id = created.json()["id"]

    header = "order_id,customer_id,sku,price,quantity,stock,address,city,postal_code,channel,payment_method,discount_pct\n"
    good = "A{i},C1,S1,100,2,10,Calle 123 numero 4,CABA,1425,web,card,10\n"
    bad = "B{i},C1,S1,,2,10,,CABA,1425,web,card,10\n"
    body = header + "".join(good.format(i=i) for i in range(8))
    body += "".join(bad.format(i=i) for i in range(2))

    upload = client.post(
        f"/datasets/{dataset_id}/upload",
        files={"file": ("propio.csv", body.encode(), "text/csv")},
        headers=auth(token),
    )
    assert upload.status_code == 200, upload.text

    run = client.post(f"/datasets/{dataset_id}/run-quality", headers=auth(token))
    assert run.status_code == 200, run.text
    summary = run.json()["quality_summary"]["summary"]

    assert summary["total_rows"] == 10
    assert summary["rows_affected"] == 2

    stored = db.query(DatasetRun).filter(DatasetRun.dataset_id == dataset_id).one()
    assert stored.rows_affected == 2
    assert stored.total_rows == 10
    assert stored.quality_score == 80.0
    assert stored.issue_rows == summary["rule_violations"]
    assert stored.issue_rows > stored.rows_affected  # violations exceed rows here

    kpis = client.get("/dashboard/kpis", headers=auth(token)).json()
    assert kpis["quality_score"] == 80.0
    assert kpis["rows_affected"] == 2
