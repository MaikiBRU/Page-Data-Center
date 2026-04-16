from datetime import datetime
from typing import List, Optional, Literal

from pydantic import BaseModel, Field

from app.schemas.case_note import CaseNoteOut


class CaseOut(BaseModel):
    id: int
    dataset_id: int
    title: str
    severity: str
    status: str
    assignee: Optional[str] = None
    summary: Optional[str] = None
    recommendation: Optional[str] = None
    due_date: Optional[datetime] = None
    sla_hours: Optional[int] = None
    blocked_reason: Optional[str] = None
    blocked_until: Optional[datetime] = None
    escalated_reason: Optional[str] = None
    escalated_level: Optional[int] = None
    escalated_to: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CaseUpdate(BaseModel):
    status: str
    assignee: Optional[str] = None
    summary: Optional[str] = None
    recommendation: Optional[str] = None
    due_date: Optional[datetime] = None
    sla_hours: Optional[int] = None
    status_reason: Optional[str] = None
    blocked_reason: Optional[str] = None
    blocked_until: Optional[datetime] = None
    escalated_reason: Optional[str] = None
    escalated_level: Optional[int] = None
    escalated_to: Optional[str] = None


class CaseCreate(BaseModel):
    dataset_id: int
    title: str
    severity: str = "medium"
    status: str = "open"
    assignee: Optional[str] = None
    auto_assign: bool = False
    summary: Optional[str] = None
    recommendation: Optional[str] = None
    due_date: Optional[datetime] = None
    sla_hours: Optional[int] = None
    status_reason: Optional[str] = None
    blocked_reason: Optional[str] = None
    blocked_until: Optional[datetime] = None
    escalated_reason: Optional[str] = None
    escalated_level: Optional[int] = None
    escalated_to: Optional[str] = None


class CaseDetail(CaseOut):
    notes: List[CaseNoteOut] = Field(default_factory=list)


class CaseStatusLogOut(BaseModel):
    id: int
    case_id: int
    from_status: Optional[str] = None
    to_status: str
    actor_email: Optional[str] = None
    reason: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class CaseTimelineItem(BaseModel):
    type: Literal["created", "status", "note", "assignment", "sla"]
    label: str
    created_at: datetime
    actor: Optional[str] = None
    meta: Optional[dict] = None


class CaseBulkUpdate(BaseModel):
    case_ids: List[int]
    status: Optional[str] = None
    assignee: Optional[str] = None
    due_date: Optional[datetime] = None
    sla_hours: Optional[int] = None


class CaseBulkCreate(BaseModel):
    items: List[CaseCreate]
