import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
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
from ..schemas import IncidentCreate

logger = logging.getLogger("incident_commander")

SERVICE_FIXTURES = [
    ("api-gateway", "Edge platform", "Degraded", "Tier 1"),
    ("payments-api", "Payments", "Operational", "Tier 1"),
    ("event-worker", "Data platform", "Operational", "Tier 2"),
    ("catalog-service", "Commerce", "Operational", "Tier 2"),
]

METRIC_FIXTURES = {
    "api-gateway": {
        "latency_ms": [182, 190, 215, 248, 310, 420, 690, 842],
        "error_rate": [0.2, 0.3, 0.4, 0.7, 1.2, 1.8, 2.9, 3.8],
        "request_rate": [1190, 1202, 1210, 1222, 1230, 1238, 1240, 1240],
    },
    "payments-api": {
        "latency_ms": [120, 122, 126, 124, 129, 131, 128, 128],
        "error_rate": [0.1, 0.2, 0.1, 0.1, 0.2, 0.2, 0.2, 0.2],
        "request_rate": [370, 372, 378, 380, 382, 385, 386, 386],
    },
    "event-worker": {
        "latency_ms": [220, 225, 230, 238, 241, 245, 244, 241],
        "error_rate": [0.5, 0.5, 0.6, 0.6, 0.7, 0.6, 0.6, 0.6],
        "request_rate": [720, 734, 748, 760, 770, 775, 780, 780],
    },
    "catalog-service": {
        "latency_ms": [94, 95, 96, 97, 98, 98, 97, 97],
        "error_rate": [0.1, 0.1, 0.1, 0.1, 0.2, 0.1, 0.1, 0.1],
        "request_rate": [900, 904, 910, 914, 918, 920, 920, 920],
    },
}

KNOWLEDGE_FIXTURES = [
    (
        "Elevated API latency: first response",
        "runbook",
        "Compare p95 latency with upstream timings. Check recent deployment markers and connection pool saturation. Prefer review and rollback planning over changing production state.",
        "api-gateway",
    ),
    (
        "Database connection pool saturation",
        "runbook",
        "Inspect connection acquisition time, pool utilization, and slow query samples. Confirm downstream health before considering a pool-size change.",
        "payments-api",
    ),
    (
        "Queue consumer lag",
        "runbook",
        "Check consumer group lag and worker restart history. Validate that throughput recovers before marking the incident mitigated.",
        "event-worker",
    ),
    (
        "Cache miss spike",
        "runbook",
        "Compare cache hit ratio across recent deploys. Verify origin capacity before attempting a cache warm-up simulation.",
        "catalog-service",
    ),
]

INCIDENT_FIXTURES = [
    {
        "title": "Elevated API latency in edge region",
        "severity": "critical",
        "status": "investigating",
        "service": "api-gateway",
        "summary": "p95 latency rose after a simulated deployment marker. Error rate is trending upward; verify upstream and connection pool signals.",
        "events": [
            ("warning", "p95 latency increased from 215 ms to 842 ms in the simulation window.", 0.94),
            ("info", "A deployment marker was recorded 11 minutes before the simulated latency increase.", 0.78),
            ("warning", "Repeated upstream timeout signature observed in synthetic request samples.", 0.72),
        ],
    },
    {
        "title": "Payment connection pool pressure",
        "severity": "high",
        "status": "open",
        "service": "payments-api",
        "summary": "Synthetic traces show connection acquisition delays on the payment API. No production system is connected.",
        "events": [
            ("info", "Connection acquisition accounted for 61% of synthetic request duration.", 0.83),
            ("warning", "Pool utilization crossed the simulated warning threshold.", 0.76),
        ],
    },
    {
        "title": "Event worker backlog growing",
        "severity": "medium",
        "status": "open",
        "service": "event-worker",
        "summary": "A simulated consumer backlog is increasing while worker throughput remains below the scenario baseline.",
        "events": [
            ("warning", "Synthetic consumer lag has risen for four consecutive intervals.", 0.81),
            ("info", "Two retry bursts appear in the sample worker log stream.", 0.69),
        ],
    },
]


def _is_synthetic(service: Service) -> bool:
    environment = service.environment.casefold()
    return environment in {"simulation", "simulated", "synthetic", "demo"} or environment.startswith("synthetic-")


