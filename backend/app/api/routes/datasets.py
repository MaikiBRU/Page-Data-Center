from datetime import datetime
from html import escape
import csv
import io
import math
from typing import Any
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import (
    Principal,
    demo_quota_error,
    get_db,
    get_principal,
    get_scoped_dataset,
    require_permission,
    scope_datasets,
)
from app.core.config import settings
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
from app.services import demo_session as demo_service
from app.services.assignment import ASSIGNMENT_MODES
from app.services.data_generator import generate_dataset, generate_dataset_csv
from app.services.data_quality import DOMAIN_RULES, RULES_CATALOG
from app.services.dataset_storage import (
    DatasetPayloadMissing,
    InvalidUpload,
    dataset_has_payload,
    demo_file_size,
    open_dataset_text,
    safe_filename,
    store_demo_file,
    validate_csv_bytes,
)
from app.services.quality_run import compute_scores, execute_quality_run, rule_violations
from app.services.schema_check import check_schema

router = APIRouter(prefix="/datasets", tags=["datasets"])
BASE_DIR = Path(__file__).resolve().parents[4]
UPLOAD_DIR = BASE_DIR / "data" / "uploads"

_PREVIEW_LIMIT = 20
_STATS_LIMIT = 200
_UPLOAD_CHUNK = 64 * 1024
# Hard ceiling for authenticated uploads. Demo uploads are additionally capped
# by DEMO_MAX_FILE_SIZE_MB, which is smaller.
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _demo_generate_rows_cap() -> int:
    """Row ceiling for generated demo datasets, derived from the size quota.

    A generated row is roughly 185 bytes, measured on the existing fixtures.
    """
    return max(50, int(settings.demo_max_file_size_bytes / 185))


@router.post("", response_model=DatasetOut)
def create_dataset(
    payload: DatasetCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("dataset:create")),
):
    if principal.is_demo:
        try:
            demo_service.assert_can_add_dataset(db, principal.demo)
        except demo_service.DemoQuotaExceeded as exc:
            raise demo_quota_error(exc) from None

    if payload.domain not in DOMAIN_RULES:
        raise HTTPException(status_code=400, detail="Dominio invalido")

    dataset = Dataset(
        name=payload.name.strip()[:255] or "Dataset",
        domain=payload.domain,
        source_type="upload",
        created_by=principal.user_id,
        demo_session_id=principal.demo_session_id,
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


@router.patch("/{dataset_id}/domain", response_model=DatasetOut)
def update_dataset_domain(
    dataset_id: int,
    payload: DatasetDomainUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("dataset:edit_domain")),
):
    dataset = get_scoped_dataset(db, principal, dataset_id)
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
def list_rules(principal: Principal = Depends(get_principal)):
    return {"catalog": RULES_CATALOG, "profiles": DOMAIN_RULES}


