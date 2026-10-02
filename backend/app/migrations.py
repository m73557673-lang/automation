import json
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from . import models
from .models import (
    Action,
    Deployment,
    Evidence,
    Incident,
    KnowledgeDocument,
    LogEvent,
    Metric,
    Postmortem,
    Recommendation,
    Service,
)

MIGRATION_VERSION = "normalized_incident_schema_v2"
REMEDIATION_MIGRATION_VERSION = "simulation_remediation_audit_v1"


def migrate_simulation_remediation_schema(db_engine: Engine) -> None:
    """Additive migration for the simulation-only approval and audit workflow."""
    inspector = __import__("sqlalchemy").inspect(db_engine)
    tables = set(inspector.get_table_names())
    with db_engine.begin() as connection:
        marker = connection.execute(
            text("SELECT version FROM schema_migrations WHERE version = :version"),
            {"version": REMEDIATION_MIGRATION_VERSION},
        ).first()
        if marker:
            return

        additions = {
            "recommendations": {
                "action_code": "VARCHAR(80) NOT NULL DEFAULT ''",
                "reason": "TEXT NOT NULL DEFAULT ''",
                "supporting_evidence": "TEXT NOT NULL DEFAULT '[]'",
                "expected_impact": "TEXT NOT NULL DEFAULT ''",
                "preconditions": "TEXT NOT NULL DEFAULT '[]'",
                "rollback_plan": "TEXT NOT NULL DEFAULT ''",
                "approval_status": "VARCHAR(24) NOT NULL DEFAULT 'pending'",
            },
            "checkout_simulation_state": {
                "active_incident_id": "INTEGER REFERENCES incidents(id) ON DELETE SET NULL",
            },
        }
        for table, columns in additions.items():
            if table not in tables:
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, declaration in columns.items():
                if name not in existing:
                    connection.exec_driver_sql(
                        f'ALTER TABLE "{table}" ADD COLUMN "{name}" {declaration}'
                    )
        connection.execute(
            text("INSERT INTO schema_migrations (version, applied_at) VALUES (:version, :applied_at)"),
            {"version": REMEDIATION_MIGRATION_VERSION, "applied_at": datetime.now(timezone.utc)},
        )


def _parse_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_history(value) -> list[float]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return [float(item) for item in parsed if isinstance(item, (int, float))]
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _legacy_rows(db, table: str):
    return db.execute(text(f'SELECT * FROM "legacy_{table}"')).mappings().all()