def serialize_service(db: Session, service: Service) -> dict:
    metrics = list(db.scalars(
        select(Metric)
        .where(Metric.service_id == service.id)
        .order_by(Metric.timestamp, Metric.id)
    ).all())
    by_name: dict[str, list[float]] = {}
    for metric in metrics:
        by_name.setdefault(metric.metric_name, []).append(float(metric.value))

    latency = by_name.get("latency_ms", [])
    errors = by_name.get("error_rate", [])
    requests = by_name.get("request_rate", [])
    return {
        "id": service.id,
        "name": service.name,
        "environment": service.environment,
        "owner": service.owner,
        "status": service.status,
        "latency_ms": latency[-1] if latency else None,
        "error_rate": errors[-1] if errors else None,
        "request_rate": requests[-1] if requests else None,
        "latency_history": latency,
        "error_history": errors,
        "is_synthetic": _is_synthetic(service),
        "created_at": service.created_at,
        "updated_at": service.updated_at,
    }


def serialize_incident(db: Session, incident: Incident) -> dict:
    context = db.scalar(
        select(LogEvent.message)
        .join(Evidence, Evidence.source_id == LogEvent.id)
        .where(
            Evidence.incident_id == incident.id,
            Evidence.source_type == "log",
            LogEvent.level == "context",
        )
        .order_by(LogEvent.timestamp, LogEvent.id)
        .limit(1)
    )
    summary = context.removeprefix("INCIDENT_CONTEXT: ").strip() if context else (
        f"Synthetic incident scenario associated with {incident.service.name}."
        if _is_synthetic(incident.service)
        else f"Incident recorded for {incident.service.name}."
    )
    return {
        "id": incident.id,
        "title": incident.title,
        "severity": incident.severity,
        "status": incident.status,
        "service_id": incident.service_id,
        "service": incident.service.name,
        "summary": summary,
        "source": "synthetic scenario" if _is_synthetic(incident.service) else incident.service.environment,
        "is_synthetic": _is_synthetic(incident.service),
        "created_at": incident.created_at,
        "resolved_at": incident.resolved_at,
    }


def _source_details(db: Session, evidence: Evidence) -> tuple[str, str, str, datetime]:
    source_type = evidence.source_type
    if source_type == "log":
        source = db.get(LogEvent, evidence.source_id)
        if source:
            return source.level, source.service.name, source.message, source.timestamp
    elif source_type == "deployment":
        source = db.get(Deployment, evidence.source_id)
        if source:
            return "deployment", f"release {source.version}", source.changes, source.timestamp
    elif source_type == "metric":
        source = db.get(Metric, evidence.source_id)
        if source:
            return "metric", source.service.name, f"{source.metric_name}: {source.value:g}", source.timestamp
    elif source_type == "knowledge":
        source = db.get(KnowledgeDocument, evidence.source_id)
        if source:
            return "runbook", source.source, source.title, source.created_at
    return source_type, "Unknown source", "The linked source record is unavailable.", evidence.created_at


def serialize_evidence(db: Session, evidence: Evidence) -> dict:
    kind, source, message, observed_at = _source_details(db, evidence)
    return {
        "id": evidence.id,
        "incident_id": evidence.incident_id,
        "source_type": evidence.source_type,
        "source_id": evidence.source_id,
        "relevance": evidence.relevance,
        "kind": kind,
        "source": source,
        "message": message,
        "observed_at": observed_at,
        "confidence": evidence.relevance,
        "created_at": evidence.created_at,
    }


def serialize_knowledge(document: KnowledgeDocument) -> dict:
    return {
        "id": document.id,
        "title": document.title,
        "type": document.type,
        "service": document.source,
        "content": document.content,
        "source": document.source,
        "tags": [],
        "created_at": document.created_at,
    }


def serialize_postmortem(db: Session, postmortem: Postmortem) -> dict:
    incident = postmortem.incident
    return {
        "id": postmortem.id,
        "incident_id": postmortem.incident_id,
        "summary": postmortem.summary,
        "root_cause": postmortem.root_cause,
        "prevention": postmortem.prevention,
        "created_at": postmortem.created_at,
        "title": f"Post-incident review: {incident.title}",
        "impact": (
            "Synthetic scenario only; no production users or traffic were affected."
            if _is_synthetic(incident.service)
            else f"Incident recorded for {incident.service.name}."
        ),
        "is_synthetic": _is_synthetic(incident.service),
    }


