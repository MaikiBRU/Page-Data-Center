"""One implementation of "analyse a dataset and record the result".

Before this module the pipeline existed twice — once in the datasets router
and once, subtly different, in the dashboard's demo regeneration (that copy
forgot to set SLA and assignee). Both callers now go through here, and the
demo sandbox reuses it as well instead of adding a third variant.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_activity_log import CaseActivityLog
from app.models.case_note import CaseNote
from app.models.case_status_log import CaseStatusLog
from app.models.dataset import Dataset
from app.models.dataset_run import DatasetRun
from app.models.user import User
from app.services.assignment import pick_assignee
from app.services.data_quality import (
    recommend_actions,
    run_anomaly_detection,
    run_quality_checks,
)
from app.services.dataset_storage import load_dataset_records
from app.services.schema_check import STATUS_INCOMPATIBLE, check_schema

_SLA_MATRIX = {
    "default": {"high": 24, "medium": 48, "low": 72},
    "ecommerce": {"high": 18, "medium": 40, "low": 72},
    "logistica": {"high": 12, "medium": 36, "low": 72},
    "ecommerce-logistica": {"high": 16, "medium": 40, "low": 80},
}


@dataclass
class RunOutcome:
    dataset_id: int
    quality_summary: dict
    anomaly_summary: dict
    cases_created: int
    schema_status: str
    # None when the schema did not match: nothing about quality was measured,
    # so there is no honest number to report.
    risk_score: float | None
    quality_score: float | None
    rows_affected: int | None
    critical_rows: int | None
    duration_ms: int


def rule_violations(issues: list[dict]) -> int:
    """How many times any rule fired.

    A row breaking three rules contributes three. This is a count of findings
    weighted by frequency, never a count of rows: summing it and calling the
    result "rows" was the original defect, and it could exceed the size of the
    dataset.
    """
    return sum(int(issue.get("count", 0) or 0) for issue in issues)


def compute_scores(rows_affected: int, critical_rows: int, total_rows: int) -> tuple[float, float]:
    """Risk and quality for one dataset. Single definition, used everywhere.

    quality_score = 100 * (1 - rows_affected / total_rows)
        Share of rows that passed every active rule. Bounded to [0, 100] by
        construction because rows_affected counts distinct rows and can never
        exceed total_rows. 100 on a clean dataset, 0 when every row fails.

    risk_score    = 100 * critical_rows / total_rows
        Share of rows failing at least one rule declared high severity in
        data_quality.severity_for. No weights, no tuning constants: it is a
        percentage of the dataset, so it is directly checkable against the
        data.

    An empty dataset has nothing to judge, so both scores are 0 and callers
    should present it as "sin datos" rather than as a bad result.
    """
    if total_rows <= 0:
        return 0.0, 0.0
    rows_affected = max(0, min(int(rows_affected), total_rows))
    critical_rows = max(0, min(int(critical_rows), total_rows))
    # Rounded here so every consumer reports the same figure; the dashboard,
    # the stored run and the exported report used to round independently.
    quality = round(100.0 * (1 - rows_affected / total_rows), 1)
    risk = round(100.0 * critical_rows / total_rows, 1)
    return risk, quality


def case_sla(severity: str, domain: str | None) -> tuple[datetime, int]:
    matrix = _SLA_MATRIX.get(domain or "", _SLA_MATRIX["default"])
    hours = matrix.get(severity, _SLA_MATRIX["default"]["medium"])
    return datetime.utcnow() + timedelta(hours=hours), hours


def _clear_generated_cases(db: Session, dataset: Dataset) -> None:
    """Drop the cases the previous run generated, keeping worked-on ones.

    The original code deleted every case of the dataset on each run, which
    threw away assignments, SLA and status along with the notes and timeline
    entries that referenced them (those were left behind as orphans). A case
    is now only removed when nobody has touched it: no notes, and no status
    change beyond the one recorded at creation.
    """
    case_ids = [row[0] for row in db.query(Case.id).filter(Case.dataset_id == dataset.id).all()]
    if not case_ids:
        return

    with_notes = {
        row[0] for row in db.query(CaseNote.case_id).filter(CaseNote.case_id.in_(case_ids)).all()
    }
    status_counts: dict[int, int] = {}
    for (case_id,) in db.query(CaseStatusLog.case_id).filter(
        CaseStatusLog.case_id.in_(case_ids)
    ).all():
        status_counts[case_id] = status_counts.get(case_id, 0) + 1

    disposable = [
        case_id
        for case_id in case_ids
        if case_id not in with_notes and status_counts.get(case_id, 0) <= 1
    ]
    if not disposable:
        return

    db.query(CaseStatusLog).filter(CaseStatusLog.case_id.in_(disposable)).delete(
        synchronize_session=False
    )
    db.query(CaseActivityLog).filter(CaseActivityLog.case_id.in_(disposable)).delete(
        synchronize_session=False
    )
    db.query(Case).filter(Case.id.in_(disposable)).delete(synchronize_session=False)


def _incompatible_outcome(
    db: Session, dataset: Dataset, report, total_rows: int, started_at: float
) -> RunOutcome:
    """Record that the file does not belong to this domain, and stop.

    The rules are not executed. Running them would report every required
    column as missing on every row and yield a quality score of 0, which
    asserts something about data quality that was never measured. The run is
    still logged, with the score columns left NULL, so the history shows the
    attempt and its verdict.
    """
    dataset.quality_summary = {
        "schema": report.as_dict(),
        "summary": {
            "schema_status": report.status,
            "total_rows": total_rows,
            "domain_profile": dataset.domain,
            # No issue_count, no rows_affected: deliberately absent rather
            # than zero, so aggregates skip this dataset instead of counting
            # it as clean or as fully broken.
        },
        "issues": [],
        "recommendations": [],
    }
    dataset.anomaly_summary = {"anomaly_count": 0, "anomalies": [], "skipped": "schema_mismatch"}
    dataset.last_run_at = datetime.utcnow()

    duration_ms = int((time.perf_counter() - started_at) * 1000)
    db.add(
        DatasetRun(
            dataset_id=dataset.id,
            run_at=dataset.last_run_at,
            duration_ms=duration_ms,
            total_rows=total_rows,
            issue_count=None,
            issue_rows=None,
            rows_affected=None,
            critical_rows=None,
            anomaly_count=None,
            risk_score=None,
            quality_score=None,
        )
    )
    db.commit()
    db.refresh(dataset)

    return RunOutcome(
        dataset_id=dataset.id,
        quality_summary=dataset.quality_summary,
        anomaly_summary=dataset.anomaly_summary,
        cases_created=0,
        schema_status=report.status,
        risk_score=None,
        quality_score=None,
        rows_affected=None,
        critical_rows=None,
        duration_ms=duration_ms,
    )


def execute_quality_run(db: Session, dataset: Dataset) -> RunOutcome:
    """Analyse the dataset, persist the summary, refresh cases, log the run.

    The schema is checked before any rule runs: a CSV that does not belong to
    the selected domain is reported as such instead of being scored.
    """
    started_at = time.perf_counter()
    records = load_dataset_records(db, dataset)

    columns = list(records[0].keys()) if records else []
    report = check_schema(columns, records, domain=dataset.domain)
    if report.status == STATUS_INCOMPATIBLE:
        return _incompatible_outcome(db, dataset, report, len(records), started_at)

    disabled_rules = (dataset.rules_config or {}).get("disabled_rules", [])
    quality_summary, issues = run_quality_checks(
        records, domain=dataset.domain, disabled_rules=disabled_rules
    )
    anomaly_summary = run_anomaly_detection(
        records, domain=dataset.domain, disabled_rules=disabled_rules
    )
    recommendations = recommend_actions(issues)

    dataset.quality_summary = {
        # Carried even when compatible, so warnings stay visible next to the
        # results they may explain.
        "schema": report.as_dict(),
        "summary": {**quality_summary, "schema_status": report.status},
        "issues": issues,
        "recommendations": recommendations,
    }
    dataset.anomaly_summary = anomaly_summary
    dataset.last_run_at = datetime.utcnow()

    total_rows = int(quality_summary.get("total_rows", 0) or 0)
    anomaly_count = int(anomaly_summary.get("anomaly_count", 0) or 0)
    rows_affected = int(quality_summary.get("rows_affected", 0) or 0)
    critical_rows = int(quality_summary.get("critical_rows", 0) or 0)
    risk_score, quality_score = compute_scores(rows_affected, critical_rows, total_rows)

    _clear_generated_cases(db, dataset)

    active_users: list[str] | None = None
    if dataset.assignment_mode == "round_robin" and not dataset.demo_session_id:
        active_users = [
            row.email
            for row in db.query(User)
            .filter(User.is_active.is_(True))
            .order_by(User.created_at.asc(), User.id.asc())
            .all()
            if row.email
        ]

    created_cases = 0
    for issue in issues:
        if issue.get("severity") != "high":
            continue
        severity = issue.get("severity", "high")
        due_date, sla_hours = case_sla(severity, dataset.domain)
        # Demo sandboxes never route work to real users.
        assignee = None if dataset.demo_session_id else pick_assignee(db, dataset, active_users)
        case = Case(
            dataset_id=dataset.id,
            demo_session_id=dataset.demo_session_id,
            title=issue.get("code", "issue"),
            severity=severity,
            status="open",
            assignee=assignee,
            summary=f"{issue.get('count', 0)} registros afectados",
            recommendation=next(
                (r["action"] for r in recommendations if r["code"] == issue.get("code")), None
            ),
            due_date=due_date,
            sla_hours=sla_hours,
        )
        db.add(case)
        created_cases += 1

    duration_ms = int((time.perf_counter() - started_at) * 1000)
    db.add(
        DatasetRun(
            dataset_id=dataset.id,
            run_at=dataset.last_run_at,
            duration_ms=duration_ms,
            total_rows=total_rows,
            issue_count=int(quality_summary.get("issue_count", 0) or 0),
            issue_rows=rule_violations(issues),
            rows_affected=rows_affected,
            critical_rows=critical_rows,
            anomaly_count=anomaly_count,
            risk_score=round(risk_score, 1),
            quality_score=round(quality_score, 1),
        )
    )
    db.commit()
    db.refresh(dataset)

    return RunOutcome(
        dataset_id=dataset.id,
        quality_summary=dataset.quality_summary,
        anomaly_summary=dataset.anomaly_summary,
        cases_created=created_cases,
        schema_status=report.status,
        risk_score=round(risk_score, 1),
        quality_score=round(quality_score, 1),
        rows_affected=rows_affected,
        critical_rows=critical_rows,
        duration_ms=duration_ms,
    )
