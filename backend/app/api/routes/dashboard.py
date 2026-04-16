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

from app.api.deps import get_current_user, get_db, require_permission
from app.models.case import Case
from app.models.dataset import Dataset
from app.models.dataset_run import DatasetRun
from app.services.data_generator import generate_dataset
from app.services.data_quality import load_records, recommend_actions, run_anomaly_detection, run_quality_checks

BASE_DIR = Path(__file__).resolve().parents[4]
UPLOAD_DIR = BASE_DIR / "data" / "uploads"

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_DEMO_ROWS = 420
_DEMO_ANOMALY_RATE = 0.12


def _issue_rows(issues: list[dict]) -> int:
    return sum(int(issue.get("count", 0) or 0) for issue in issues)


def _weighted_issues(issues: list[dict]) -> float:
    weights = {"high": 1.0, "medium": 0.6, "low": 0.3}
    total = 0.0
    for issue in issues:
        count = float(issue.get("count", 0) or 0)
        severity = issue.get("severity", "medium")
        total += count * weights.get(severity, 0.6)
    return total


def _base_value(domain: str | None) -> float:
    mapping = {
        "ecommerce": 120.0,
        "logistica": 90.0,
        "ecommerce-logistica": 110.0,
    }
    return mapping.get(domain or "", 100.0)


def _impact_and_risk(dataset: Dataset) -> dict:
    summary = dataset.quality_summary or {}
    issues = summary.get("issues", []) if isinstance(summary, dict) else []
    anomalies = (dataset.anomaly_summary or {}).get("anomalies", [])
    total_rows = int((summary.get("summary") or {}).get("total_rows", 0) or 0)
    weighted = _weighted_issues(issues)
    issue_rows = _issue_rows(issues)
    anomaly_count = len(anomalies)
    base = _base_value(dataset.domain)
    impact = weighted * base + anomaly_count * base * 0.4
    if total_rows <= 0:
        risk_score = 0.0
    else:
        risk_score = min(100.0, (weighted / total_rows) * 100 + (anomaly_count / total_rows) * 50)
    return {
        "issue_rows": issue_rows,
        "weighted_issues": weighted,
        "anomaly_count": anomaly_count,
        "total_rows": total_rows,
        "impact": impact,
        "risk_score": risk_score,
    }


def _risk_level(score: float) -> str:
    if score >= 70:
        return "alto"
    if score >= 40:
        return "medio"
    return "bajo"


def _delta(current: float, previous: float) -> float:
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return round(((current - previous) / previous) * 100, 1)


def _window_metrics(datasets: list[Dataset], start: datetime.date, end: datetime.date) -> dict:
    totals = {
        "runs": 0,
        "issue_rows": 0,
        "weighted_issues": 0.0,
        "anomalies": 0,
        "total_rows": 0,
        "impact": 0.0,
    }
    for dataset in datasets:
        if not dataset.last_run_at:
            continue
        run_date = dataset.last_run_at.date()
        if run_date < start or run_date > end:
            continue
        totals["runs"] += 1
        metrics = _impact_and_risk(dataset)
        totals["issue_rows"] += metrics["issue_rows"]
        totals["weighted_issues"] += metrics["weighted_issues"]
        totals["anomalies"] += metrics["anomaly_count"]
        totals["total_rows"] += metrics["total_rows"]
        totals["impact"] += metrics["impact"]

    if totals["total_rows"] > 0:
        totals["risk_score"] = min(
            100.0,
            (totals["weighted_issues"] / totals["total_rows"]) * 100
            + (totals["anomalies"] / totals["total_rows"]) * 50,
        )
    else:
        totals["risk_score"] = 0.0
    return totals


def _record_run(dataset: Dataset, issues: list[dict]) -> None:
    summary = dataset.quality_summary or {}
    total_rows = int((summary.get("summary") or {}).get("total_rows", 0) or 0)
    issue_count = int((summary.get("summary") or {}).get("issue_count", 0) or 0)
    issue_rows = sum(int(issue.get("count", 0) or 0) for issue in issues)
    anomaly_count = int((dataset.anomaly_summary or {}).get("anomaly_count", 0) or 0)
    weighted = _weighted_issues(issues)
    if total_rows:
        risk_score = min(100.0, (weighted / total_rows) * 100 + (anomaly_count / total_rows) * 50)
        quality_score = max(0.0, 100.0 - (issue_rows / total_rows) * 100)
    else:
        risk_score = 0.0
        quality_score = 0.0
    run = DatasetRun(
        dataset_id=dataset.id,
        run_at=dataset.last_run_at or datetime.utcnow(),
        duration_ms=None,
        total_rows=total_rows,
        issue_count=issue_count,
        issue_rows=issue_rows,
        anomaly_count=anomaly_count,
        risk_score=round(risk_score, 1),
        quality_score=round(quality_score, 1),
    )
    return run

