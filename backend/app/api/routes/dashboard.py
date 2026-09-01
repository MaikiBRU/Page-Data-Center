from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from html import escape
import shutil
import csv
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import (
    Principal,
    demo_quota_error,
    get_db,
    get_principal,
    require_permission,
    scope_cases,
    scope_datasets,
)
from app.services import demo_session as demo_service
from app.models.case import Case
from app.models.dataset import Dataset
from app.models.dataset_run import DatasetRun
from app.services.data_generator import generate_dataset
from app.services.quality_run import execute_quality_run

BASE_DIR = Path(__file__).resolve().parents[4]
UPLOAD_DIR = BASE_DIR / "data" / "uploads"

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_DEMO_ROWS = 420
_DEMO_ANOMALY_RATE = 0.12


def _dataset_facts(dataset: Dataset) -> dict:
    """Row-level facts for one dataset, read from its last stored run.

    Everything here is a count of rows or of findings. There is no weighting,
    no monetary conversion and no tuning constant, so every number can be
    traced back to the CSV it came from.
    """
    summary = dataset.quality_summary or {}
    block = summary.get("summary") or {} if isinstance(summary, dict) else {}
    issues = summary.get("issues", []) if isinstance(summary, dict) else []
    total_rows = int(block.get("total_rows", 0) or 0)

    # rows_affected / critical_rows were added to the summary when row level
    # tracking landed. Runs stored before that have neither, and there is no
    # way to recover them from the aggregated counts, so such a dataset is
    # excluded from row based aggregates instead of being counted as clean.
    has_row_metrics = "rows_affected" in block
    rows_affected = min(int(block.get("rows_affected", 0) or 0), total_rows)
    critical_rows = min(int(block.get("critical_rows", 0) or 0), total_rows)

    return {
        "total_rows": total_rows,
        "rows_affected": rows_affected,
        "critical_rows": critical_rows,
        "has_row_metrics": has_row_metrics and total_rows > 0,
        # "compatible" | "warning" | "incompatible", or None when the dataset
        # has never been analysed. Lets the UI say why a score is missing
        # instead of showing the same blank for both cases.
        "schema_status": (block.get("schema_status") if isinstance(block, dict) else None),
        "findings": int(block.get("issue_count", len(issues)) or 0),
        "rule_violations": int(
            block.get(
                "rule_violations",
                sum(int(issue.get("count", 0) or 0) for issue in issues),
            )
            or 0
        ),
        # The stored anomaly list is capped at 50 for payload size; the count
        # is not. Reading len(list) understated large datasets by up to 10x.
        "anomalies": int((dataset.anomaly_summary or {}).get("anomaly_count", 0) or 0),
        "analyzed": dataset.last_run_at is not None,
    }


def _quality_score(rows_affected: int, total_rows: int) -> float:
    """Share of rows that passed every active rule. See services/quality_run."""
    if total_rows <= 0:
        return 0.0
    return round(100.0 * (1 - min(rows_affected, total_rows) / total_rows), 1)


