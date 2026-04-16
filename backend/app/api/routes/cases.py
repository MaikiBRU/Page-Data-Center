from datetime import datetime, timedelta
import csv
import io
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.api.deps import get_current_user, get_db, require_permission
from app.models.case import Case
from app.models.dataset import Dataset
from app.models.case_note import CaseNote
from app.models.case_status_log import CaseStatusLog
from app.models.case_activity_log import CaseActivityLog
from app.schemas.case import (
    CaseBulkUpdate,
    CaseBulkCreate,
    CaseCreate,
    CaseDetail,
    CaseOut,
    CaseTimelineItem,
    CaseUpdate,
)
from app.schemas.case_note import CaseNoteCreate, CaseNoteOut
from app.services.assignment import pick_assignee

router = APIRouter(prefix="/cases", tags=["cases"])
_SEVERITIES = {"high", "medium", "low"}
_STATUSES = {"backlog", "open", "in_progress", "blocked", "escalated", "resolved"}
_SLA_MATRIX = {
    "default": {"high": 24, "medium": 48, "low": 72},
    "ecommerce": {"high": 18, "medium": 40, "low": 72},
    "logistica": {"high": 12, "medium": 36, "low": 72},
    "ecommerce-logistica": {"high": 16, "medium": 40, "low": 80},
}


def _apply_filters(
    query,
    status: str | None,
    severity: str | None,
    dataset_id: int | None,
    assignee: str | None,
    q: str | None,
    sla_state: str | None,
):
    if status:
        if "," in status:
            values = [item.strip() for item in status.split(",") if item.strip()]
            if values:
                query = query.filter(Case.status.in_(values))
        else:
            query = query.filter(Case.status == status)
    if severity:
        query = query.filter(Case.severity == severity)
    if dataset_id:
        query = query.filter(Case.dataset_id == dataset_id)
    if assignee:
        if assignee == "__none__":
            query = query.filter(Case.assignee.is_(None))
        else:
            query = query.filter(Case.assignee == assignee)
    if q:
        term = f"%{q.strip().lower()}%"
        query = query.filter(
            or_(
                Case.title.ilike(term),
                Case.summary.ilike(term),
                Case.recommendation.ilike(term),
                Case.assignee.ilike(term),
            )
        )
    if sla_state:
        now = datetime.utcnow()
        if sla_state == "overdue":
            query = query.filter(Case.due_date.is_not(None)).filter(Case.due_date < now)
        elif sla_state == "due_soon":
            soon = now + timedelta(hours=24)
            query = query.filter(Case.due_date.is_not(None)).filter(Case.due_date >= now).filter(
                Case.due_date <= soon
            )
        elif sla_state == "on_track":
            soon = now + timedelta(hours=24)
            query = query.filter(Case.due_date.is_not(None)).filter(Case.due_date > soon)
        elif sla_state == "none":
            query = query.filter(Case.due_date.is_(None))
    return query


def _apply_sort(query, sort: str | None):
    if sort == "oldest":
        return query.order_by(Case.created_at.asc())
    if sort == "sla":
        return query.order_by(Case.due_date.asc().nullslast())
    if sort == "severity":
        return query.order_by(
            Case.severity.desc(),
            Case.created_at.desc(),
        )
    if sort == "updated":
        return query.order_by(Case.updated_at.desc())
    return query.order_by(Case.created_at.desc())