@router.get("/kpis")
def dashboard_kpis(db: Session = Depends(get_db), user=Depends(get_current_user)):
    datasets = db.query(Dataset).all()
    open_cases = db.query(Case).filter(Case.status == "open").count()
    total_issues = 0
    impact_total = 0.0
    weighted_total = 0.0
    anomaly_total = 0
    total_rows = 0
    for dataset in datasets:
        if dataset.quality_summary and dataset.quality_summary.get("summary"):
            total_issues += dataset.quality_summary["summary"].get("issue_count", 0)
        metrics = _impact_and_risk(dataset)
        impact_total += metrics["impact"]
        weighted_total += metrics["weighted_issues"]
        anomaly_total += metrics["anomaly_count"]
        total_rows += metrics["total_rows"]

    if total_rows > 0:
        risk_score = min(
            100.0, (weighted_total / total_rows) * 100 + (anomaly_total / total_rows) * 50
        )
    else:
        risk_score = 0.0

    today = datetime.utcnow().date()
    current_start = today - timedelta(days=6)
    prev_start = today - timedelta(days=13)
    prev_end = today - timedelta(days=7)
    current = _window_metrics(datasets, current_start, today)
    previous = _window_metrics(datasets, prev_start, prev_end)

    new_cases_current = (
        db.query(Case)
        .filter(Case.created_at >= datetime.combine(current_start, datetime.min.time()))
        .filter(Case.created_at <= datetime.combine(today, datetime.max.time()))
        .count()
    )
    new_cases_previous = (
        db.query(Case)
        .filter(Case.created_at >= datetime.combine(prev_start, datetime.min.time()))
        .filter(Case.created_at <= datetime.combine(prev_end, datetime.max.time()))
        .count()
    )

    return {
        "datasets": len(datasets),
        "open_cases": open_cases,
        "issues": total_issues,
        "impact_estimated": round(impact_total, 2),
        "risk_score": round(risk_score, 1),
        "risk_level": _risk_level(risk_score),
        "week": {
            "runs": {
                "current": current["runs"],
                "previous": previous["runs"],
                "delta_pct": _delta(current["runs"], previous["runs"]),
            },
            "issues": {
                "current": current["issue_rows"],
                "previous": previous["issue_rows"],
                "delta_pct": _delta(current["issue_rows"], previous["issue_rows"]),
            },
            "anomalies": {
                "current": current["anomalies"],
                "previous": previous["anomalies"],
                "delta_pct": _delta(current["anomalies"], previous["anomalies"]),
            },
            "impact": {
                "current": round(current["impact"], 2),
                "previous": round(previous["impact"], 2),
                "delta_pct": _delta(current["impact"], previous["impact"]),
            },
            "risk_score": {
                "current": round(current["risk_score"], 1),
                "previous": round(previous["risk_score"], 1),
                "delta_pct": _delta(current["risk_score"], previous["risk_score"]),
            },
            "cases": {
                "current": new_cases_current,
                "previous": new_cases_previous,
                "delta_pct": _delta(new_cases_current, new_cases_previous),
            },
        },
    }


def _demo_datasets(db: Session) -> list[Dataset]:
    return db.query(Dataset).filter(Dataset.name.ilike("%demo%")).all()


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


def _rebuild_dataset(dataset: Dataset) -> None:
    dataset_dir = UPLOAD_DIR / f"dataset_{dataset.id}"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    file_path = dataset_dir / "generated.csv"
    generate_dataset(str(file_path), _DEMO_ROWS, _DEMO_ANOMALY_RATE)
    dataset.file_path = str(file_path)
    dataset.source_type = "generated"

    records = load_records(dataset.file_path)
    rules_config = dataset.rules_config or {}
    disabled_rules = rules_config.get("disabled_rules", [])
    quality_summary, issues = run_quality_checks(
        records, domain=dataset.domain, disabled_rules=disabled_rules
    )
    anomaly_summary = run_anomaly_detection(
        records, domain=dataset.domain, disabled_rules=disabled_rules
    )
    recommendations = recommend_actions(issues)

    dataset.quality_summary = {
        "summary": quality_summary,
        "issues": issues,
        "recommendations": recommendations,
    }
    dataset.anomaly_summary = anomaly_summary
    dataset.last_run_at = datetime.utcnow()

    return issues