def _pct(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return round(100.0 * part / whole, 1)


def _quality_trend(db: Session, dataset_ids: list[int]) -> dict | None:
    """Compare the latest run of each dataset against its own previous run.

    Returns None when no dataset has two comparable runs. The dashboard used
    to derive a "previous week" from ``dataset.last_run_at``, a single
    timestamp: a dataset can only fall inside one of the two windows, so the
    previous window was always empty and every delta came out at +100%. The
    real history lives in ``dataset_runs``, so the comparison is made there,
    and it is reported in percentage points, which needs no division by a
    possibly zero baseline.
    """
    if not dataset_ids:
        return None

    runs = (
        db.query(DatasetRun)
        .filter(DatasetRun.dataset_id.in_(dataset_ids))
        .filter(DatasetRun.rows_affected.is_not(None))
        .filter(DatasetRun.total_rows.is_not(None))
        .filter(DatasetRun.total_rows > 0)
        .order_by(DatasetRun.dataset_id.asc(), DatasetRun.run_at.desc(), DatasetRun.id.desc())
        .all()
    )

    by_dataset: dict[int, list[DatasetRun]] = {}
    for run in runs:
        by_dataset.setdefault(run.dataset_id, []).append(run)

    latest_rows = latest_affected = previous_rows = previous_affected = 0
    compared = 0
    for dataset_runs in by_dataset.values():
        if len(dataset_runs) < 2:
            continue
        latest, previous = dataset_runs[0], dataset_runs[1]
        latest_rows += latest.total_rows
        latest_affected += min(latest.rows_affected, latest.total_rows)
        previous_rows += previous.total_rows
        previous_affected += min(previous.rows_affected, previous.total_rows)
        compared += 1

    if compared == 0 or latest_rows == 0 or previous_rows == 0:
        return None

    current = _quality_score(latest_affected, latest_rows)
    previous_score = _quality_score(previous_affected, previous_rows)
    return {
        "current": current,
        "previous": previous_score,
        # Percentage points, not a percent change: quality is already a
        # percentage, so a ratio between two of them would not mean anything.
        "delta_points": round(current - previous_score, 1),
        "datasets_compared": compared,
    }


@router.get("/kpis")
def dashboard_kpis(
    db: Session = Depends(get_db), principal: Principal = Depends(get_principal)
):
    """Headline data quality figures.

    Every value is a count of rows, a count of findings, or a percentage
    derived from those two. Nothing is estimated or converted into money.
    """
    datasets = scope_datasets(db.query(Dataset), principal).all()

    # "Open" here means the same thing as in /cases/summary: anything not
    # resolved. Counting only status == "open" left in_progress, blocked and
    # escalated cases out and disagreed with the Casos page.
    open_cases = (
        scope_cases(db.query(Case), principal).filter(Case.status != "resolved").count()
    )

    total_rows = rows_affected = critical_rows = 0
    findings = violations = anomalies = analyzed = 0
    measurable_datasets = 0
    for dataset in datasets:
        facts = _dataset_facts(dataset)
        if facts["analyzed"]:
            analyzed += 1
        findings += facts["findings"]
        violations += facts["rule_violations"]
        anomalies += facts["anomalies"]
        if facts["has_row_metrics"]:
            measurable_datasets += 1
            total_rows += facts["total_rows"]
            rows_affected += facts["rows_affected"]
            critical_rows += facts["critical_rows"]

    dataset_ids = [dataset.id for dataset in datasets]
    return {
        "datasets": len(datasets),
        "datasets_analyzed": analyzed,
        # Number of datasets contributing to the row based figures below.
        "datasets_measured": measurable_datasets,
        "total_rows": total_rows,
        "rows_affected": rows_affected,
        "rows_affected_pct": _pct(rows_affected, total_rows),
        "critical_rows": critical_rows,
        "critical_rows_pct": _pct(critical_rows, total_rows),
        "quality_score": _quality_score(rows_affected, total_rows),
        "findings": findings,
        "rule_violations": violations,
        "anomalies": anomalies,
        "open_cases": open_cases,
        # None when no dataset has been run twice, so the UI shows nothing
        # rather than a fabricated delta.
        "quality_trend": _quality_trend(db, dataset_ids),
    }


def _demo_datasets(db: Session) -> list[Dataset]:
    """Legacy admin seeded datasets in the authenticated app.

    Explicitly excludes sandbox rows so an administrator running "reset demo"
    can never delete a visitor's in-flight session data.
    """
    return (
        db.query(Dataset)
        .filter(Dataset.demo_session_id.is_(None))
        .filter(Dataset.name.ilike("%demo%"))
        .all()
    )


def _cleanup_dataset_files(dataset: Dataset) -> None:
    try:
        dataset_dir = UPLOAD_DIR / f"dataset_{dataset.id}"
        if dataset_dir.exists():
            shutil.rmtree(dataset_dir, ignore_errors=True)
    except Exception:
        pass
    if dataset.file_path:
        try:
            path = Path(dataset.file_path)
            if path.exists():
                path.unlink()
        except Exception:
            pass


def _rebuild_dataset(db: Session, dataset: Dataset) -> None:
    """Regenerate an admin demo dataset and re-analyse it.

    Delegates to the shared pipeline so this path cannot drift from the one
    used by POST /datasets/{id}/run-quality, as the previous copy had.
    """
    dataset_dir = UPLOAD_DIR / f"dataset_{dataset.id}"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    file_path = dataset_dir / "generated.csv"
    generate_dataset(str(file_path), _DEMO_ROWS, _DEMO_ANOMALY_RATE)
    dataset.file_path = str(file_path)
    dataset.source_type = "generated"
    db.commit()
    execute_quality_run(db, dataset)


@router.post("/demo/reset")
def reset_demo(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("dashboard:demo")),
):
    demos = _demo_datasets(db)
    if not demos:
        return {"removed": 0}
    removed = 0
    for dataset in demos:
        db.query(Case).filter(Case.dataset_id == dataset.id).delete(synchronize_session=False)
        db.query(DatasetRun).filter(DatasetRun.dataset_id == dataset.id).delete(synchronize_session=False)
        _cleanup_dataset_files(dataset)
        db.delete(dataset)
        removed += 1
    db.commit()
    return {"removed": removed}