@router.patch("/{dataset_id}/rules", response_model=DatasetOut)
def update_dataset_rules(
    dataset_id: int,
    payload: DatasetRulesUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("dataset:edit_rules")),
):
    dataset = get_scoped_dataset(db, principal, dataset_id)
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
    principal: Principal = Depends(require_permission("dataset:edit_assignment")),
):
    dataset = get_scoped_dataset(db, principal, dataset_id)
    mode = (payload.mode or "manual").strip()
    if mode not in ASSIGNMENT_MODES:
        raise HTTPException(status_code=400, detail="Invalid assignment mode")
    owner = (payload.owner or "").strip() or None
    if mode == "owner":
        if not owner:
            raise HTTPException(status_code=400, detail="Owner required for owner mode")
        owner_row = (
            db.query(User).filter(User.email == owner, User.is_active.is_(True)).first()
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
def list_datasets(db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    query = scope_datasets(db.query(Dataset), principal)
    return query.order_by(Dataset.created_at.desc()).all()


@router.get("/{dataset_id}", response_model=DatasetDetail)
def get_dataset(
    dataset_id: int, db: Session = Depends(get_db), principal: Principal = Depends(get_principal)
):
    return get_scoped_dataset(db, principal, dataset_id)


def _read_upload(file: UploadFile, max_bytes: int) -> bytes:
    """Stream the upload, aborting as soon as it exceeds the ceiling.

    Reading in chunks means an oversized body is rejected without ever being
    fully materialised in memory.
    """
    buffer = bytearray()
    while True:
        chunk = file.file.read(_UPLOAD_CHUNK)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"El archivo supera el maximo de {max_bytes // (1024 * 1024)} MB.",
            )
    return bytes(buffer)


@router.post("/{dataset_id}/upload", response_model=DatasetDetail)
def upload_dataset(
    dataset_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("dataset:upload")),
):
    dataset = get_scoped_dataset(db, principal, dataset_id)

    max_bytes = (
        settings.demo_max_file_size_bytes if principal.is_demo else _MAX_UPLOAD_BYTES
    )
    content = _read_upload(file, max_bytes)

    # The filename is attacker controlled: reduce it to a bare leaf name before
    # it is used anywhere. The client-declared content type is not trusted
    # either; the bytes themselves are parsed to confirm this is a CSV.
    filename = safe_filename(file.filename)
    try:
        validate_csv_bytes(content)
    except InvalidUpload as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    if principal.is_demo:
        session = principal.demo
        # Replacing an existing file frees the space it used.
        already = demo_file_size(db, dataset.id)
        try:
            demo_service.assert_storage_available(
                session, max(0, len(content) - already)
            )
        except demo_service.DemoQuotaExceeded as exc:
            raise demo_quota_error(exc) from None
        store_demo_file(db, dataset, filename, content)
        dataset.source_type = "upload"
        db.commit()
        demo_service.recalculate_storage(db, session)
        db.refresh(dataset)
        return dataset

    dataset_dir = UPLOAD_DIR / f"dataset_{dataset_id}"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    file_path = (dataset_dir / filename).resolve()
    # Defence in depth: even after sanitisation, refuse to write outside the
    # dataset directory.
    if not str(file_path).startswith(str(dataset_dir.resolve())):
        raise HTTPException(status_code=400, detail="Nombre de archivo invalido")
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
    principal: Principal = Depends(require_permission("dataset:generate")),
):
    dataset = get_scoped_dataset(db, principal, dataset_id)

    rows = max(1, int(payload.rows))
    anomaly_rate = min(max(float(payload.anomaly_rate), 0.0), 0.9)

    if principal.is_demo:
        session = principal.demo
        rows = min(rows, _demo_generate_rows_cap())
        content = generate_dataset_csv(rows, anomaly_rate).encode("utf-8")
        already = demo_file_size(db, dataset.id)
        try:
            demo_service.assert_storage_available(session, max(0, len(content) - already))
        except demo_service.DemoQuotaExceeded as exc:
            raise demo_quota_error(exc) from None
        store_demo_file(db, dataset, "dataset-demo.csv", content)
        dataset.source_type = "generated"
        db.commit()
        demo_service.recalculate_storage(db, session)
        db.refresh(dataset)
        return dataset

    dataset_dir = UPLOAD_DIR / f"dataset_{dataset_id}"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    file_path = dataset_dir / "generated.csv"
    generate_dataset(str(file_path), rows, anomaly_rate)

    dataset.file_path = str(file_path)
    dataset.source_type = "generated"
    db.commit()
    db.refresh(dataset)
    return dataset


@router.post("/{dataset_id}/run-quality", response_model=DatasetRunResponse)
def run_quality(
    dataset_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("dataset:run_quality")),
):
    dataset = get_scoped_dataset(db, principal, dataset_id)
    if not dataset_has_payload(db, dataset):
        # A dataset that was never given a file is a 404. One whose file_path
        # is set but whose bytes are gone is a different situation: fall
        # through so the run raises DatasetPayloadMissing and the caller is
        # told the instance lost the file rather than that it never existed.
        lost_on_disk = bool(dataset.file_path) and not dataset.demo_session_id
        if not lost_on_disk:
            raise HTTPException(
                status_code=404, detail="Dataset not found or no file uploaded"
            )

    if principal.is_demo:
        try:
            demo_service.assert_can_run(principal.demo)
        except demo_service.DemoQuotaExceeded as exc:
            raise demo_quota_error(exc) from None

    try:
        outcome = execute_quality_run(db, dataset)
    except DatasetPayloadMissing as exc:
        # The dataset exists; its bytes are gone. 409 rather than 404 so the
        # client can tell "you asked for something that never existed" apart
        # from "this instance lost the file".
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dataset file not found") from None

    if principal.is_demo:
        demo_service.register_run(db, principal.demo)

    return DatasetRunResponse(
        dataset_id=outcome.dataset_id,
        quality_summary=outcome.quality_summary,
        anomaly_summary=outcome.anomaly_summary,
        cases_created=outcome.cases_created,
        schema_status=outcome.schema_status,
        quality_score=outcome.quality_score,
        risk_score=outcome.risk_score,
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
    principal: Principal = Depends(get_principal),
):
    dataset = get_scoped_dataset(db, principal, dataset_id)

    rows: list[dict] = []
    stats_rows: list[dict] = []
    sampled = False
    columns: list[str] = []
    try:
        handle = open_dataset_text(db, dataset)
    except DatasetPayloadMissing as exc:
        # The dataset exists; its bytes are gone. 409 rather than 404 so the
        # client can tell "you asked for something that never existed" apart
        # from "this instance lost the file".
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dataset file not found") from None

    try:
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
    finally:
        close = getattr(handle, "close", None)
        if callable(close):
            close()

    stats = _preview_stats(stats_rows, columns)
    # Same sample, no extra I/O: the visitor learns whether the file matches
    # the domain before spending a quality run on it.
    schema_report = check_schema(columns, stats_rows, domain=dataset.domain)
    return {
        "columns": columns,
        "rows": rows,
        "stats": stats,
        "sampled": sampled,
        "sample_size": len(stats_rows),
        "schema": schema_report.as_dict(),
    }