@router.post("/demo/reset")
def reset_demo(db: Session = Depends(get_db), user=Depends(require_permission("dashboard:demo"))):
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
    user=Depends(require_permission("dashboard:demo")),
):
    demos = _demo_datasets(db)
    if not demos:
        raise HTTPException(status_code=404, detail="No demo datasets found")
    regenerated = 0
    for dataset in demos:
        issues = _rebuild_dataset(dataset)
        db.query(Case).filter(Case.dataset_id == dataset.id).delete(synchronize_session=False)
        for issue in issues:
            if issue.get("severity") == "high":
                case = Case(
                    dataset_id=dataset.id,
                    title=issue.get("code", "issue"),
                    severity=issue.get("severity", "medium"),
                    status="open",
                    summary=f"{issue.get('count', 0)} registros afectados",
                    recommendation=next(
                        (
                            r["action"]
                            for r in (dataset.quality_summary or {}).get("recommendations", [])
                            if r.get("code") == issue.get("code")
                        ),
                        None,
                    ),
                )
                db.add(case)
        db.add(_record_run(dataset, issues))
        regenerated += 1
    db.commit()
    return {"regenerated": regenerated}


@router.get("/insights")
def dashboard_insights(db: Session = Depends(get_db), user=Depends(get_current_user)):
    datasets = db.query(Dataset).all()

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

        total_rows = (summary.get("summary") or {}).get("total_rows", 0)
        issue_count = (summary.get("summary") or {}).get("issue_count", 0)
        if total_rows:
            ratio = min(1.0, issue_count / max(1, total_rows))
            score = round(100 - ratio * 100, 1)
        else:
            score = 0

        dataset_health.append(
            {
                "id": dataset.id,
                "name": dataset.name,
                "score": score,
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
        "dataset_health": sorted(dataset_health, key=lambda item: item["score"], reverse=True),
    }


@router.get("/report")
def export_report(
    format: str = "json",
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    kpis = dashboard_kpis(db, user)
    insights = dashboard_insights(db, user)
    datasets = db.query(Dataset).all()
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
            f"<tr><td>{escape(str(item.get('name', '')))}</td><td>{item.get('score', 0)}</td><td>{escape(str(item.get('last_run_at') or '-'))}</td></tr>"
            for item in insights.get("dataset_health", [])
        )
        datasets_html = "".join(
            f"<tr><td>{escape(dataset.name)}</td><td>{escape(dataset.domain)}</td><td>{escape(dataset.source_type)}</td><td>{escape(dataset.last_run_at.isoformat() if dataset.last_run_at else '-')}</td></tr>"
            for dataset in datasets
        )
        week = kpis.get("week", {})
        week_rows = "".join(
            f"<tr><td>{escape(metric)}</td><td>{data.get('current')}</td><td>{data.get('previous')}</td><td>{data.get('delta_pct')}%</td></tr>"
            for metric, data in week.items()
        )
        html = f"""
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <title>Reporte Ejecutivo - Control Center</title>
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
    <div class="card"><strong>Datasets</strong><div>{kpis.get('datasets')}</div></div>
    <div class="card"><strong>Alertas abiertas</strong><div>{kpis.get('open_cases')}</div></div>
    <div class="card"><strong>Issues</strong><div>{kpis.get('issues')}</div></div>
    <div class="card"><strong>Impacto</strong><div>{kpis.get('impact_estimated')}</div></div>
    <div class="card"><strong>Riesgo</strong><div>{kpis.get('risk_score')}</div></div>
  </div>

  <div class="section">
    <h2>Comparativa semanal</h2>
    <table>
      <thead><tr><th>Métrica</th><th>Actual</th><th>Anterior</th><th>Delta</th></tr></thead>
      <tbody>{week_rows}</tbody>
    </table>
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
      <thead><tr><th>Dataset</th><th>Score</th><th>Última corrida</th></tr></thead>
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
        if key == "week":
            continue
        writer.writerow(["kpi", key, value, ""])
    week = kpis.get("week", {})
    for metric, data in week.items():
        writer.writerow(["week", f"{metric}_current", data.get("current"), ""])
        writer.writerow(["week", f"{metric}_previous", data.get("previous"), ""])
        writer.writerow(["week", f"{metric}_delta_pct", data.get("delta_pct"), ""])
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
