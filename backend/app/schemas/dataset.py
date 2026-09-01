from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_serializer


class DatasetCreate(BaseModel):
    name: str
    domain: str


class DatasetDomainUpdate(BaseModel):
    domain: str


class DatasetGenerateRequest(BaseModel):
    rows: int = 300
    anomaly_rate: float = 0.08


class DatasetOut(BaseModel):
    id: int
    name: str
    domain: str
    source_type: str
    created_at: datetime
    last_run_at: Optional[datetime] = None
    assignment_mode: str = "manual"
    assignment_owner: Optional[str] = None
    assignment_cursor: int = 0

    class Config:
        from_attributes = True


class DatasetDetail(DatasetOut):
    file_path: Optional[str] = None
    quality_summary: Optional[Dict[str, Any]] = None
    anomaly_summary: Optional[Dict[str, Any]] = None
    rules_config: Optional[Dict[str, Any]] = None

    @field_serializer("file_path")
    def _hide_server_path(self, value: Optional[str]) -> Optional[str]:
        """Expose only the file name.

        The raw value is an absolute server path (or a demo:// locator).
        Clients only need to know whether a payload exists and what it is
        called, so the directory structure of the host is never sent out.
        """
        if not value:
            return None
        return value.replace("\\", "/").rsplit("/", 1)[-1] or None


class DatasetRunResponse(BaseModel):
    dataset_id: int
    quality_summary: Dict[str, Any]
    anomaly_summary: Dict[str, Any]
    cases_created: int
    # compatible | warning | incompatible
    schema_status: str = "compatible"
    # None when the schema did not match and nothing was measured.
    quality_score: Optional[float] = None
    risk_score: Optional[float] = None


class DatasetRulesUpdate(BaseModel):
    disabled_rules: list[str] = Field(default_factory=list)


class DatasetAssignmentUpdate(BaseModel):
    mode: str
    owner: Optional[str] = None