@router.get("", response_model=list[CaseOut])
def list_cases(
    status: str | None = None,
    severity: str | None = None,
    dataset_id: int | None = None,
    assignee: str | None = None,
    q: str | None = None,
    sla_state: str | None = None,
    sort: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    query = db.query(Case)
    query = _apply_filters(query, status, severity, dataset_id, assignee, q, sla_state)
    query = _apply_sort(query, sort)
    return query.all()


@router.get("/summary")
def cases_summary(
    status: str | None = None,
    severity: str | None = None,
    dataset_id: int | None = None,
    assignee: str | None = None,
    q: str | None = None,
    sla_state: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    query = db.query(Case)
    query = _apply_filters(query, status, severity, dataset_id, assignee, q, sla_state)
    rows = query.all()
    now = datetime.utcnow()
    total = len(rows)
    by_status: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    overdue = 0
    due_soon = 0
    no_sla = 0
    unassigned = 0
    age_hours: list[float] = []
    remaining_hours: list[float] = []
    for item in rows:
        by_status[item.status] = by_status.get(item.status, 0) + 1
        by_severity[item.severity] = by_severity.get(item.severity, 0) + 1
        if not item.assignee:
            unassigned += 1
        if item.created_at:
            age_hours.append((now - item.created_at).total_seconds() / 3600)
        if item.due_date:
            remaining = (item.due_date - now).total_seconds() / 3600
            remaining_hours.append(remaining)
            if remaining < 0:
                overdue += 1
            elif remaining <= 24:
                due_soon += 1
        else:
            no_sla += 1

    def _avg(values: list[float]) -> float:
        if not values:
            return 0.0
        return round(sum(values) / len(values), 1)

    open_count = sum(
        count for status, count in by_status.items() if status != "resolved"
    )
    return {
        "total": total,
        "open": open_count,
        "resolved": by_status.get("resolved", 0),
        "overdue": overdue,
        "due_soon": due_soon,
        "no_sla": no_sla,
        "unassigned": unassigned,
        "avg_age_hours": _avg(age_hours),
        "avg_sla_remaining_hours": _avg(remaining_hours),
        "by_status": by_status,
        "by_severity": by_severity,
    }


@router.get("/export")
def export_cases(
    format: str = "csv",
    status: str | None = None,
    severity: str | None = None,
    dataset_id: int | None = None,
    assignee: str | None = None,
    q: str | None = None,
    sla_state: str | None = None,
    sort: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    query = db.query(Case, Dataset.name.label("dataset_name")).join(
        Dataset, Dataset.id == Case.dataset_id
    )
    query = _apply_filters(query, status, severity, dataset_id, assignee, q, sla_state)
    query = _apply_sort(query, sort)
    rows = query.all()
    payload: list[dict[str, Any]] = []
    for case, dataset_name in rows:
        payload.append(
            {
                "id": case.id,
                "title": case.title,
                "severity": case.severity,
                "status": case.status,
                "assignee": case.assignee,
                "dataset_id": case.dataset_id,
                "dataset": dataset_name,
                "summary": case.summary,
                "recommendation": case.recommendation,
                "due_date": case.due_date.isoformat() if case.due_date else None,
                "sla_hours": case.sla_hours,
                "blocked_reason": case.blocked_reason,
                "blocked_until": case.blocked_until.isoformat() if case.blocked_until else None,
                "escalated_reason": case.escalated_reason,
                "escalated_level": case.escalated_level,
                "escalated_to": case.escalated_to,
                "created_at": case.created_at.isoformat() if case.created_at else None,
                "updated_at": case.updated_at.isoformat() if case.updated_at else None,
            }
        )

    if format == "json":
        return payload

    if format != "csv":
        raise HTTPException(status_code=400, detail="Invalid format")

    output = io.StringIO()
    fieldnames = [
        "id",
        "title",
        "severity",
        "status",
        "assignee",
        "dataset_id",
        "dataset",
        "summary",
        "recommendation",
        "due_date",
        "sla_hours",
        "blocked_reason",
        "blocked_until",
        "escalated_reason",
        "escalated_level",
        "escalated_to",
        "created_at",
        "updated_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in payload:
        writer.writerow(row)

    output.seek(0)
    headers = {"Content-Disposition": "attachment; filename=cases_export.csv"}
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers=headers)


@router.post("/bulk", response_model=dict)
def bulk_update_cases(
    payload: CaseBulkUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_permission("case:update")),
):
    if not payload.case_ids:
        raise HTTPException(status_code=400, detail="case_ids required")
    fields = payload.model_fields_set
    if (
        payload.status is None
        and "assignee" not in fields
        and "due_date" not in fields
        and "sla_hours" not in fields
    ):
        raise HTTPException(status_code=400, detail="No changes provided")
    if payload.status and payload.status not in _STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    cases = db.query(Case).filter(Case.id.in_(payload.case_ids)).all()
    if not cases:
        return {"updated": 0}
    dataset_ids = {case.dataset_id for case in cases}
    dataset_map = {}
    if dataset_ids:
        rows = db.query(Dataset).filter(Dataset.id.in_(dataset_ids)).all()
        dataset_map = {row.id: row.domain for row in rows}
    now = datetime.utcnow()
    for case in cases:
        previous_status = case.status
        previous_assignee = case.assignee
        previous_due = case.due_date
        previous_sla = case.sla_hours
        if payload.status is not None:
            case.status = payload.status
        if "assignee" in fields:
            case.assignee = payload.assignee or None
        due_changed = False
        if "due_date" in fields:
            case.due_date = payload.due_date
            due_changed = True
        if "sla_hours" in fields and payload.sla_hours is not None:
            due_date, sla_hours = _compute_due_date(
                case.severity,
                payload.sla_hours,
                payload.due_date,
                dataset_map.get(case.dataset_id),
            )
            case.due_date = due_date
            case.sla_hours = sla_hours
            due_changed = True
        if "sla_hours" in fields and payload.sla_hours is None:
            case.sla_hours = None
        case.updated_at = now
        if payload.status is not None and previous_status != case.status:
            db.add(
                CaseStatusLog(
                    case_id=case.id,
                    from_status=previous_status,
                    to_status=case.status,
                    actor_email=user.email,
                )
            )
        if "assignee" in fields and previous_assignee != case.assignee:
            db.add(
                CaseActivityLog(
                    case_id=case.id,
                    event_type="assignment",
                    actor_email=user.email,
                    meta={"from": previous_assignee, "to": case.assignee},
                )
            )
        if due_changed and (previous_due != case.due_date or previous_sla != case.sla_hours):
            db.add(
                CaseActivityLog(
                    case_id=case.id,
                    event_type="sla",
                    actor_email=user.email,
                    meta={
                        "from": previous_sla,
                        "to": case.sla_hours,
                        "from_due": previous_due.isoformat() if previous_due else None,
                        "to_due": case.due_date.isoformat() if case.due_date else None,
                    },
                )
            )
    db.commit()
    return {"updated": len(cases)}


@router.post("/bulk-create", response_model=dict)
def bulk_create_cases(
    payload: CaseBulkCreate,
    db: Session = Depends(get_db),
    user=Depends(require_permission("case:create")),
):
    if not payload.items:
        raise HTTPException(status_code=400, detail="items required")
    if len(payload.items) > 200:
        raise HTTPException(status_code=400, detail="Max 200 items per batch")

    dataset_ids = {item.dataset_id for item in payload.items}
    datasets = db.query(Dataset).filter(Dataset.id.in_(dataset_ids)).all()
    dataset_map = {dataset.id: dataset for dataset in datasets}
    if len(dataset_map) != len(dataset_ids):
        raise HTTPException(status_code=400, detail="Dataset not found")

    prepared: list[dict[str, Any]] = []
    for item in payload.items:
        title = item.title.strip()
        if len(title) < 6 or len(title) > 140:
            raise HTTPException(status_code=400, detail="Title must be 6-140 chars")
        if item.severity not in _SEVERITIES:
            raise HTTPException(status_code=400, detail="Invalid severity")
        if item.status not in _STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        if item.summary and len(item.summary.strip()) < 20:
            raise HTTPException(status_code=400, detail="Summary must be 20+ chars")
        if item.recommendation and len(item.recommendation.strip()) < 20:
            raise HTTPException(status_code=400, detail="Recommendation must be 20+ chars")
        dataset = dataset_map.get(item.dataset_id)
        if not dataset:
            raise HTTPException(status_code=400, detail="Dataset not found")
        due_date, sla_hours = _compute_due_date(
            item.severity,
            item.sla_hours,
            item.due_date,
            dataset.domain,
        )
        if item.status == "blocked" and not item.blocked_reason:
            raise HTTPException(status_code=400, detail="Blocked reason required")
        if item.status == "escalated" and not item.escalated_reason:
            raise HTTPException(status_code=400, detail="Escalation reason required")
        if item.escalated_level is not None and (
            item.escalated_level < 1 or item.escalated_level > 5
        ):
            raise HTTPException(status_code=400, detail="Escalation level must be 1-5")
        prepared.append(
            {
                "item": item,
                "dataset": dataset,
                "title": title,
                "due_date": due_date,
                "sla_hours": sla_hours,
            }
        )

    created: list[int] = []
    for row in prepared:
        item = row["item"]
        dataset = row["dataset"]
        assignee = item.assignee or None
        if item.auto_assign and not assignee:
            assignee = pick_assignee(db, dataset)
        case = Case(
            dataset_id=item.dataset_id,
            title=row["title"],
            severity=item.severity,
            status=item.status,
            assignee=assignee,
            summary=item.summary.strip() if item.summary else None,
            recommendation=item.recommendation.strip() if item.recommendation else None,
            due_date=row["due_date"],
            sla_hours=row["sla_hours"],
            blocked_reason=item.blocked_reason if item.status == "blocked" else None,
            blocked_until=item.blocked_until if item.status == "blocked" else None,
            escalated_reason=item.escalated_reason if item.status == "escalated" else None,
            escalated_level=item.escalated_level if item.status == "escalated" else None,
            escalated_to=item.escalated_to if item.status == "escalated" else None,
        )
        db.add(case)
        db.flush()
        created.append(case.id)
        db.add(
            CaseStatusLog(
                case_id=case.id,
                from_status=None,
                to_status=case.status,
                actor_email=user.email,
                reason=item.status_reason
                or item.blocked_reason
                or item.escalated_reason,
            )
        )
        if case.assignee:
            db.add(
                CaseActivityLog(
                    case_id=case.id,
                    event_type="assignment",
                    actor_email=user.email,
                    meta={"from": None, "to": case.assignee},
                )
            )
    db.commit()
    return {"created": len(created), "ids": created}


@router.get("/{case_id}", response_model=CaseDetail)
def get_case(case_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    notes = db.query(CaseNote).filter(CaseNote.case_id == case_id).order_by(CaseNote.created_at.desc()).all()
    detail = CaseDetail.model_validate(case)
    detail.notes = notes
    return detail


@router.get("/{case_id}/timeline", response_model=list[CaseTimelineItem])
def case_timeline(case_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    notes = db.query(CaseNote).filter(CaseNote.case_id == case_id).all()
    status_logs = db.query(CaseStatusLog).filter(CaseStatusLog.case_id == case_id).all()
    activity_logs = db.query(CaseActivityLog).filter(CaseActivityLog.case_id == case_id).all()
    items: list[CaseTimelineItem] = []
    items.append(
        CaseTimelineItem(
            type="created",
            label="Caso creado",
            created_at=case.created_at,
            actor=None,
            meta={"status": case.status},
        )
    )
    for log in status_logs:
        label = f"Estado: {log.from_status or 'nuevo'} → {log.to_status}"
        if log.reason:
            label = f"{label} · {log.reason}"
        items.append(
            CaseTimelineItem(
                type="status",
                label=label,
                created_at=log.created_at,
                actor=log.actor_email,
                meta={"from": log.from_status, "to": log.to_status, "reason": log.reason},
            )
        )
    for log in activity_logs:
        meta = log.meta or {}
        if log.event_type == "assignment":
            label = f"Asignación: {meta.get('from') or 'Sin asignar'} → {meta.get('to') or 'Sin asignar'}"
        elif log.event_type == "sla":
            label = f"SLA actualizado: {meta.get('from') or '-'} → {meta.get('to') or '-'}"
        else:
            label = "Actualización"
        items.append(
            CaseTimelineItem(
                type=log.event_type,
                label=label,
                created_at=log.created_at,
                actor=log.actor_email,
                meta=log.meta,
            )
        )
    for note in notes:
        items.append(
            CaseTimelineItem(
                type="note",
                label="Nota agregada",
                created_at=note.created_at,
                actor=note.author,
                meta={"note": note.note},
            )
        )
    items.sort(key=lambda item: item.created_at, reverse=True)
    return items


@router.get("/{case_id}/report")
def case_report(
    case_id: int,
    format: str = "html",
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    dataset = db.query(Dataset).filter(Dataset.id == case.dataset_id).first()
    notes = db.query(CaseNote).filter(CaseNote.case_id == case_id).order_by(CaseNote.created_at.desc()).all()
    if format == "html":
        html = f"""
        <html>
          <head>
            <meta charset="utf-8" />
            <title>Reporte de Caso #{case.id}</title>
            <style>
              body {{ font-family: Arial, sans-serif; background: #0b0c10; color: #f5f5f5; padding: 32px; }}
              .panel {{ background: #141821; border-radius: 16px; padding: 24px; border: 1px solid rgba(255,255,255,0.08); }}
              h1 {{ margin-top: 0; }}
              .muted {{ color: #9aa0aa; font-size: 14px; }}
              .badge {{ display: inline-block; border-radius: 999px; padding: 4px 10px; border: 1px solid rgba(255,255,255,0.12); font-size: 12px; }}
              .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }}
              .note {{ border-top: 1px dashed rgba(255,255,255,0.1); padding-top: 8px; margin-top: 8px; }}
            </style>
          </head>
          <body>
            <div class="panel">
              <h1>Reporte de Caso #{case.id}</h1>
              <div class="muted">Dataset: {dataset.name if dataset else case.dataset_id}</div>
              <div class="muted">Actualizado: {case.updated_at}</div>
              <div style="margin-top: 12px;">
                <span class="badge">Estado: {case.status}</span>
                <span class="badge">Severidad: {case.severity}</span>
                <span class="badge">Asignado: {case.assignee or "Sin asignar"}</span>
              </div>
              <div class="grid" style="margin-top: 16px;">
                <div>
                  <h3>Resumen</h3>
                  <p>{case.summary or "-"}</p>
                </div>
                <div>
                  <h3>Recomendación</h3>
                  <p>{case.recommendation or "-"}</p>
                </div>
              </div>
              <div style="margin-top: 16px;">
                <h3>SLA</h3>
                <p>Due date: {case.due_date or "Sin SLA"} · SLA horas: {case.sla_hours or "-"}</p>
              </div>
              <div style="margin-top: 16px;">
                <h3>Estado avanzado</h3>
                <p>Bloqueo: {case.blocked_reason or "-"}</p>
                <p>Revisión esperada: {case.blocked_until or "-"}</p>
                <p>Escalado: {case.escalated_reason or "-"}</p>
                <p>Nivel: {case.escalated_level or "-"}</p>
                <p>Escalado a: {case.escalated_to or "-"}</p>
              </div>
              <div style="margin-top: 16px;">
                <h3>Notas</h3>
                {"".join([f"<div class='note'><strong>{n.author}</strong> ({n.created_at})<br/>{n.note}</div>" for n in notes]) or "<p class='muted'>Sin notas</p>"}
              </div>
            </div>
          </body>
        </html>
        """
        return HTMLResponse(content=html)

    if format == "pdf":
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"reportlab no instalado: {exc}") from exc
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        y = height - 50
        c.setFont("Helvetica-Bold", 16)
        c.drawString(40, y, f"Reporte de Caso #{case.id}")
        y -= 20
        c.setFont("Helvetica", 10)
        c.drawString(40, y, f"Dataset: {dataset.name if dataset else case.dataset_id}")
        y -= 15
        c.drawString(40, y, f"Estado: {case.status} | Severidad: {case.severity} | Asignado: {case.assignee or 'Sin asignar'}")
        y -= 20
        c.drawString(40, y, f"SLA: {case.sla_hours or '-'} horas | Due: {case.due_date or 'Sin SLA'}")
        y -= 25
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y, "Estado avanzado")
        y -= 15
        c.setFont("Helvetica", 10)
        c.drawString(40, y, f"Bloqueo: {case.blocked_reason or '-'}")
        y -= 12
        c.drawString(40, y, f"Revisión esperada: {case.blocked_until or '-'}")
        y -= 12
        c.drawString(40, y, f"Escalado: {case.escalated_reason or '-'}")
        y -= 12
        c.drawString(40, y, f"Nivel: {case.escalated_level or '-'}")
        y -= 12
        c.drawString(40, y, f"Escalado a: {case.escalated_to or '-'}")
        y -= 20
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y, "Resumen")
        y -= 15
        c.setFont("Helvetica", 10)
        for line in (case.summary or "-").splitlines():
            c.drawString(40, y, line[:120])
            y -= 12
            if y < 80:
                c.showPage()
                y = height - 50
        y -= 10
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y, "Recomendación")
        y -= 15
        c.setFont("Helvetica", 10)
        for line in (case.recommendation or "-").splitlines():
            c.drawString(40, y, line[:120])
            y -= 12
            if y < 80:
                c.showPage()
                y = height - 50
        y -= 10
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y, "Notas")
        y -= 15
        c.setFont("Helvetica", 10)
        if not notes:
            c.drawString(40, y, "Sin notas")
        else:
            for note in notes:
                c.drawString(40, y, f"{note.author} ({note.created_at})")
                y -= 12
                for line in note.note.splitlines():
                    c.drawString(60, y, line[:110])
                    y -= 12
                    if y < 80:
                        c.showPage()
                        y = height - 50
                y -= 6
        c.showPage()
        c.save()
        buffer.seek(0)
        headers = {"Content-Disposition": f"attachment; filename=case_{case.id}.pdf"}
        return StreamingResponse(buffer, media_type="application/pdf", headers=headers)

    raise HTTPException(status_code=400, detail="Invalid format")


