"""Schema validation: is this CSV really data of the selected domain?

The point of these tests is the distinction between "your data has problems"
and "this file was never this kind of data". A wrong-schema CSV used to reach
the rules and come back scored 0%, which is a claim about quality that was
never measured.
"""

import csv
import io

import pytest

from conftest import auth, make_admin

from app.models.dataset import Dataset
from app.models.dataset_run import DatasetRun
from app.services.data_generator import generate_dataset_csv
from app.services.schema_check import (
    MAX_INVALID_TYPE_RATIO,
    MIN_REQUIRED_COVERAGE,
    STATUS_COMPATIBLE,
    STATUS_INCOMPATIBLE,
    STATUS_WARNING,
    check_schema,
)

ECOMMERCE_COLUMNS = [
    "order_id",
    "customer_id",
    "sku",
    "price",
    "quantity",
    "stock",
    "address",
    "city",
    "postal_code",
    "channel",
    "payment_method",
    "discount_pct",
]


def good_row(index: int, **overrides) -> dict:
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


def rows(count: int, **overrides) -> list[dict]:
    return [good_row(i, **overrides) for i in range(count)]


def to_csv(records: list[dict]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(records[0].keys()))
    writer.writeheader()
    writer.writerows(records)
    return buffer.getvalue().encode("utf-8")


# --- 1. correct schema ------------------------------------------------------


def test_matching_schema_is_compatible():
    records = rows(20)
    report = check_schema(ECOMMERCE_COLUMNS, records, domain="ecommerce")

    assert report.status == STATUS_COMPATIBLE
    assert report.missing_required == []
    assert report.unexpected_columns == []
    assert report.type_mismatches == []
    assert report.required_coverage == 1.0


def test_the_generated_demo_dataset_is_compatible_with_every_domain():
    parsed = list(csv.DictReader(io.StringIO(generate_dataset_csv(40, 0.0, seed=11))))
    columns = list(parsed[0].keys())

    for domain in ("ecommerce", "logistica", "ecommerce-logistica"):
        report = check_schema(columns, parsed, domain=domain)
        assert report.status == STATUS_COMPATIBLE, (domain, report.reasons)


# --- 2 & 3. missing required columns ---------------------------------------


def test_one_missing_required_column_is_a_warning_not_a_rejection():
    columns = [c for c in ECOMMERCE_COLUMNS if c != "city"]
    records = [{k: v for k, v in row.items() if k != "city"} for row in rows(20)]

    report = check_schema(columns, records, domain="ecommerce")

    assert report.status == STATUS_WARNING
    assert report.missing_required == ["city"]
    assert report.required_coverage > MIN_REQUIRED_COVERAGE
    assert any("city" in reason for reason in report.reasons)


def test_many_missing_required_columns_fall_below_coverage_and_are_incompatible():
    keep = ["order_id", "customer_id", "sku", "price"]  # 4 of 12
    records = [{k: row[k] for k in keep} for row in rows(20)]

    report = check_schema(keep, records, domain="ecommerce")

    assert report.status == STATUS_INCOMPATIBLE
    assert report.required_coverage < MIN_REQUIRED_COVERAGE
    assert len(report.missing_required) == 8


def test_missing_identity_column_is_incompatible_even_with_everything_else():
    columns = [c for c in ECOMMERCE_COLUMNS if c != "order_id"]
    records = [{k: v for k, v in row.items() if k != "order_id"} for row in rows(20)]

    report = check_schema(columns, records, domain="ecommerce")

    # Coverage alone would have passed; identity is a separate, harder rule.
    assert report.required_coverage > MIN_REQUIRED_COVERAGE
    assert report.status == STATUS_INCOMPATIBLE
    assert any("order_id" in reason for reason in report.reasons)


# --- 4. unexpected columns --------------------------------------------------


