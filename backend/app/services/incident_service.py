import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Evidence, Incident, Postmortem, Remediation, Runbook, Service
from ..schemas import IncidentCreate

logger = logging.getLogger("incident_commander")

RUNBOOKS = [
    {
        "title": "Elevated API latency: first response",
        "service": "api-gateway",
        "content": "Compare p95 latency with upstream timings. Check recent deployment markers and connection pool saturation. Prefer rollback simulation over changing production state.",
        "tags": "latency,api,rollback",
    },
    {
        "title": "Database connection pool saturation",
        "service": "payments-api",
        "content": "Inspect connection acquisition time, pool utilization, and slow query samples. Confirm downstream health before considering a pool-size change.",
        "tags": "database,pool,latency",
    },
    {
        "title": "Queue consumer lag",
        "service": "event-worker",
        "content": "Check consumer group lag and worker restart history. Validate that throughput recovers before marking the incident mitigated.",
        "tags": "queue,worker,throughput",
    },
    {
        "title": "Cache miss spike",
        "service": "catalog-service",
        "content": "Compare cache hit ratio across recent deploys. Verify origin capacity before attempting a cache warm-up simulation.",
        "tags": "cache,latency",
    },
]

SAMPLE_SERVICES = [
    ("api-gateway", "Edge platform", "Tier 1", "Degraded", 842, 3.8, 1240, [182, 190, 215, 248, 310, 420, 690, 842], [0.2, 0.3, 0.4, 0.7, 1.2, 1.8, 2.9, 3.8]),
    ("payments-api", "Payments", "Tier 1", "Operational", 128, 0.2, 386, [120, 122, 126, 124, 129, 131, 128, 128], [0.1, 0.2, 0.1, 0.1, 0.2, 0.2, 0.2, 0.2]),
    ("event-worker", "Data platform", "Tier 2", "Operational", 241, 0.6, 780, [220, 225, 230, 238, 241, 245, 244, 241], [0.5, 0.5, 0.6, 0.6, 0.7, 0.6, 0.6, 0.6]),
    ("catalog-service", "Commerce", "Tier 2", "Operational", 97, 0.1, 920, [94, 95, 96, 97, 98, 98, 97, 97], [0.1, 0.1, 0.1, 0.1, 0.2, 0.1, 0.1, 0.1]),
]

SAMPLE_INCIDENTS = [
    {
        "title": "Elevated API latency in edge region",
        "severity": "critical",
        "status": "investigating",
        "service": "api-gateway",
        "summary": "p95 latency rose after a simulated deployment marker. Error rate is trending upward; verify upstream and connection pool signals.",
        "source": "synthetic scenario",
        "evidence": [
            ("metric", "latency monitor", "p95 latency increased from 215 ms to 842 ms in the simulation window.", 0.94),
            ("deployment", "release tracker", "A deployment marker was recorded 11 minutes before the simulated latency increase.", 0.78),
            ("log", "gateway logs", "Repeated upstream timeout signature observed in synthetic request samples.", 0.72),
        ],
    },
    {
        "title": "Payment connection pool pressure",
        "severity": "high",
        "status": "open",
        "service": "payments-api",
        "summary": "Synthetic traces show connection acquisition delays on the payment API. No production system is connected.",
        "source": "synthetic scenario",
        "evidence": [
            ("trace", "request trace sample", "Connection acquisition accounted for 61% of synthetic request duration.", 0.83),
            ("metric", "pool monitor", "Pool utilization crossed the simulated warning threshold.", 0.76),
        ],
    },
    {
        "title": "Event worker backlog growing",
        "severity": "medium",
        "status": "open",
        "service": "event-worker",
        "summary": "A simulated consumer backlog is increasing while worker throughput remains below the scenario baseline.",
        "source": "synthetic scenario",
        "evidence": [
            ("metric", "consumer lag", "Synthetic consumer lag has risen for four consecutive intervals.", 0.81),
            ("log", "worker logs", "Two retry bursts appear in the sample worker log stream.", 0.69),
        ],
    },
]


def serialize_service(service: Service) -> dict:
    return {
        "id": service.id,
        "name": service.name,
        "owner": service.owner,
        "tier": service.tier,
        "status": service.status,
        "latency_ms": service.latency_ms,
        "error_rate": service.error_rate,
        "request_rate": service.request_rate,
        "latency_history": json.loads(service.latency_history),
        "error_history": json.loads(service.error_history),
        "is_synthetic": service.is_synthetic,
    }


