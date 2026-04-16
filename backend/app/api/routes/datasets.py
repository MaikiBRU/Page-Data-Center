from datetime import datetime, timedelta
from html import escape
import csv
import io
import math
import time
from typing import Any
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_permission
from app.models.case import Case
from app.models.dataset import Dataset
from app.models.dataset_run import DatasetRun
from app.models.user import User
from app.schemas.dataset import (
    DatasetCreate,
    DatasetAssignmentUpdate,
    DatasetDetail,
    DatasetDomainUpdate,
    DatasetGenerateRequest,
    DatasetOut,
    DatasetRulesUpdate,
    DatasetRunResponse,
)
from app.services.assignment import ASSIGNMENT_MODES, pick_assignee
from app.services.data_generator import generate_dataset
from app.services.data_quality import (
    DOMAIN_RULES,
    RULES_CATALOG,
    load_records,
    recommend_actions,
    run_anomaly_detection,
    run_quality_checks,
)

router = APIRouter(prefix="/datasets", tags=["datasets"])
BASE_DIR = Path(__file__).resolve().parents[4]
UPLOAD_DIR = BASE_DIR / "data" / "uploads"

_PREVIEW_LIMIT = 20
_STATS_LIMIT = 200


def _case_due_date(severity: str, domain: str) -> tuple[datetime, int]:
    matrix = {
        "default": {"high": 24, "medium": 48, "low": 72},
        "ecommerce": {"high": 18, "medium": 40, "low": 72},
        "logistica": {"high": 12, "medium": 36, "low": 72},
        "ecommerce-logistica": {"high": 16, "medium": 40, "low": 80},
    }
    rules = matrix.get(domain, matrix["default"])
    sla_hours = rules.get(severity, matrix["default"]["medium"])
    return datetime.utcnow() + timedelta(hours=sla_hours), sla_hours


@router.post("", response_model=DatasetOut)
def create_dataset(
    payload: DatasetCreate,
    db: Session = Depends(get_db),
    user=Depends(require_permission("dataset:create")),
):
    dataset = Dataset(name=payload.name, domain=payload.domain, source_type="upload", created_by=user.id)
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


@router.patch("/{dataset_id}/domain", response_model=DatasetOut)
def update_dataset_domain(
    dataset_id: int,
    payload: DatasetDomainUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_permission("dataset:edit_domain")),
):
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    dataset.domain = payload.domain
    if dataset.rules_config and dataset.rules_config.get("disabled_rules"):
        allowed = set(DOMAIN_RULES.get(payload.domain, []))
        disabled = [
            rule for rule in dataset.rules_config.get("disabled_rules", []) if rule in allowed
        ]
        dataset.rules_config = {"disabled_rules": disabled}
    db.commit()
    db.refresh(dataset)
    return dataset


@router.get("/rules")
def list_rules(user=Depends(get_current_user)):
    return {"catalog": RULES_CATALOG, "profiles": DOMAIN_RULES}


@router.patch("/{dataset_id}/rules", response_model=DatasetOut)
def update_dataset_rules(
    dataset_id: int,
    payload: DatasetRulesUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_permission("dataset:edit_rules")),
):
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    allowed = set(DOMAIN_RULES.get(dataset.domain, []))
    invalid = [rule for rule in payload.disabled_rules if rule not in allowed]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid rules: {', '.join(invalid)}")
    dataset.rules_config = {"disabled_rules": payload.disabled_rules}
    db.commit()
    db.refresh(dataset)
    return dataset


@router.patch("/{dataset_id}/assignment", response_model=DatasetOut)
def update_dataset_assignment(
    dataset_id: int,
    payload: DatasetAssignmentUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_permission("dataset:edit_assignment")),
):
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    mode = (payload.mode or "manual").strip()
    if mode not in ASSIGNMENT_MODES:
        raise HTTPException(status_code=400, detail="Invalid assignment mode")
    owner = (payload.owner or "").strip() or None
    if mode == "owner":
        if not owner:
            raise HTTPException(status_code=400, detail="Owner required for owner mode")
        owner_row = (
            db.query(User)
            .filter(User.email == owner, User.is_active == True)  # noqa: E712
            .first()
        )
        if not owner_row:
            raise HTTPException(status_code=400, detail="Owner must be an active user")
    dataset.assignment_mode = mode
    dataset.assignment_owner = owner if mode == "owner" else None
    if mode != "round_robin":
        dataset.assignment_cursor = 0
    db.commit()
    db.refresh(dataset)
    return dataset