def test_unexpected_column_is_reported_as_a_warning():
    columns = ECOMMERCE_COLUMNS + ["margen_bruto"]
    records = [dict(row, margen_bruto="12") for row in rows(20)]

    report = check_schema(columns, records, domain="ecommerce")

    assert report.status == STATUS_WARNING
    assert report.unexpected_columns == ["margen_bruto"]
    assert report.missing_required == []


# --- 5. type mismatches -----------------------------------------------------


def test_numeric_column_holding_text_is_a_type_mismatch():
    records = rows(20, price="caro", quantity="muchos")
    report = check_schema(ECOMMERCE_COLUMNS, records, domain="ecommerce")

    assert report.status == STATUS_WARNING
    mismatched = {m.column: m for m in report.type_mismatches}
    assert set(mismatched) == {"price", "quantity"}
    assert mismatched["price"].expected == "number"
    assert mismatched["price"].invalid_ratio > MAX_INVALID_TYPE_RATIO
    assert mismatched["price"].samples == ["caro"]


def test_a_minority_of_bad_values_is_a_quality_problem_not_a_type_mismatch():
    """Two bad prices out of twenty is dirty data, not the wrong column."""
    records = rows(18) + [good_row(90, price="caro"), good_row(91, price="gratis")]
    report = check_schema(ECOMMERCE_COLUMNS, records, domain="ecommerce")

    assert report.type_mismatches == []
    assert report.status == STATUS_COMPATIBLE


def test_empty_values_are_not_counted_as_type_errors():
    """Emptiness belongs to the missing_value rules, not to the schema check."""
    records = rows(20, price="")
    report = check_schema(ECOMMERCE_COLUMNS, records, domain="ecommerce")

    assert report.type_mismatches == []


def test_category_column_with_foreign_values_is_a_mismatch():
    records = rows(20, channel="canal-desconocido")
    report = check_schema(ECOMMERCE_COLUMNS, records, domain="ecommerce")

    mismatched = {m.column for m in report.type_mismatches}
    assert "channel" in mismatched


def test_a_column_with_too_few_values_is_not_judged():
    records = rows(3, price="caro")
    report = check_schema(ECOMMERCE_COLUMNS, records, domain="ecommerce")
    # Three values are not enough to conclude anything about a column.
    assert report.type_mismatches == []


# --- 6. a completely different dataset -------------------------------------


def test_a_foreign_csv_is_incompatible():
    records = [
        {"id": str(i), "nombre": "Ana", "fecha": "2026-01-01", "monto": str(i * 10)}
        for i in range(50)
    ]
    report = check_schema(list(records[0].keys()), records, domain="ecommerce")

    assert report.status == STATUS_INCOMPATIBLE
    assert report.required_coverage == 0.0
    assert sorted(report.unexpected_columns) == ["fecha", "id", "monto", "nombre"]


def test_empty_column_list_is_incompatible():
    report = check_schema([], [], domain="ecommerce")
    assert report.status == STATUS_INCOMPATIBLE


# --- 7 & 8. behaviour of the run -------------------------------------------


def _dataset_with_csv(client, token, name, domain, payload: bytes) -> int:
    created = client.post(
        "/datasets", json={"name": name, "domain": domain}, headers=auth(token)
    )
    assert created.status_code == 200, created.text
    dataset_id = created.json()["id"]
    uploaded = client.post(
        f"/datasets/{dataset_id}/upload",
        files={"file": (f"{name}.csv", payload, "text/csv")},
        headers=auth(token),
    )
    assert uploaded.status_code == 200, uploaded.text
    return dataset_id


def test_valid_dataset_with_quality_problems_is_still_scored(client, db):
    """The important non-regression: dirty but valid data keeps its score."""
    _, token = make_admin(db)
    records = rows(8) + [good_row(50, address="", price=""), good_row(51, address="", price="")]
    dataset_id = _dataset_with_csv(client, token, "valido-sucio", "ecommerce", to_csv(records))

    response = client.post(f"/datasets/{dataset_id}/run-quality", headers=auth(token))
    assert response.status_code == 200
    body = response.json()

    assert body["schema_status"] == STATUS_COMPATIBLE
    assert body["quality_score"] == 80.0
    summary = body["quality_summary"]["summary"]
    assert summary["total_rows"] == 10
    assert summary["rows_affected"] == 2
    assert body["quality_summary"]["issues"], "the rules must still have run"


