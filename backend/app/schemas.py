from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class IncidentCreate(BaseModel):
    title: str = Field(min_length=4, max_length=180)
    severity: Literal["critical", "high", "medium", "low"]
    service: str = Field(min_length=2, max_length=100)
    summary: str = Field(min_length=8, max_length=2000)


class IncidentOut(BaseModel):
    id: int
    title: str
    severity: str
    status: str
    service: str
    summary: str
    source: str
    is_synthetic: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class EvidenceOut(BaseModel):
    id: int
    incident_id: int
    kind: str
    source: str
    message: str
    observed_at: datetime
    confidence: float | None

    model_config = {"from_attributes": True}


class ServiceOut(BaseModel):
    id: int
    name: str
    owner: str
    tier: str
    status: str
    latency_ms: float
    error_rate: float
    request_rate: float
    latency_history: list[float]
    error_history: list[float]
    is_synthetic: bool


class RunbookOut(BaseModel):
    id: int
    title: str
    service: str
    content: str
    tags: list[str]


class RemediationOut(BaseModel):
    id: int
    incident_id: int
    action: str
    state: str
    created_at: datetime
    approved_at: datetime | None
    validation_passed: bool | None
    result: str | None

    model_config = {"from_attributes": True}


class PostmortemOut(BaseModel):
    id: int
    incident_id: int
    title: str
    summary: str
    root_cause: str
    impact: str
    prevention: str
    created_at: datetime
    is_synthetic: bool

    model_config = {"from_attributes": True}