@router.patch("/{case_id}", response_model=CaseOut)
def update_case(
    case_id: int,
    payload: CaseUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_permission("case:update")),
):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if payload.status not in _STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    dataset = None
    if "sla_hours" in payload.model_fields_set or "due_date" in payload.model_fields_set:
        dataset = db.query(Dataset).filter(Dataset.id == case.dataset_id).first()
    previous_status = case.status
    previous_assignee = case.assignee
    previous_due = case.due_date
    previous_sla = case.sla_hours
    fields = payload.model_fields_set
    case.status = payload.status
    if "assignee" in fields:
        case.assignee = payload.assignee or None
    if payload.summary is not None:
        case.summary = payload.summary
    if payload.recommendation is not None:
        case.recommendation = payload.recommendation
    if "blocked_reason" in fields:
        case.blocked_reason = payload.blocked_reason
    if "blocked_until" in fields:
        case.blocked_until = payload.blocked_until
    if "escalated_reason" in fields:
        case.escalated_reason = payload.escalated_reason
    if "escalated_level" in fields:
        case.escalated_level = payload.escalated_level
    if "escalated_to" in fields:
        case.escalated_to = payload.escalated_to

    if payload.status == "blocked":
        reason = case.blocked_reason or payload.status_reason
        if not reason:
            raise HTTPException(status_code=400, detail="Blocked reason required")
        case.blocked_reason = reason
    if payload.status != "blocked":
        case.blocked_reason = None
        case.blocked_until = None
    if payload.status == "escalated":
        reason = case.escalated_reason or payload.status_reason
        if not reason:
            raise HTTPException(status_code=400, detail="Escalation reason required")
        case.escalated_reason = reason
        if case.escalated_level is None:
            case.escalated_level = 1
        if case.escalated_level < 1 or case.escalated_level > 5:
            raise HTTPException(status_code=400, detail="Escalation level must be 1-5")
    if payload.status != "escalated":
        case.escalated_reason = None
        case.escalated_level = None
        case.escalated_to = None

    due_changed = False
    if "due_date" in fields:
        case.due_date = payload.due_date
        due_changed = True
    if "sla_hours" in fields and payload.sla_hours is not None:
        due_date, sla_hours = _compute_due_date(
            case.severity,
            payload.sla_hours,
            payload.due_date,
            dataset.domain if dataset else None,
        )
        case.due_date = due_date
        case.sla_hours = sla_hours
        due_changed = True
    if "sla_hours" in fields and payload.sla_hours is None:
        case.sla_hours = None
    case.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(case)
    if previous_status != case.status:
        db.add(
            CaseStatusLog(
                case_id=case.id,
                from_status=previous_status,
                to_status=case.status,
                actor_email=user.email,
                reason=payload.status_reason
                or case.blocked_reason
                or case.escalated_reason,
            )
        )
        db.commit()
    if "assignee" in fields and previous_assignee != case.assignee:
        db.add(
            CaseActivityLog(
                case_id=case.id,
                event_type="assignment",
                actor_email=user.email,
                meta={"from": previous_assignee, "to": case.assignee},
            )
        )
        db.commit()
    if due_changed and (previous_due != case.due_date or previous_sla != case.sla_hours):
        db.add(
            CaseActivityLog(
                case_id=case.id,
                event_type="sla",
                actor_email=user.email,
                meta={
                    "from": previous_sla,
                    "to": case.sla_hours,
                    "from_due": previous_due.isoformat() if previous_due else None,
                    "to_due": case.due_date.isoformat() if case.due_date else None,
                },
            )
        )
        db.commit()
    return case