def serialize_remediation(action: Action) -> dict:
    return {
        "id": action.id,
        "incident_id": action.incident_id,
        "action": action.action,
        "state": "validated" if action.status == "simulated_validated" else action.status,
        "created_at": action.created_at,
        "approved_at": action.updated_at if action.approved_by else None,
        "validation_passed": True if action.status == "simulated_validated" else None,
        "result": action.result,
    }


def serialize_action(action: Action) -> dict:
    return {
        "id": action.id,
        "incident_id": action.incident_id,
        "approved_by": action.approved_by,
        "status": action.status,
        "result": action.result,
        "action": action.action,
        "created_at": action.created_at,
        "updated_at": action.updated_at,
    }


def serialize_recommendation(recommendation: Recommendation) -> dict:
    return {
        "id": recommendation.id,
        "incident_id": recommendation.incident_id,
        "action": recommendation.action,
        "risk": recommendation.risk,
        "confidence": recommendation.confidence,
        "created_at": recommendation.created_at,
    }


def _default_recommendation(incident: Incident) -> Recommendation:
    return Recommendation(
        incident_id=incident.id,
        action=(
            f"Review {incident.service.name} logs, recent deployments, and metric samples. "
            "No infrastructure action will be taken by this prototype."
        ),
        risk="low",
        confidence=0.55,
    )


def seed_database(db: Session) -> None:
    now = datetime.now(timezone.utc)

    if not db.scalar(select(func.count()).select_from(Service)):
        for name, owner, status, _tier in SERVICE_FIXTURES:
            db.add(Service(
                name=name,
                environment="simulation",
                owner=owner,
                status=status,
                created_at=now,
                updated_at=now,
            ))
        db.flush()

    services = {service.name: service for service in db.scalars(select(Service)).all()}

    if not db.scalar(select(func.count()).select_from(Metric)):
        for service_name, metric_groups in METRIC_FIXTURES.items():
            service = services.get(service_name)
            if service is None:
                continue
            for metric_name, values in metric_groups.items():
                for offset, value in enumerate(values):
                    timestamp = now - timedelta(minutes=(len(values) - offset - 1) * 5)
                    db.add(Metric(
                        service_id=service.id,
                        timestamp=timestamp,
                        metric_name=metric_name,
                        value=value,
                    ))

    if not db.scalar(select(func.count()).select_from(Deployment)):
        for service_name, version in (
            ("api-gateway", "2.14.0"),
            ("payments-api", "5.8.2"),
            ("event-worker", "1.22.1"),
            ("catalog-service", "3.6.0"),
        ):
            service = services.get(service_name)
            if service:
                db.add(Deployment(
                    service_id=service.id,
                    version=version,
                    changes=f"Synthetic deployment marker for {service_name}.",
                    timestamp=now - timedelta(minutes=35),
                ))

    if not db.scalar(select(func.count()).select_from(KnowledgeDocument)):
        for title, document_type, content, source in KNOWLEDGE_FIXTURES:
            db.add(KnowledgeDocument(
                title=title,
                type=document_type,
                content=content,
                source=source,
            ))

    db.flush()
    services = {service.name: service for service in db.scalars(select(Service)).all()}
    if not db.scalar(select(func.count()).select_from(Incident)):
        for index, item in enumerate(INCIDENT_FIXTURES):
            service = services[item["service"]]
            created_at = now - timedelta(minutes=16 + index * 23)
            incident = Incident(
                title=item["title"],
                severity=item["severity"],
                status=item["status"],
                service_id=service.id,
                created_at=created_at,
            )
            db.add(incident)
            db.flush()

            context = LogEvent(
                service_id=service.id,
                timestamp=created_at,
                level="context",
                message=f"INCIDENT_CONTEXT: {item['summary']}",
            )
            db.add(context)
            db.flush()
            db.add(Evidence(
                incident_id=incident.id,
                source_type="log",
                source_id=context.id,
                relevance=1.0,
                created_at=created_at,
            ))

            for event_index, (level, message, relevance) in enumerate(item["events"]):
                event_timestamp = created_at + timedelta(minutes=event_index * 2)
                log_event = LogEvent(
                    service_id=service.id,
                    timestamp=event_timestamp,
                    level=level,
                    message=message,
                )
                db.add(log_event)
                db.flush()
                db.add(Evidence(
                    incident_id=incident.id,
                    source_type="log",
                    source_id=log_event.id,
                    relevance=relevance,
                    created_at=event_timestamp,
                ))

            deployment = db.scalar(
                select(Deployment)
                .where(Deployment.service_id == service.id)
                .order_by(Deployment.timestamp.desc())
                .limit(1)
            )
            if deployment:
                db.add(Evidence(
                    incident_id=incident.id,
                    source_type="deployment",
                    source_id=deployment.id,
                    relevance=0.72,
                    created_at=deployment.timestamp,
                ))

            matching_document = db.scalar(
                select(KnowledgeDocument)
                .where(KnowledgeDocument.source == service.name)
                .limit(1)
            )
            if matching_document:
                db.add(Evidence(
                    incident_id=incident.id,
                    source_type="knowledge",
                    source_id=matching_document.id,
                    relevance=0.65,
                ))
            db.add(_default_recommendation(incident))
    else:
        incidents = list(db.scalars(select(Incident)).all())
        existing_recommendations = set(db.scalars(select(Recommendation.incident_id)).all())
        for incident in incidents:
            if incident.id not in existing_recommendations:
                db.add(_default_recommendation(incident))

    db.commit()
    logger.info("database initialized with records backed by SQLite")