def serialize_runbook(runbook: Runbook) -> dict:
    return {
        "id": runbook.id,
        "title": runbook.title,
        "service": runbook.service,
        "content": runbook.content,
        "tags": [tag.strip() for tag in runbook.tags.split(",") if tag.strip()],
    }


def seed_database(db: Session) -> None:
    if db.scalar(select(func.count()).select_from(Service)):
        return

    for item in SAMPLE_SERVICES:
        name, owner, tier, status, latency, error, rate, latency_history, error_history = item
        db.add(Service(
            name=name, owner=owner, tier=tier, status=status,
            latency_ms=latency, error_rate=error, request_rate=rate,
            latency_history=json.dumps(latency_history), error_history=json.dumps(error_history),
            is_synthetic=True,
        ))

    now = datetime.now(timezone.utc)
    for index, item in enumerate(SAMPLE_INCIDENTS):
        incident = Incident(
            title=item["title"], severity=item["severity"], status=item["status"],
            service=item["service"], summary=item["summary"], source=item["source"],
            is_synthetic=True, created_at=now - timedelta(minutes=16 + index * 23),
        )
        db.add(incident)
        db.flush()
        for offset, (kind, source, message, confidence) in enumerate(item["evidence"]):
            db.add(Evidence(
                incident_id=incident.id, kind=kind, source=source, message=message,
                confidence=confidence, observed_at=incident.created_at + timedelta(minutes=offset * 2),
            ))

    for item in RUNBOOKS:
        db.add(Runbook(**item))

    db.commit()
    logger.info("seeded synthetic demonstration records")


def get_dashboard(db: Session) -> dict:
    incidents = list(db.scalars(
        select(Incident).order_by(Incident.created_at.desc()).limit(8)
    ).all())
    services = list(db.scalars(select(Service).order_by(Service.name)).all())
    open_incidents = list(db.scalars(
        select(Incident).where(Incident.status.in_(("open", "investigating")))
    ).all())
    affected = {incident.service for incident in open_incidents}
    recovery_count = db.scalar(
        select(func.count()).select_from(Remediation).where(Remediation.state == "validated")
    ) or 0
    activity = []
    for incident in incidents:
        activity.append({
            "id": incident.id,
            "incident_id": incident.id,
            "title": incident.title,
            "detail": f"{incident.severity.title()} · {incident.service} · {incident.status}",
            "occurred_at": incident.created_at.isoformat(),
        })
    activity.sort(key=lambda item: item["occurred_at"], reverse=True)
    return {
        "active_incidents": len(open_incidents),
        "critical_incidents": sum(incident.severity == "critical" for incident in open_incidents),
        "affected_services": len(affected),
        "recovery_checks_passed": recovery_count,
        "incidents": [incident for incident in incidents],
        "activity": activity[:6],
        "services": [serialize_service(service) for service in services],
        "synthetic": True,
    }


def create_incident(db: Session, payload: IncidentCreate) -> Incident:
    service = payload.service.strip()
    incident = Incident(
        title=payload.title.strip(),
        severity=payload.severity,
        status="open",
        service=service,
        summary=payload.summary.strip(),
        source="user-created simulation",
        is_synthetic=True,
    )
    db.add(incident)
    db.flush()
    db.add(Evidence(
        incident_id=incident.id,
        kind="operator note",
        source="incident commander",
        message="Incident created in the local simulation workspace. Add correlated telemetry before drawing conclusions.",
        confidence=None,
    ))
    db.commit()
    db.refresh(incident)
    return incident


def get_investigation(db: Session, incident_id: int) -> dict | None:
    incident = db.get(Incident, incident_id)
    if incident is None:
        return None
    evidence = list(db.scalars(
        select(Evidence).where(Evidence.incident_id == incident_id).order_by(Evidence.observed_at)
    ).all())
    runbooks = list(db.scalars(
        select(Runbook).where(Runbook.service == incident.service)
    ).all())
    if not runbooks:
        runbooks = list(db.scalars(select(Runbook).order_by(Runbook.title).limit(2)).all())
    remediation = db.scalar(
        select(Remediation).where(Remediation.incident_id == incident_id).order_by(Remediation.id.desc())
    )
    postmortem = db.scalar(select(Postmortem).where(Postmortem.incident_id == incident_id))
    return {
        "incident": incident,
        "evidence": evidence,
        "runbooks": [serialize_runbook(runbook) for runbook in runbooks],
        "remediation": remediation,
        "postmortem": postmortem,
    }