@router.get("/{dataset_id}/runs")
def list_runs(
    dataset_id: int,
    limit: int = 20,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    dataset = get_scoped_dataset(db, principal, dataset_id)
    runs = (
        db.query(DatasetRun)
        .filter(DatasetRun.dataset_id == dataset.id)
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
    principal: Principal = Depends(get_principal),
):
    dataset = get_scoped_dataset(db, principal, dataset_id)

    if principal.is_demo:
        try:
            demo_service.assert_can_export(principal.demo)
        except demo_service.DemoQuotaExceeded as exc:
            raise demo_quota_error(exc) from None

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

    summary_block = (dataset.quality_summary or {}).get("summary", {})
    total_violations = rule_violations(issues)
    total_rows = int(summary_block.get("total_rows", 0) or 0)
    rows_affected = int(summary_block.get("rows_affected", 0) or 0)
    critical_rows = int(summary_block.get("critical_rows", 0) or 0)
    anomaly_count = int(
        (dataset.anomaly_summary or {}).get("anomaly_count", len(anomaly_list)) or 0
    )
    risk_score = latest_run.risk_score if latest_run and latest_run.risk_score is not None else None
    quality_score = (
        latest_run.quality_score if latest_run and latest_run.quality_score is not None else None
    )

    if risk_score is None:
        computed_risk, computed_quality = compute_scores(rows_affected, critical_rows, total_rows)
        risk_score = round(computed_risk, 1)
        quality_score = round(computed_quality, 1)

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
            "rows_affected": rows_affected,
            "critical_rows": critical_rows,
            "findings": int(summary_block.get("issue_count", 0) or 0),
            "rule_violations": total_violations,
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

    fmt = format.lower()
    if fmt not in {"json", "html", "csv"}:
        raise HTTPException(status_code=400, detail="Unsupported format")

    if principal.is_demo:
        demo_service.register_export(db, principal.demo)

    if fmt == "json":
        return JSONResponse(report)

    if fmt == "html":
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
  </style>
</head>
<body>
  <h1>Reporte de Dataset</h1>
  <div class="meta">{escape(dataset.name)} &middot; {escape(dataset.domain)} &middot; {escape(dataset.source_type)} &middot; Generado: {escape(report['generated_at'])}</div>

  <div class="grid">
    <div class="card"><strong>Filas analizadas</strong><div>{total_rows}</div></div>
    <div class="card"><strong>Filas afectadas</strong><div>{rows_affected}</div></div>
    <div class="card"><strong>Filas criticas</strong><div>{critical_rows}</div></div>
    <div class="card"><strong>Hallazgos</strong><div>{summary_block.get("issue_count", 0)} ({total_violations} violaciones)</div></div>
    <div class="card"><strong>Anomalias</strong><div>{anomaly_count}</div></div>
    <div class="card"><strong>Calidad</strong><div>{quality_score}%</div></div>
  </div>

  <div class="section">
    <h2>Reglas</h2>
    <p class="meta">Activas: {escape(", ".join(active_rules) or "Sin reglas")}</p>
    <p class="meta">Desactivadas: {escape(", ".join(disabled_labels) or "Sin reglas")}</p>
  </div>

  <div class="section">
    <h2>Issues</h2>
    <table>
      <thead><tr><th>Codigo</th><th>Campo</th><th>Casos</th><th>Severidad</th><th>Accion</th></tr></thead>
      <tbody>{rows_html or "<tr><td colspan='5'>Sin issues</td></tr>"}</tbody>
    </table>
  </div>

  <div class="section">
    <h2>Anomalias</h2>
    <table>
      <thead><tr><th>Campo</th><th>Casos</th></tr></thead>
      <tbody>{anomaly_html or "<tr><td colspan='2'>Sin anomalias</td></tr>"}</tbody>
    </table>
  </div>

  <div class="section">
    <h2>Recomendaciones</h2>
    <table>
      <thead><tr><th>Recomendacion</th><th>Prioridad</th><th>Casos</th><th>Accion</th></tr></thead>
      <tbody>{rec_html or "<tr><td colspan='4'>Sin recomendaciones</td></tr>"}</tbody>
    </table>
  </div>

  <div class="section">
    <h2>Historial de corridas</h2>
    <table>
      <thead><tr><th>Fecha</th><th>Duracion</th><th>Filas</th><th>Issues</th><th>Anomalias</th><th>Riesgo</th><th>Calidad</th></tr></thead>
      <tbody>{runs_html or "<tr><td colspan='7'>Sin corridas</td></tr>"}</tbody>
    </table>
  </div>
</body>
</html>
"""
        return Response(content=html, media_type="text/html")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["type", "code", "field", "count", "severity", "action"])
    rec_map = {rec.get("code"): rec.get("action") for rec in recommendations}
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
    for field, count in anomaly_counts.items():
        writer.writerow(["anomaly", field, field, count, "", "Revisar outliers y validar rangos."])

    csv_bytes = output.getvalue().encode("utf-8")
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=dataset_{dataset_id}_report.csv"},
    )