def create_incident(db: Session, payload: IncidentCreate) -> Incident | None:
    service = db.get(Service, payload.service_id)
    if service is None:
        return None
    incident = Incident(
        title=payload.title,
        severity=payload.severity,
        status="open",
        service_id=service.id,
    )
    db.add(incident)
    db.flush()

    if payload.summary:
        context = LogEvent(
            service_id=service.id,
            timestamp=incident.created_at,
            level="context",
            message=f"INCIDENT_CONTEXT: {payload.summary}",
        )
        db.add(context)
        db.flush()
        db.add(Evidence(
            incident_id=incident.id,
            source_type="log",
            source_id=context.id,
            relevance=1.0,
        ))

    db.add(_default_recommendation(incident))
    db.commit()
    db.refresh(incident)
    return incident


def get_investigation(db: Session, incident_id: int) -> dict | None:
    incident = db.get(Incident, incident_id)
    if incident is None:
        return None
    evidence = list(db.scalars(
        select(Evidence)
        .where(Evidence.incident_id == incident_id)
        .order_by(Evidence.relevance.desc(), Evidence.created_at)
    ).all())
    recommendations = list(db.scalars(
        select(Recommendation)
        .where(Recommendation.incident_id == incident_id)
        .order_by(Recommendation.created_at.desc())
    ).all())
    action = db.scalar(
        select(Action).where(Action.incident_id == incident_id).order_by(Action.created_at.desc()).limit(1)
    )
    postmortem = db.scalar(select(Postmortem).where(Postmortem.incident_id == incident_id))
    knowledge = list(db.scalars(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.source == incident.service.name)
        .order_by(KnowledgeDocument.title)
    ).all())
    return {
        "incident": serialize_incident(db, incident),
        "evidence": [serialize_evidence(db, item) for item in evidence],
        "runbooks": [serialize_knowledge(item) for item in knowledge],
        "recommendation": serialize_recommendation(recommendations[0]) if recommendations else None,
        "remediation": serialize_remediation(action) if action else None,
        "postmortem": serialize_postmortem(db, postmortem) if postmortem else None,
    }


def get_dashboard(db: Session) -> dict:
    incidents = list(db.scalars(
        select(Incident).order_by(Incident.created_at.desc()).limit(8)
    ).all())
    all_open = list(db.scalars(
        select(Incident).where(Incident.status.in_(("open", "investigating")))
    ).all())
    services = list(db.scalars(select(Service).order_by(Service.name).limit(8)).all())
    validated_actions = db.scalar(
        select(func.count()).select_from(Action).where(Action.status == "simulated_validated")
    ) or 0
    activity = [{
        "id": incident.id,
        "incident_id": incident.id,
        "title": incident.title,
        "detail": f"{incident.severity.title()} · {incident.service.name} · {incident.status}",
        "occurred_at": incident.created_at.isoformat(),
    } for incident in incidents]
    return {
        "active_incidents": len(all_open),
        "critical_incidents": sum(item.severity == "critical" for item in all_open),
        "affected_services": len({item.service_id for item in all_open}),
        "recovery_checks_passed": validated_actions,
        "incidents": [serialize_incident(db, item) for item in incidents],
        "activity": activity,
        "services": [serialize_service(db, item) for item in services],
        "synthetic": all(_is_synthetic(item.service) for item in incidents),
    }
