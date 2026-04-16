from datetime import datetime
from pydantic import BaseModel


class CaseNoteCreate(BaseModel):
    note: str


class CaseNoteOut(BaseModel):
    id: int
    case_id: int
    author: str
    note: str
    created_at: datetime

    class Config:
        from_attributes = True
