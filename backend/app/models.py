from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Service(Base):
    __tablename__ = "services"
    __table_args__ = (
        Index("ix_services_environment_status", "environment", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    environment: Mapped[str] = mapped_column(String(40), default="simulation", nullable=False)
    owner: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="Operational", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    incidents: Mapped[list["Incident"]] = relationship(back_populates="service")
    log_events: Mapped[list["LogEvent"]] = relationship(back_populates="service", cascade="all, delete-orphan")
    deployments: Mapped[list["Deployment"]] = relationship(back_populates="service", cascade="all, delete-orphan")
    metrics: Mapped[list["Metric"]] = relationship(back_populates="service", cascade="all, delete-orphan")


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint("severity IN ('critical', 'high', 'medium', 'low')", name="ck_incidents_severity"),
        CheckConstraint("status IN ('open', 'investigating', 'mitigated', 'resolved')", name="ck_incidents_status"),
        Index("ix_incidents_status_created_at", "status", "created_at"),
        Index("ix_incidents_service_created_at", "service_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="open", nullable=False)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    service: Mapped[Service] = relationship(back_populates="incidents")
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="incident", cascade="all, delete-orphan")
    recommendations: Mapped[list["Recommendation"]] = relationship(back_populates="incident", cascade="all, delete-orphan")
    actions: Mapped[list["Action"]] = relationship(back_populates="incident", cascade="all, delete-orphan")
    postmortem: Mapped["Postmortem | None"] = relationship(back_populates="incident", uselist=False, cascade="all, delete-orphan")


class LogEvent(Base):
    __tablename__ = "log_events"
    __table_args__ = (
        Index("ix_log_events_service_timestamp", "service_id", "timestamp"),
        Index("ix_log_events_level_timestamp", "level", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    service: Mapped[Service] = relationship(back_populates="log_events")


class Deployment(Base):
    __tablename__ = "deployments"
    __table_args__ = (
        Index("ix_deployments_service_timestamp", "service_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[str] = mapped_column(String(80), nullable=False)
    changes: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    service: Mapped[Service] = relationship(back_populates="deployments")


class Metric(Base):
    __tablename__ = "metrics"
    __table_args__ = (
        Index("ix_metrics_service_name_timestamp", "service_id", "metric_name", "timestamp"),
        CheckConstraint("value = value", name="ck_metrics_finite_value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    metric_name: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)

    service: Mapped[Service] = relationship(back_populates="metrics")


class CheckoutSimulationState(Base):
    __tablename__ = "checkout_simulation_state"
    __table_args__ = (
        CheckConstraint("state IN ('healthy', 'incident')", name="ck_checkout_simulation_state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    state: Mapped[str] = mapped_column(String(16), default="healthy", nullable=False)
    run_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (Index("ix_knowledge_documents_type_title", "type", "title"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalDocument(Base):
    __tablename__ = "operational_documents"
    __table_args__ = (
        Index("ix_operational_documents_status_created", "approval_status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    source: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    approval_status: Mapped[str] = mapped_column(String(24), default="approved", nullable=False)
    approved_by: Mapped[str] = mapped_column(String(120), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    indexing_status: Mapped[str] = mapped_column(String(24), default="indexed", nullable=False)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_metadata: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    chunks: Mapped[list["OperationalDocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="OperationalDocumentChunk.chunk_index"
    )


class OperationalDocumentChunk(Base):
    __tablename__ = "operational_document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_operational_document_chunk"),
        Index("ix_operational_document_chunks_document", "document_id", "chunk_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("operational_documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    document: Mapped[OperationalDocument] = relationship(back_populates="chunks")


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        CheckConstraint("relevance >= 0 AND relevance <= 1", name="ck_evidence_relevance"),
        Index("ix_evidence_incident_relevance", "incident_id", "relevance"),
        Index("ix_evidence_source", "source_type", "source_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # Polymorphic reference to a log event, deployment, metric, or knowledge document.
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    relevance: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    incident: Mapped[Incident] = relationship(back_populates="evidence")


class Recommendation(Base):
    __tablename__ = "recommendations"
    __table_args__ = (
        UniqueConstraint("incident_id", name="uq_recommendations_incident"),
        CheckConstraint("risk IN ('low', 'medium', 'high')", name="ck_recommendations_risk"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_recommendations_confidence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    risk: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    incident: Mapped[Incident] = relationship(back_populates="recommendations")


class Action(Base):
    __tablename__ = "actions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed', 'approved', 'rejected', 'simulated_validated')",
            name="ck_actions_status",
        ),
        Index("ix_actions_incident_created_at", "incident_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="proposed", nullable=False)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    incident: Mapped[Incident] = relationship(back_populates="actions")


class Postmortem(Base):
    __tablename__ = "postmortems"
    __table_args__ = (UniqueConstraint("incident_id", name="uq_postmortems_incident"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    prevention: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    incident: Mapped[Incident] = relationship(back_populates="postmortem")