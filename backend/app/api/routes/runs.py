from datetime import datetime, date, time, timedelta
import csv
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import (
    Principal,
    demo_quota_error,
    get_db,
    get_principal,
    scope_datasets,
)
from app.services import demo_session as demo_service
from app.models.dataset import Dataset
from app.models.dataset_run import DatasetRun

router = APIRouter(prefix="/runs", tags=["runs"])


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except Exception:
        return None


def _apply_filters(
    query,
    dataset_id: int | None,
    from_date: date | None,
    to_date: date | None,
    min_risk: float | None,
    min_rows: int | None,
):
    if dataset_id:
        query = query.filter(DatasetRun.dataset_id == dataset_id)
    if from_date:
        query = query.filter(DatasetRun.run_at >= datetime.combine(from_date, time.min))
    if to_date:
        query = query.filter(DatasetRun.run_at <= datetime.combine(to_date, time.max))
    if min_risk is not None:
        query = query.filter(DatasetRun.risk_score >= min_risk)
    if min_rows is not None:
        query = query.filter(DatasetRun.total_rows >= min_rows)
    return query


@router.get("")
def list_runs(
    dataset_id: int | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    min_risk: float | None = None,
    min_rows: int | None = None,
    limit: int = 200,
    format: str = "json",
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    from_dt = _parse_date(from_date)
    to_dt = _parse_date(to_date)
    query = scope_datasets(
        db.query(DatasetRun, Dataset).join(Dataset, Dataset.id == DatasetRun.dataset_id),
        principal,
    )
    query = _apply_filters(query, dataset_id, from_dt, to_dt, min_risk, min_rows)
    query = query.order_by(DatasetRun.run_at.desc()).limit(min(limit, 5000))
    rows = query.all()

    results = [
        {
            "id": run.id,
            "dataset_id": dataset.id,
            "dataset_name": dataset.name,
            "domain": dataset.domain,
            "run_at": run.run_at.isoformat() if run.run_at else None,
            "duration_ms": run.duration_ms,
            "total_rows": run.total_rows,
            "issue_count": run.issue_count,
            "issue_rows": run.issue_rows,
            "anomaly_count": run.anomaly_count,
            "risk_score": run.risk_score,
            "quality_score": run.quality_score,
        }
        for run, dataset in rows
    ]

    if format.lower() == "json":
        return results
    if format.lower() != "csv":
        raise HTTPException(status_code=400, detail="Unsupported format")

    if principal.is_demo:
        try:
            demo_service.assert_can_export(principal.demo)
        except demo_service.DemoQuotaExceeded as exc:
            raise demo_quota_error(exc) from None
        demo_service.register_export(db, principal.demo)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "run_at",
            "dataset",
            "domain",
            "duration_ms",
            "total_rows",
            "issue_rows",
            "anomaly_count",
            "risk_score",
            "quality_score",
        ]
    )
    for item in results:
        writer.writerow(
            [
                item["run_at"],
                item["dataset_name"],
                item["domain"],
                item["duration_ms"],
                item["total_rows"],
                item["issue_rows"],
                item["anomaly_count"],
                item["risk_score"],
                item["quality_score"],
            ]
        )

    csv_bytes = output.getvalue().encode("utf-8")
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=runs_export.csv"},
    )


@router.get("/summary")
def runs_summary(
    dataset_id: int | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    min_risk: float | None = None,
    min_rows: int | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    from_dt = _parse_date(from_date)
    to_dt = _parse_date(to_date)
    query = scope_datasets(
        db.query(DatasetRun).join(Dataset, Dataset.id == DatasetRun.dataset_id), principal
    )
    query = _apply_filters(query, dataset_id, from_dt, to_dt, min_risk, min_rows)
    runs = query.all()

    total_runs = len(runs)
    total_rows = sum((run.total_rows or 0) for run in runs)
    total_issues = sum((run.issue_rows or 0) for run in runs)
    total_anomalies = sum((run.anomaly_count or 0) for run in runs)
    avg_duration = (
        sum((run.duration_ms or 0) for run in runs) / total_runs if total_runs else 0
    )
    avg_risk = (
        sum((run.risk_score or 0) for run in runs) / total_runs if total_runs else 0
    )
    avg_quality = (
        sum((run.quality_score or 0) for run in runs) / total_runs if total_runs else 0
    )

    if from_dt and to_dt:
        start = from_dt
        end = to_dt
    else:
        end = date.today()
        start = end - timedelta(days=13)

    series_map: dict[str, int] = {}
    for run in runs:
        if not run.run_at:
            continue
        day = run.run_at.date().isoformat()
        series_map[day] = series_map.get(day, 0) + 1

    series = []
    cursor = start
    while cursor <= end:
        key = cursor.isoformat()
        series.append({"date": key, "runs": series_map.get(key, 0)})
        cursor = cursor + timedelta(days=1)

    return {
        "total_runs": total_runs,
        "total_rows": total_rows,
        "total_issues": total_issues,
        "total_anomalies": total_anomalies,
        "avg_duration_ms": round(avg_duration, 1) if total_runs else 0,
        "avg_risk_score": round(avg_risk, 1) if total_runs else 0,
        "avg_quality_score": round(avg_quality, 1) if total_runs else 0,
        "runs_by_day": series,
    }