@router.post("/demo/regenerate")
def regenerate_demo(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("dashboard:demo")),
):
    demos = _demo_datasets(db)
    if not demos:
        raise HTTPException(status_code=404, detail="No demo datasets found")
    regenerated = 0
    for dataset in demos:
        _rebuild_dataset(db, dataset)
        regenerated += 1
    return {"regenerated": regenerated}


@router.get("/insights")
def dashboard_insights(
    db: Session = Depends(get_db), principal: Principal = Depends(get_principal)
):
    datasets = scope_datasets(db.query(Dataset), principal).all()

    issues_by_code: dict[str, int] = defaultdict(int)
    issues_by_severity: dict[str, int] = defaultdict(int)
    anomalies_by_field: dict[str, int] = defaultdict(int)
    runs_by_day: dict[str, int] = defaultdict(int)
    dataset_health: list[dict] = []

    today = datetime.utcnow().date()
    for dataset in datasets:
        if dataset.last_run_at:
            run_date = dataset.last_run_at.date()
            if today - timedelta(days=6) <= run_date <= today:
                runs_by_day[run_date.isoformat()] += 1

        summary = dataset.quality_summary or {}
        issues = summary.get("issues", []) if isinstance(summary, dict) else []
        for issue in issues:
            code = issue.get("code", "unknown")
            count = int(issue.get("count", 0) or 0)
            severity = issue.get("severity", "medium")
            issues_by_code[code] += count
            issues_by_severity[severity] += count

        anomalies = (dataset.anomaly_summary or {}).get("anomalies", [])
        for anomaly in anomalies:
            field = anomaly.get("field", "unknown")
            anomalies_by_field[field] += 1

        # Health is the same quality score used everywhere else. It used to
        # be 100 - findings / total_rows, which divides a count of findings
        # by a count of rows and therefore sat near 100 no matter how
        # damaged the data was, disagreeing with dataset_runs.quality_score
        # for the very same dataset.
        facts = _dataset_facts(dataset)
        dataset_health.append(
            {
                "id": dataset.id,
                "name": dataset.name,
                "score": (
                    _quality_score(facts["rows_affected"], facts["total_rows"])
                    if facts["has_row_metrics"]
                    else None
                ),
                "total_rows": facts["total_rows"],
                "rows_affected": facts["rows_affected"] if facts["has_row_metrics"] else None,
                "critical_rows": facts["critical_rows"] if facts["has_row_metrics"] else None,
                "schema_status": facts["schema_status"],
                "last_run_at": dataset.last_run_at.isoformat() if dataset.last_run_at else None,
            }
        )

    run_series = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        run_series.append({"date": day.isoformat(), "runs": runs_by_day.get(day.isoformat(), 0)})

    issues_sorted = sorted(issues_by_code.items(), key=lambda item: item[1], reverse=True)
    anomalies_sorted = sorted(anomalies_by_field.items(), key=lambda item: item[1], reverse=True)

    return {
        "issues_by_code": [
            {"label": code, "value": count} for code, count in issues_sorted[:8]
        ],
        "issues_by_code_all": [
            {"label": code, "value": count} for code, count in issues_sorted
        ],
        "issues_by_severity": [
            {"label": severity, "value": count}
            for severity, count in issues_by_severity.items()
        ],
        "anomalies_by_field": [
            {"label": field, "value": count} for field, count in anomalies_sorted[:8]
        ],
        "anomalies_by_field_all": [
            {"label": field, "value": count} for field, count in anomalies_sorted
        ],
        "runs_last_7_days": run_series,
        # Worst first: that is the order somebody acting on this needs.
        # Datasets without row metrics have no score and go last.
        "dataset_health": sorted(
            dataset_health,
            key=lambda item: (
                item["score"] is None,
                item["score"] if item["score"] is not None else 0,
            ),
        ),
    }


