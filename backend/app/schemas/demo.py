from datetime import datetime

from pydantic import BaseModel


class DemoLimitsOut(BaseModel):
    max_datasets: int
    max_file_size_mb: float
    max_storage_mb: float
    max_runs: int
    max_exports: int
    session_ttl_minutes: int
    idle_timeout_minutes: int


class DemoSessionStateOut(BaseModel):
    """Everything the UI needs about the sandbox. Never includes the id."""

    label: str
    expires_at: datetime
    seconds_remaining: int
    idle_seconds_remaining: int
    datasets_used: int
    datasets_max: int
    runs_used: int
    runs_max: int
    exports_used: int
    exports_max: int
    storage_bytes: int
    storage_max_bytes: int
    max_file_size_bytes: int


class DemoSessionOut(BaseModel):
    state: DemoSessionStateOut
    limits: DemoLimitsOut


class DemoStartOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    session: DemoSessionOut


class DemoConfigOut(BaseModel):
    enabled: bool
    limits: DemoLimitsOut