@router.post("", response_model=CaseOut, status_code=201)
def create_case(
    payload: CaseCreate, db: Session = Depends(get_db), user=Depends(require_permission("case:create"))
):
    title = payload.title.strip()
    if len(title) < 6 or len(title) > 140:
        raise HTTPException(status_code=400, detail="Title must be 6-140 chars")
    if payload.severity not in _SEVERITIES:
        raise HTTPException(status_code=400, detail="Invalid severity")
    if payload.status not in _STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    if payload.summary and len(payload.summary.strip()) < 20:
        raise HTTPException(status_code=400, detail="Summary must be 20+ chars")
    if payload.recommendation and len(payload.recommendation.strip()) < 20:
        raise HTTPException(status_code=400, detail="Recommendation must be 20+ chars")
    dataset = db.query(Dataset).filter(Dataset.id == payload.dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=400, detail="Dataset not found")
    due_date, sla_hours = _compute_due_date(
        payload.severity,
        payload.sla_hours,
        payload.due_date,
        dataset.domain,
    )
    if payload.status == "blocked" and not payload.blocked_reason:
        raise HTTPException(status_code=400, detail="Blocked reason required")
    if payload.status == "escalated" and not payload.escalated_reason:
        raise HTTPException(status_code=400, detail="Escalation reason required")
    if payload.escalated_level is not None and (
        payload.escalated_level < 1 or payload.escalated_level > 5
    ):
        raise HTTPException(status_code=400, detail="Escalation level must be 1-5")
    assignee = payload.assignee or None
    if payload.auto_assign and not assignee:
        assignee = pick_assignee(db, dataset)
    case = Case(
        dataset_id=payload.dataset_id,
        title=title,
        severity=payload.severity,
        status=payload.status,
        assignee=assignee,
        summary=payload.summary.strip() if payload.summary else None,
        recommendation=payload.recommendation.strip() if payload.recommendation else None,
        due_date=due_date,
        sla_hours=sla_hours,
        blocked_reason=payload.blocked_reason,
        blocked_until=payload.blocked_until,
        escalated_reason=payload.escalated_reason,
        escalated_level=payload.escalated_level,
        escalated_to=payload.escalated_to,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    db.add(
        CaseStatusLog(
            case_id=case.id,
            from_status=None,
            to_status=case.status,
            actor_email=user.email,
            reason=payload.status_reason
            or payload.blocked_reason
            or payload.escalated_reason,
        )
    )
    if case.assignee:
        db.add(
            CaseActivityLog(
                case_id=case.id,
                event_type="assignment",
                actor_email=user.email,
                meta={"from": None, "to": case.assignee},
            )
        )
    db.commit()
    return case


@router.post("/{case_id}/notes", response_model=CaseNoteOut)
def add_note(
    case_id: int,
    payload: CaseNoteCreate,
    db: Session = Depends(get_db),
    user=Depends(require_permission("case:add_note")),
):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    note = CaseNote(case_id=case_id, author=user.email, note=payload.note)
    db.add(note)
    db.commit()
    db.refresh(note)
    case.updated_at = datetime.utcnow()
    db.commit()
    return note
def _default_sla_hours(severity: str, domain: str | None = None) -> int:
    matrix = _SLA_MATRIX.get(domain or "", _SLA_MATRIX["default"])
    return matrix.get(severity, _SLA_MATRIX["default"]["medium"])


def _compute_due_date(
    severity: str,
    sla_hours: int | None = None,
    due_date: datetime | None = None,
    domain: str | None = None,
) -> tuple[datetime | None, int | None]:
    if due_date:
        return due_date, sla_hours
    if sla_hours is None:
        sla_hours = _default_sla_hours(severity, domain)
    if sla_hours <= 0 or sla_hours > 168:
        raise HTTPException(status_code=400, detail="SLA must be between 1 and 168 hours")
    return datetime.utcnow() + timedelta(hours=sla_hours), sla_hours