@router.get("/report")
def export_report(
    format: str = "json",
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    if principal.is_demo:
        try:
            demo_service.assert_can_export(principal.demo)
        except demo_service.DemoQuotaExceeded as exc:
            raise demo_quota_error(exc) from None
        demo_service.register_export(db, principal.demo)
    kpis = dashboard_kpis(db, principal)
    insights = dashboard_insights(db, principal)
    datasets = scope_datasets(db.query(Dataset), principal).all()
    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "kpis": kpis,
        "insights": insights,
        "datasets": [
            {
                "id": dataset.id,
                "name": dataset.name,
                "domain": dataset.domain,
                "source_type": dataset.source_type,
                "last_run_at": dataset.last_run_at.isoformat() if dataset.last_run_at else None,
            }
            for dataset in datasets
        ],
    }
    if format.lower() == "json":
        return JSONResponse(report)
    if format.lower() == "html":
        issues_html = "".join(
            f"<tr><td>{escape(str(item.get('label', '')))}</td><td>{item.get('value', 0)}</td></tr>"
            for item in insights.get("issues_by_code_all", [])
        )
        anomalies_html = "".join(
            f"<tr><td>{escape(str(item.get('label', '')))}</td><td>{item.get('value', 0)}</td></tr>"
            for item in insights.get("anomalies_by_field_all", [])
        )
        health_html = "".join(
            f"<tr><td>{escape(str(item.get('name', '')))}</td>"
            f"<td>{'-' if item.get('score') is None else str(item['score']) + '%'}</td>"
            f"<td>{escape(str(item.get('last_run_at') or '-'))}</td></tr>"
            for item in insights.get("dataset_health", [])
        )
        datasets_html = "".join(
            f"<tr><td>{escape(dataset.name)}</td><td>{escape(dataset.domain)}</td><td>{escape(dataset.source_type)}</td><td>{escape(dataset.last_run_at.isoformat() if dataset.last_run_at else '-')}</td></tr>"
            for dataset in datasets
        )
        # The row based figures are only meaningful when at least one dataset
        # has been analysed since row level tracking landed. The interface
        # already checks datasets_measured before showing them; the export did
        # not, so a database whose runs all predate the migration produced a
        # report stating "Calidad de datos: 0%" -- a measurement that was never
        # taken, presented as a fact.
        measured = int(kpis.get("datasets_measured", 0) or 0) > 0

        def measured_or_dash(value: object, suffix: str = "") -> str:
            return f"{value}{suffix}" if measured else "sin medir"

        trend = kpis.get("quality_trend")
        if trend:
            trend_text = (
                f"{trend['previous']}% -> {trend['current']}% "
                f"({trend['delta_points']:+} puntos), comparando la ultima corrida "
                f"contra la anterior en {trend['datasets_compared']} dataset(s)."
            )
        else:
            trend_text = (
                "Sin comparacion disponible: ningun dataset tiene todavia dos corridas."
            )
        html = f"""
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <title>Reporte Ejecutivo - Data Center</title>
  <style>
    body {{ font-family: Arial, sans-serif; background: #f7f7f8; color: #111; margin: 0; padding: 32px; }}
    h1, h2 {{ margin: 0 0 8px 0; }}
    .meta {{ color: #555; font-size: 13px; margin-bottom: 24px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 24px; }}
    .card {{ background: #fff; border: 1px solid #e6e6e8; border-radius: 12px; padding: 12px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 12px; overflow: hidden; }}
    th, td {{ border-bottom: 1px solid #eee; padding: 8px 10px; font-size: 12px; text-align: left; }}
    th {{ background: #fafafa; text-transform: uppercase; letter-spacing: 0.08em; font-size: 10px; color: #666; }}
    .section {{ margin-bottom: 24px; }}
  </style>
</head>
<body>
  <h1>Reporte Ejecutivo</h1>
  <div class="meta">Generado: {escape(report['generated_at'])}</div>

  <div class="grid">
    <div class="card"><strong>Datasets analizados</strong><div>{kpis.get('datasets_analyzed')} de {kpis.get('datasets')}</div></div>
    <div class="card"><strong>Calidad de datos</strong><div>{measured_or_dash(kpis.get('quality_score'), '%')}</div></div>
    <div class="card"><strong>Filas afectadas</strong><div>{measured_or_dash(str(kpis.get('rows_affected')) + ' de ' + str(kpis.get('total_rows')) + ' (' + str(kpis.get('rows_affected_pct')) + '%)')}</div></div>
    <div class="card"><strong>Filas criticas</strong><div>{measured_or_dash(str(kpis.get('critical_rows')) + ' (' + str(kpis.get('critical_rows_pct')) + '%)')}</div></div>
    <div class="card"><strong>Hallazgos</strong><div>{kpis.get('findings')} ({kpis.get('rule_violations')} violaciones)</div></div>
    <div class="card"><strong>Anomalias</strong><div>{kpis.get('anomalies')}</div></div>
    <div class="card"><strong>Casos abiertos</strong><div>{kpis.get('open_cases')}</div></div>
  </div>

  <div class="section">
    <h2>Tendencia de calidad</h2>
    <p class="meta">{trend_text}</p>
  </div>

  <div class="section">
    <h2>Top issues</h2>
    <table>
      <thead><tr><th>Issue</th><th>Casos</th></tr></thead>
      <tbody>{issues_html or "<tr><td colspan='2'>Sin datos</td></tr>"}</tbody>
    </table>
  </div>

  <div class="section">
    <h2>Top anomalías</h2>
    <table>
      <thead><tr><th>Campo</th><th>Casos</th></tr></thead>
      <tbody>{anomalies_html or "<tr><td colspan='2'>Sin datos</td></tr>"}</tbody>
    </table>
  </div>

  <div class="section">
    <h2>Salud por dataset</h2>
    <table>
      <thead><tr><th>Dataset</th><th>Calidad</th><th>Ultima corrida</th></tr></thead>
      <tbody>{health_html or "<tr><td colspan='3'>Sin datos</td></tr>"}</tbody>
    </table>
  </div>

  <div class="section">
    <h2>Listado de datasets</h2>
    <table>
      <thead><tr><th>Dataset</th><th>Dominio</th><th>Origen</th><th>Última corrida</th></tr></thead>
      <tbody>{datasets_html or "<tr><td colspan='4'>Sin datasets</td></tr>"}</tbody>
    </table>
  </div>
</body>
</html>
"""
        return Response(content=html, media_type="text/html")

    if format.lower() != "csv":
        raise HTTPException(status_code=400, detail="Unsupported format")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["section", "metric", "value", "extra"])
    for key, value in kpis.items():
        if key == "quality_trend":
            continue
        writer.writerow(["kpi", key, value, ""])
    trend = kpis.get("quality_trend")
    if trend:
        writer.writerow(["trend", "quality_current", trend["current"], ""])
        writer.writerow(["trend", "quality_previous", trend["previous"], ""])
        writer.writerow(["trend", "quality_delta_points", trend["delta_points"], ""])
        writer.writerow(["trend", "datasets_compared", trend["datasets_compared"], ""])
    else:
        writer.writerow(["trend", "quality_delta_points", "", "sin corrida previa"])
    for item in insights.get("issues_by_code_all", []):
        writer.writerow(["issue", item.get("label"), item.get("value"), ""])
    for item in insights.get("anomalies_by_field_all", []):
        writer.writerow(["anomaly", item.get("label"), item.get("value"), ""])
    for item in insights.get("dataset_health", []):
        writer.writerow(
            [
                "dataset_health",
                item.get("name"),
                item.get("score"),
                item.get("last_run_at"),
            ]
        )
    for dataset in datasets:
        writer.writerow(
            [
                "dataset",
                dataset.name,
                dataset.domain,
                dataset.last_run_at.isoformat() if dataset.last_run_at else "",
            ]
        )

    csv_bytes = output.getvalue().encode("utf-8")
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=dashboard_report.csv"},
    )