def test_incompatible_dataset_does_not_run_the_rules(client, db):
    _, token = make_admin(db)
    foreign = [
        {"id": str(i), "nombre": "Ana", "fecha": "2026-01-01", "monto": str(i * 10)}
        for i in range(30)
    ]
    dataset_id = _dataset_with_csv(client, token, "ajeno", "ecommerce", to_csv(foreign))

    response = client.post(f"/datasets/{dataset_id}/run-quality", headers=auth(token))
    assert response.status_code == 200
    body = response.json()

    assert body["schema_status"] == STATUS_INCOMPATIBLE
    # No rules ran, so there are no findings and no cases.
    assert body["quality_summary"]["issues"] == []
    assert body["quality_summary"]["recommendations"] == []
    assert body["cases_created"] == 0
    assert body["anomaly_summary"]["anomaly_count"] == 0
    assert body["anomaly_summary"]["skipped"] == "schema_mismatch"


def test_incompatible_dataset_produces_no_quality_score(client, db):
    """No number at all, rather than a 0% that would mean something false."""
    _, token = make_admin(db)
    foreign = [{"a": str(i), "b": "x", "c": "y"} for i in range(30)]
    dataset_id = _dataset_with_csv(client, token, "ajeno2", "ecommerce", to_csv(foreign))

    body = client.post(f"/datasets/{dataset_id}/run-quality", headers=auth(token)).json()

    assert body["quality_score"] is None
    assert body["risk_score"] is None
    summary = body["quality_summary"]["summary"]
    assert summary["schema_status"] == STATUS_INCOMPATIBLE
    # Deliberately absent, not zero.
    assert "rows_affected" not in summary
    assert "issue_count" not in summary
    # The row count is still known and reported.
    assert summary["total_rows"] == 30

    stored = db.query(DatasetRun).filter(DatasetRun.dataset_id == dataset_id).one()
    assert stored.quality_score is None
    assert stored.risk_score is None
    assert stored.rows_affected is None
    assert stored.total_rows == 30


def test_incompatible_dataset_explains_what_is_wrong(client, db):
    _, token = make_admin(db)
    foreign = [{"id": str(i), "monto": "10"} for i in range(30)]
    dataset_id = _dataset_with_csv(client, token, "ajeno3", "ecommerce", to_csv(foreign))

    body = client.post(f"/datasets/{dataset_id}/run-quality", headers=auth(token)).json()
    report = body["quality_summary"]["schema"]

    assert report["status"] == STATUS_INCOMPATIBLE
    assert "order_id" in report["missing_required"]
    assert sorted(report["unexpected_columns"]) == ["id", "monto"]
    assert report["reasons"], "the user must be told why"
    assert all(isinstance(reason, str) and reason for reason in report["reasons"])


def test_warning_dataset_still_runs_the_rules_and_keeps_its_score(client, db):
    _, token = make_admin(db)
    records = [dict(row, margen_bruto="12") for row in rows(10)]
    dataset_id = _dataset_with_csv(client, token, "con-extra", "ecommerce", to_csv(records))

    body = client.post(f"/datasets/{dataset_id}/run-quality", headers=auth(token)).json()

    assert body["schema_status"] == STATUS_WARNING
    assert body["quality_score"] == 100.0  # the data itself is clean
    assert body["quality_summary"]["schema"]["unexpected_columns"] == ["margen_bruto"]


# --- 9 & 10. the dashboard must not be misled -------------------------------