@router.get("", response_model=list[DatasetDetail])
def list_datasets(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return db.query(Dataset).order_by(Dataset.created_at.desc()).all()


@router.get("/{dataset_id}", response_model=DatasetDetail)
def get_dataset(dataset_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


@router.post("/{dataset_id}/upload", response_model=DatasetDetail)
def upload_dataset(
    dataset_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(require_permission("dataset:upload")),
):
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    dataset_dir = UPLOAD_DIR / f"dataset_{dataset_id}"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    file_path = dataset_dir / file.filename
    content = file.file.read()
    file_path.write_bytes(content)

    dataset.file_path = str(file_path)
    dataset.source_type = "upload"
    db.commit()
    db.refresh(dataset)
    return dataset


@router.post("/{dataset_id}/generate", response_model=DatasetDetail)
def generate_dataset_file(
    dataset_id: int,
    payload: DatasetGenerateRequest,
    db: Session = Depends(get_db),
    user=Depends(require_permission("dataset:generate")),
):
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    dataset_dir = UPLOAD_DIR / f"dataset_{dataset_id}"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    file_path = dataset_dir / "generated.csv"
    generate_dataset(str(file_path), payload.rows, payload.anomaly_rate)

    dataset.file_path = str(file_path)
    dataset.source_type = "generated"
    db.commit()
    db.refresh(dataset)
    return dataset


@router.post("/{dataset_id}/run-quality", response_model=DatasetRunResponse)
def run_quality(
    dataset_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_permission("dataset:run_quality")),
):
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset or not dataset.file_path:
        raise HTTPException(status_code=404, detail="Dataset not found or no file uploaded")

    started_at = time.perf_counter()
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

    dataset.quality_summary = {"summary": quality_summary, "issues": issues, "recommendations": recommendations}
    dataset.anomaly_summary = anomaly_summary
    dataset.last_run_at = datetime.utcnow()

    issue_rows = sum(int(issue.get("count", 0) or 0) for issue in issues)
    total_rows = int(quality_summary.get("total_rows", 0) or 0)
    anomaly_count = int(anomaly_summary.get("anomaly_count", 0) or 0)
    weighted = 0.0
    for issue in issues:
        count = float(issue.get("count", 0) or 0)
        severity = issue.get("severity", "medium")
        weight = 1.0 if severity == "high" else 0.6 if severity == "medium" else 0.3
        weighted += count * weight
    if total_rows:
        risk_score = min(100.0, (weighted / total_rows) * 100 + (anomaly_count / total_rows) * 50)
        quality_score = max(0.0, 100.0 - (issue_rows / total_rows) * 100)
    else:
        risk_score = 0.0
        quality_score = 0.0

    db.query(Case).filter(Case.dataset_id == dataset.id).delete(synchronize_session=False)
    created_cases = 0
    active_users = None
    if dataset.assignment_mode == "round_robin":
        active_users = [
            row.email
            for row in db.query(User)
            .filter(User.is_active == True)  # noqa: E712
            .order_by(User.created_at.asc(), User.id.asc())
            .all()
            if row.email
        ]

    for issue in issues:
        if issue.get("severity") == "high":
            due_date, sla_hours = _case_due_date(issue.get("severity", "high"), dataset.domain)
            assignee = pick_assignee(db, dataset, active_users)
            case = Case(
                dataset_id=dataset.id,
                title=issue.get("code", "issue"),
                severity=issue.get("severity", "medium"),
                status="open",
                assignee=assignee,
                summary=f"{issue.get('count', 0)} registros afectados",
                recommendation=next((r["action"] for r in recommendations if r["code"] == issue.get("code")), None),
                due_date=due_date,
                sla_hours=sla_hours,
            )
            db.add(case)
            created_cases += 1

    duration_ms = int((time.perf_counter() - started_at) * 1000)
    run = DatasetRun(
        dataset_id=dataset.id,
        run_at=dataset.last_run_at,
        duration_ms=duration_ms,
        total_rows=total_rows,
        issue_count=int(quality_summary.get("issue_count", 0) or 0),
        issue_rows=issue_rows,
        anomaly_count=anomaly_count,
        risk_score=round(risk_score, 1),
        quality_score=round(quality_score, 1),
    )
    db.add(run)
    db.commit()
    return DatasetRunResponse(
        dataset_id=dataset.id,
        quality_summary=dataset.quality_summary,
        anomaly_summary=dataset.anomaly_summary,
        cases_created=created_cases,
    )


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def _preview_stats(rows: list[dict], columns: list[str]) -> dict:
    stats: dict[str, dict[str, Any]] = {}
    for col in columns:
        stats[col] = {
            "missing": 0,
            "unique": set(),
            "numeric_count": 0,
            "text_count": 0,
            "min": None,
            "max": None,
            "sum": 0.0,
            "count": 0,
            "samples": [],
        }

    for row in rows:
        for col in columns:
            value = row.get(col)
            if _is_missing(value):
                stats[col]["missing"] += 1
                continue
            value_str = str(value).strip()
            if value_str and len(stats[col]["samples"]) < 3 and value_str not in stats[col]["samples"]:
                stats[col]["samples"].append(value_str)
            if len(stats[col]["unique"]) < 200:
                stats[col]["unique"].add(value_str)
            try:
                num = float(value_str)
                if not math.isfinite(num):
                    raise ValueError("non-finite value")
                stats[col]["numeric_count"] += 1
                stats[col]["sum"] += num
                stats[col]["count"] += 1
                stats[col]["min"] = num if stats[col]["min"] is None else min(stats[col]["min"], num)
                stats[col]["max"] = num if stats[col]["max"] is None else max(stats[col]["max"], num)
            except Exception:
                stats[col]["text_count"] += 1

    serialized: dict[str, dict[str, Any]] = {}
    for col, data in stats.items():
        numeric = data["numeric_count"]
        text = data["text_count"]
        total = data["count"]
        avg = round(data["sum"] / total, 2) if total else None
        serialized[col] = {
            "missing": data["missing"],
            "unique": len(data["unique"]),
            "type": "number" if numeric >= text and numeric > 0 else "text",
            "min": data["min"],
            "max": data["max"],
            "avg": avg,
            "samples": data["samples"],
        }
    return serialized


@router.get("/{dataset_id}/preview")
def preview_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset or not dataset.file_path:
        raise HTTPException(status_code=404, detail="Dataset not found or no file uploaded")
    path = Path(dataset.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Dataset file not found")

    rows: list[dict] = []
    stats_rows: list[dict] = []
    sampled = False
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = reader.fieldnames or []
            for idx, row in enumerate(reader):
                if idx < _PREVIEW_LIMIT:
                    rows.append(row)
                if idx < _STATS_LIMIT:
                    stats_rows.append(row)
                else:
                    sampled = True
                    break
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo leer el CSV: {exc}") from exc

    stats = _preview_stats(stats_rows, columns)
    return {
        "columns": columns,
        "rows": rows,
        "stats": stats,
        "sampled": sampled,
        "sample_size": len(stats_rows),
    }


@router.get("/{dataset_id}/runs")
def list_runs(
    dataset_id: int,
    limit: int = 20,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    runs = (
        db.query(DatasetRun)
        .filter(DatasetRun.dataset_id == dataset_id)
        .order_by(DatasetRun.run_at.desc())
        .limit(min(limit, 100))
        .all()
    )
    return [
        {
            "id": run.id,
            "run_at": run.run_at.isoformat() if run.run_at else None,
            "duration_ms": run.duration_ms,
            "total_rows": run.total_rows,
            "issue_count": run.issue_count,
            "issue_rows": run.issue_rows,
            "anomaly_count": run.anomaly_count,
            "risk_score": run.risk_score,
            "quality_score": run.quality_score,
        }
        for run in runs
    ]


@router.get("/{dataset_id}/report")
def export_report(
    dataset_id: int,
    format: str = "json",
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    runs = (
        db.query(DatasetRun)
        .filter(DatasetRun.dataset_id == dataset_id)
        .order_by(DatasetRun.run_at.desc())
        .limit(20)
        .all()
    )
    latest_run = runs[0] if runs else None
    issues = (dataset.quality_summary or {}).get("issues", [])
    recommendations = (dataset.quality_summary or {}).get("recommendations", [])
    anomaly_list = (dataset.anomaly_summary or {}).get("anomalies", [])
    anomaly_counts: dict[str, int] = {}
    for anomaly in anomaly_list:
        field = anomaly.get("field", "unknown")
        anomaly_counts[field] = anomaly_counts.get(field, 0) + 1

    issue_rows = sum(int(issue.get("count", 0) or 0) for issue in issues)
    total_rows = int((dataset.quality_summary or {}).get("summary", {}).get("total_rows", 0) or 0)
    anomaly_count = int((dataset.anomaly_summary or {}).get("anomaly_count", len(anomaly_list)) or 0)
    risk_score = latest_run.risk_score if latest_run and latest_run.risk_score is not None else None
    quality_score = latest_run.quality_score if latest_run and latest_run.quality_score is not None else None

    if risk_score is None:
        weighted = 0.0
        for issue in issues:
            count = float(issue.get("count", 0) or 0)
            severity = issue.get("severity", "medium")
            weight = 1.0 if severity == "high" else 0.6 if severity == "medium" else 0.3
            weighted += count * weight
        if total_rows:
            risk_score = round(
                min(100.0, (weighted / total_rows) * 100 + (anomaly_count / total_rows) * 50),
                1,
            )
            quality_score = round(max(0.0, 100.0 - (issue_rows / total_rows) * 100), 1)
        else:
            risk_score = 0.0
            quality_score = 0.0

    active_rules = (dataset.quality_summary or {}).get("summary", {}).get("active_rules", [])
    disabled_rules = (dataset.rules_config or {}).get("disabled_rules", [])
    disabled_labels = [RULES_CATALOG.get(rule, rule) for rule in disabled_rules]

    report = {
        "dataset": {
            "id": dataset.id,
            "name": dataset.name,
            "domain": dataset.domain,
            "source_type": dataset.source_type,
            "last_run_at": dataset.last_run_at.isoformat() if dataset.last_run_at else None,
        },
        "quality_summary": dataset.quality_summary or {},
        "anomaly_summary": dataset.anomaly_summary or {},
        "rules_config": dataset.rules_config or {},
        "executive": {
            "total_rows": total_rows,
            "issue_rows": issue_rows,
            "anomaly_count": anomaly_count,
            "risk_score": risk_score,
            "quality_score": quality_score,
        },
        "runs": [
            {
                "run_at": run.run_at.isoformat() if run.run_at else None,
                "duration_ms": run.duration_ms,
                "total_rows": run.total_rows,
                "issue_rows": run.issue_rows,
                "anomaly_count": run.anomaly_count,
                "risk_score": run.risk_score,
                "quality_score": run.quality_score,
            }
            for run in runs
        ],
        "generated_at": datetime.utcnow().isoformat(),
    }

    if format.lower() == "json":
        return JSONResponse(report)

    if format.lower() == "html":
        rows_html = "".join(
            f"<tr><td>{escape(str(issue.get('code', '')))}</td>"
            f"<td>{escape(str(issue.get('field', '') or '-'))}</td>"
            f"<td>{issue.get('count', 0)}</td>"
            f"<td>{escape(str(issue.get('severity', '') or '-'))}</td>"
            f"<td>{escape(str(next((r.get('action') for r in recommendations if r.get('code') == issue.get('code')), '') or '-'))}</td></tr>"
            for issue in issues
        )
        anomaly_html = "".join(
            f"<tr><td>{escape(field)}</td><td>{count}</td></tr>"
            for field, count in anomaly_counts.items()
        )
        rec_html = "".join(
            f"<tr><td>{escape(str(rec.get('label') or rec.get('code') or ''))}</td>"
            f"<td>{escape(str(rec.get('priority', '') or '-'))}</td>"
            f"<td>{rec.get('count', 0)}</td>"
            f"<td>{escape(str(rec.get('action', '') or '-'))}</td></tr>"
            for rec in recommendations
        )
        runs_html = "".join(
            f"<tr><td>{escape(str(run.run_at.isoformat() if run.run_at else '-'))}</td>"
            f"<td>{run.duration_ms or 0}</td>"
            f"<td>{run.total_rows or 0}</td>"
            f"<td>{run.issue_rows or 0}</td>"
            f"<td>{run.anomaly_count or 0}</td>"
            f"<td>{run.risk_score or 0}</td>"
            f"<td>{run.quality_score or 0}</td></tr>"
            for run in runs
        )
        html = f"""
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <title>Reporte Dataset - {escape(dataset.name)}</title>
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
    .pill {{ display: inline-block; padding: 4px 8px; border-radius: 999px; background: #ffefdf; color: #9a4d00; font-size: 11px; }}
  </style>
</head>
<body>
  <h1>Reporte de Dataset</h1>
  <div class="meta">{escape(dataset.name)} · {escape(dataset.domain)} · {escape(dataset.source_type)} · Generado: {escape(report['generated_at'])}</div>

  <div class="grid">
    <div class="card"><strong>Filas analizadas</strong><div>{total_rows}</div></div>
    <div class="card"><strong>Issues</strong><div>{issue_rows}</div></div>
    <div class="card"><strong>Anomalías</strong><div>{anomaly_count}</div></div>
    <div class="card"><strong>Riesgo</strong><div>{risk_score}</div></div>
    <div class="card"><strong>Calidad</strong><div>{quality_score}</div></div>
  </div>

  <div class="section">
    <h2>Reglas</h2>
    <p class="meta">Activas: {escape(", ".join(active_rules) or "Sin reglas")}</p>
    <p class="meta">Desactivadas: {escape(", ".join(disabled_labels) or "Sin reglas")}</p>
  </div>

  <div class="section">
    <h2>Issues</h2>
    <table>
      <thead><tr><th>Código</th><th>Campo</th><th>Casos</th><th>Severidad</th><th>Acción</th></tr></thead>
      <tbody>{rows_html or "<tr><td colspan='5'>Sin issues</td></tr>"}</tbody>
    </table>
  </div>

  <div class="section">
    <h2>Anomalías</h2>
    <table>
      <thead><tr><th>Campo</th><th>Casos</th></tr></thead>
      <tbody>{anomaly_html or "<tr><td colspan='2'>Sin anomalías</td></tr>"}</tbody>
    </table>
  </div>

  <div class="section">
    <h2>Recomendaciones</h2>
    <table>
      <thead><tr><th>Recomendación</th><th>Prioridad</th><th>Casos</th><th>Acción</th></tr></thead>
      <tbody>{rec_html or "<tr><td colspan='4'>Sin recomendaciones</td></tr>"}</tbody>
    </table>
  </div>

  <div class="section">
    <h2>Historial de corridas</h2>
    <table>
      <thead><tr><th>Fecha</th><th>Duración</th><th>Filas</th><th>Issues</th><th>Anomalías</th><th>Riesgo</th><th>Calidad</th></tr></thead>
      <tbody>{runs_html or "<tr><td colspan='7'>Sin corridas</td></tr>"}</tbody>
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
    writer.writerow(["type", "code", "field", "count", "severity", "action"])
    rec_map = {
        rec.get("code"): rec.get("action") for rec in recommendations
    }
    for issue in issues:
        writer.writerow(
            [
                "issue",
                issue.get("code"),
                issue.get("field"),
                issue.get("count"),
                issue.get("severity"),
                rec_map.get(issue.get("code"), ""),
            ]
        )
    anomalies = (dataset.anomaly_summary or {}).get("anomalies", [])
    anomaly_counts: dict[str, int] = {}
    for anomaly in anomalies:
        field = anomaly.get("field", "unknown")
        anomaly_counts[field] = anomaly_counts.get(field, 0) + 1
    for field, count in anomaly_counts.items():
        writer.writerow(
            [
                "anomaly",
                field,
                field,
                count,
                "",
                "Revisar outliers y validar rangos.",
            ]
        )

    csv_bytes = output.getvalue().encode("utf-8")
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=dataset_{dataset_id}_report.csv"
        },
    )