def migrate_legacy_records(db_engine: Engine) -> None:
    inspector = __import__("sqlalchemy").inspect(db_engine)
    tables = set(inspector.get_table_names())
    if "legacy_services" not in tables:
        return

    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as db:
        marker = db.execute(
            text("SELECT version FROM schema_migrations WHERE version = :version"),
            {"version": MIGRATION_VERSION},
        ).first()
        if marker:
            return

        services_by_name: dict[str, Service] = {}
        for row in _legacy_rows(db, "services"):
            service = Service(
                id=row["id"],
                name=row["name"],
                environment="simulation" if row.get("is_synthetic", True) else "development",
                owner=row.get("owner") or "Unassigned",
                status=row.get("status") or "Operational",
            )
            db.add(service)
            services_by_name[service.name] = service
        db.flush()

        incidents_by_id: dict[int, Incident] = {}
        for row in _legacy_rows(db, "incidents") if "legacy_incidents" in tables else []:
            service = services_by_name.get(row.get("service"))
            if service is None:
                continue
            created_at = _parse_datetime(row.get("created_at"))
            status = row.get("status") or "open"
            incident = Incident(
                id=row["id"],
                title=row["title"],
                severity=row.get("severity") or "medium",
                status=status,
                service_id=service.id,
                created_at=created_at or datetime.now(timezone.utc),
                resolved_at=created_at if status == "resolved" else None,
            )
            db.add(incident)
            incidents_by_id[incident.id] = incident
        db.flush()

        for incident_row in _legacy_rows(db, "incidents") if "legacy_incidents" in tables else []:
            summary = (incident_row.get("summary") or "").strip()
            incident = incidents_by_id.get(incident_row["id"])
            if not summary or incident is None:
                continue
            event = LogEvent(
                service_id=incident.service_id,
                timestamp=incident.created_at,
                level="context",
                message=f"INCIDENT_CONTEXT: {summary}",
            )
            db.add(event)
            db.flush()
            db.add(Evidence(
                incident_id=incident.id,
                source_type="log",
                source_id=event.id,
                relevance=1.0,
                created_at=event.timestamp,
            ))

        if "legacy_evidence" in tables:
            for row in _legacy_rows(db, "evidence"):
                incident = incidents_by_id.get(row["incident_id"])
                if incident is None:
                    continue
                observed_at = _parse_datetime(row.get("observed_at")) or incident.created_at
                event = LogEvent(
                    service_id=incident.service_id,
                    timestamp=observed_at,
                    level=(row.get("kind") or "info")[:16],
                    message=f"{row.get('source') or 'Legacy evidence'}: {row.get('message') or ''}",
                )
                db.add(event)
                db.flush()
                relevance = row.get("confidence")
                relevance = min(1.0, max(0.0, float(relevance))) if relevance is not None else 0.5
                db.add(Evidence(
                    incident_id=incident.id,
                    source_type="log",
                    source_id=event.id,
                    relevance=relevance,
                    created_at=observed_at,
                ))

        if "legacy_runbooks" in tables:
            for row in _legacy_rows(db, "runbooks"):
                db.add(KnowledgeDocument(
                    id=row["id"],
                    title=row["title"],
                    type="runbook",
                    content=row["content"],
                    source=row.get("service") or "legacy import",
                ))

        for row in _legacy_rows(db, "services"):
            service = services_by_name[row["name"]]
            latency = _parse_history(row.get("latency_history"))
            errors = _parse_history(row.get("error_history"))
            point_count = max(len(latency), len(errors))
            now = datetime.now(timezone.utc)
            for index in range(point_count):
                timestamp = now.replace(microsecond=0)
                timestamp = timestamp.replace(second=0)
                offset = point_count - index - 1
                from datetime import timedelta
                timestamp = timestamp - timedelta(minutes=offset * 5)
                if index < len(latency):
                    db.add(Metric(
                        service_id=service.id,
                        timestamp=timestamp,
                        metric_name="latency_ms",
                        value=latency[index],
                    ))
                if index < len(errors):
                    db.add(Metric(
                        service_id=service.id,
                        timestamp=timestamp,
                        metric_name="error_rate",
                        value=errors[index],
                    ))
            if row.get("request_rate") is not None:
                db.add(Metric(
                    service_id=service.id,
                    timestamp=now,
                    metric_name="request_rate",
                    value=float(row["request_rate"]),
                ))

        for service_name, service in services_by_name.items():
            existing_deployment = db.scalar(
                select(Deployment.id).where(Deployment.service_id == service.id).limit(1)
            )
            if not existing_deployment:
                db.add(Deployment(
                    service_id=service.id,
                    version="legacy",
                    changes="Imported from the previous local simulation dataset.",
                ))

        if "legacy_remediations" in tables:
            for row in _legacy_rows(db, "remediations"):
                if row["incident_id"] not in incidents_by_id:
                    continue
                state = row.get("state") or "proposed"
                if state == "validated":
                    state = "simulated_validated"
                db.add(Action(
                    id=row["id"],
                    incident_id=row["incident_id"],
                    approved_by=None,
                    status=state if state in {"approved", "rejected", "simulated_validated"} else "proposed",
                    result=row.get("result"),
                    action=row.get("action") or "Imported simulated action.",
                    created_at=_parse_datetime(row.get("created_at")) or datetime.now(timezone.utc),
                ))

        if "legacy_postmortems" in tables:
            for row in _legacy_rows(db, "postmortems"):
                if row["incident_id"] not in incidents_by_id:
                    continue
                summary = row.get("summary") or ""
                if row.get("title"):
                    summary = f"{row['title']}: {summary}"
                if row.get("impact"):
                    summary = f"{summary}\n\nImpact: {row['impact']}"
                db.add(Postmortem(
                    id=row["id"],
                    incident_id=row["incident_id"],
                    summary=summary,
                    root_cause=row.get("root_cause") or "Not recorded",
                    prevention=row.get("prevention") or "Not recorded",
                    created_at=_parse_datetime(row.get("created_at")) or datetime.now(timezone.utc),
                ))

        for incident in incidents_by_id.values():
            if not db.scalar(select(Recommendation.id).where(Recommendation.incident_id == incident.id)):
                db.add(Recommendation(
                    incident_id=incident.id,
                    action="Review the linked logs, metrics, and deployment context before selecting a response. No automated action is performed.",
                    risk="low",
                    confidence=0.55,
                ))

        db.execute(
            text("INSERT INTO schema_migrations (version, applied_at) VALUES (:version, :applied_at)"),
            {"version": MIGRATION_VERSION, "applied_at": datetime.now(timezone.utc)},
        )