def test_incompatible_dataset_is_excluded_from_dashboard_aggregates(client, db):
    _, token = make_admin(db)

    valid_id = _dataset_with_csv(
        client,
        token,
        "valido",
        "ecommerce",
        to_csv(rows(8) + [good_row(50 + i, address="") for i in range(2)]),
    )
    client.post(f"/datasets/{valid_id}/run-quality", headers=auth(token))

    foreign = [{"id": str(i), "monto": "10"} for i in range(900)]
    bad_id = _dataset_with_csv(client, token, "ajeno", "ecommerce", to_csv(foreign))
    client.post(f"/datasets/{bad_id}/run-quality", headers=auth(token))

    kpis = client.get("/dashboard/kpis", headers=auth(token)).json()

    assert kpis["datasets"] == 2
    # Only the valid one contributes; the 900 foreign rows must not drag the
    # percentage down as if they had been measured.
    assert kpis["datasets_measured"] == 1
    assert kpis["total_rows"] == 10
    assert kpis["quality_score"] == 80.0

    health = client.get("/dashboard/insights", headers=auth(token)).json()["dataset_health"]
    scores = {item["name"]: item["score"] for item in health}
    assert scores["valido"] == 80.0
    assert scores["ajeno"] is None


def test_quality_score_is_unchanged_for_compatible_datasets(client, db):
    """Regression guard for the formula corrected in the previous phase."""
    _, token = make_admin(db)
    records = rows(7) + [good_row(80 + i, address="", price="") for i in range(3)]
    dataset_id = _dataset_with_csv(client, token, "regresion", "ecommerce", to_csv(records))

    body = client.post(f"/datasets/{dataset_id}/run-quality", headers=auth(token)).json()
    summary = body["quality_summary"]["summary"]

    assert summary["rows_affected"] == 3
    assert summary["rule_violations"] == 9  # still more violations than rows
    assert body["quality_score"] == 70.0


# --- preview surfaces the verdict before a run is spent ---------------------


def test_preview_reports_the_schema_status(client, db):
    _, token = make_admin(db)
    foreign = [{"id": str(i), "monto": "10"} for i in range(30)]
    dataset_id = _dataset_with_csv(client, token, "ajeno-preview", "ecommerce", to_csv(foreign))

    preview = client.get(f"/datasets/{dataset_id}/preview", headers=auth(token)).json()

    assert preview["schema"]["status"] == STATUS_INCOMPATIBLE
    assert "order_id" in preview["schema"]["missing_required"]


def test_preview_reports_compatible_for_a_matching_file(client, db):
    _, token = make_admin(db)
    dataset_id = _dataset_with_csv(client, token, "ok-preview", "ecommerce", to_csv(rows(20)))

    preview = client.get(f"/datasets/{dataset_id}/preview", headers=auth(token)).json()
    assert preview["schema"]["status"] == STATUS_COMPATIBLE


# --- domain matters ---------------------------------------------------------


def test_the_same_file_can_match_one_domain_and_not_another(client, db):
    """An ecommerce CSV lacks the logistics columns; the verdict must differ."""
    _, token = make_admin(db)
    payload = to_csv(rows(20))

    ecom_id = _dataset_with_csv(client, token, "como-ecommerce", "ecommerce", payload)
    logi_id = _dataset_with_csv(client, token, "como-logistica", "logistica", payload)

    ecom = client.post(f"/datasets/{ecom_id}/run-quality", headers=auth(token)).json()
    logi = client.post(f"/datasets/{logi_id}/run-quality", headers=auth(token)).json()

    assert ecom["schema_status"] == STATUS_COMPATIBLE
    assert ecom["quality_score"] == 100.0
    assert logi["schema_status"] == STATUS_INCOMPATIBLE
    assert logi["quality_score"] is None


@pytest.mark.parametrize("domain", ["ecommerce", "logistica", "ecommerce-logistica"])
def test_every_domain_declares_a_type_for_all_of_its_columns(domain):
    """Guards against a column being added to a profile without a type."""
    from app.services.data_quality import DOMAIN_PROFILES, FIELD_TYPES

    profile = DOMAIN_PROFILES[domain]
    declared = set(FIELD_TYPES)
    for column in list(profile["required"]) + list(profile["optional"]):
        assert column in declared, f"{column} has no declared type"
