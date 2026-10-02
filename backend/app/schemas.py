from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field, field_validator


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    skip: int
    limit: int


class HealthOut(BaseModel):
    status: Literal["ok"]
    database: Literal["connected"]


class IncidentCreate(BaseModel):
    title: str = Field(min_length=4, max_length=180)
    severity: Literal["critical", "high", "medium", "low"]
    service_id: int = Field(gt=0)
    summary: str | None = Field(default=None, min_length=8, max_length=2000)

    @field_validator("title", "summary")
    @classmethod
    def trim_non_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value


class ServiceOut(BaseModel):
    id: int
    name: str
    environment: str
    owner: str
    status: str
    latency_ms: float | None
    error_rate: float | None
    request_rate: float | None
    latency_history: list[float]
    error_history: list[float]
    is_synthetic: bool
    created_at: datetime
    updated_at: datetime


class IncidentOut(BaseModel):
    id: int
    title: str
    severity: str
    status: str
    service_id: int
    service: str
    summary: str
    source: str
    is_synthetic: bool
    created_at: datetime
    resolved_at: datetime | None


class IncidentDetailOut(IncidentOut):
    pass


class IncidentPage(Page[IncidentOut]):
    pass


class ServicePage(Page[ServiceOut]):
    pass


class LogEventOut(BaseModel):
    id: int
    service_id: int
    timestamp: datetime
    level: str
    message: str


class DeploymentOut(BaseModel):
    id: int
    service_id: int
    version: str
    changes: str
    timestamp: datetime


class MetricOut(BaseModel):
    id: int
    service_id: int
    timestamp: datetime
    metric_name: str
    value: float


class KnowledgeDocumentOut(BaseModel):
    id: int
    title: str
    type: str
    content: str
    source: str
    service: str
    tags: list[str]
    created_at: datetime


class EvidenceOut(BaseModel):
    id: int
    incident_id: int
    source_type: str
    source_id: int
    relevance: float
    kind: str
    source: str
    message: str
    observed_at: datetime
    confidence: float
    created_at: datetime


class EvidencePage(Page[EvidenceOut]):
    pass


class MetricPage(Page[MetricOut]):
    pass


class KnowledgeDocumentPage(Page[KnowledgeDocumentOut]):
    pass


class RecommendationOut(BaseModel):
    id: int
    incident_id: int
    action: str
    risk: str
    confidence: float
    created_at: datetime


class ActionDecision(BaseModel):
    approved_by: str = Field(min_length=2, max_length=120)

    @field_validator("approved_by")
    @classmethod
    def trim_operator(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Operator name cannot be blank.")
        return value


class ActionOut(BaseModel):
    id: int
    incident_id: int
    approved_by: str | None
    status: str
    result: str | None
    action: str
    created_at: datetime
    updated_at: datetime


class ActionPage(Page[ActionOut]):
    pass


class PostmortemOut(BaseModel):
    id: int
    incident_id: int
    summary: str
    root_cause: str
    prevention: str
    created_at: datetime
    title: str
    impact: str
    is_synthetic: bool


class PostmortemPage(Page[PostmortemOut]):
    pass


class RemediationOut(BaseModel):
    id: int
    incident_id: int
    action: str
    state: str
    created_at: datetime
    approved_at: datetime | None
    validation_passed: bool | None
    result: str | None


class RunbookOut(BaseModel):
    id: int
    title: str
    service: str
    content: str
    tags: list[str]


class DashboardOut(BaseModel):
    active_incidents: int
    critical_incidents: int
    affected_services: int
    recovery_checks_passed: int
    incidents: list[IncidentOut]
    activity: list[dict]
    services: list[ServiceOut]
    synthetic: bool