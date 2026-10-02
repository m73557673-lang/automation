"""Deterministic, local-only checkout incident simulation."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import (
    Action,
    CheckoutSimulationState,
    Deployment,
    Evidence,
    Incident,
    LogEvent,
    Metric,
    Recommendation,
    Service,
    utc_now,
)
from .remediation import (
    RESTORE_POOL_ACTION,
    RESTORE_POOL_ACTION_CODE,
    add_audit_event,
)

CHECKOUT_SERVICES = (
    "API Gateway",
    "Checkout Service",
    "Order Service",
    "Database Service",
)
CHECKOUT_ENVIRONMENT = "synthetic-checkout-demo"

# Every run reuses these values and event offsets. Only backend-generated
# timestamps and the monotonically increasing run number change between runs.
HEALTHY_POINTS = {
    "API Gateway": {
        "latency_ms": (94, 95, 96, 95),
        "error_rate": (0.08, 0.09, 0.08, 0.09),
        "request_rate": (240, 242, 241, 243),
    },
    "Checkout Service": {
        "latency_ms": (108, 110, 109, 110),
        "error_rate": (0.10, 0.10, 0.09, 0.10),
        "request_rate": (120, 121, 122, 121),
    },
    "Order Service": {
        "latency_ms": (72, 73, 72, 73),
        "error_rate": (0.10, 0.10, 0.10, 0.10),
        "request_rate": (100, 101, 100, 101),
    },
    "Database Service": {
        "latency_ms": (18, 18, 19, 18),
        "error_rate": (0.05, 0.05, 0.05, 0.05),
        "request_rate": (160, 162, 161, 163),
        "db_pool_utilization_percent": (38, 39, 38, 39),
        "db_pool_size": (50, 50, 50, 50),
    },
}

INCIDENT_POINTS = {
    "API Gateway": {
        "latency_ms": (94, 96, 97, 125, 260, 410, 520),
        "error_rate": (0.08, 0.10, 0.09, 0.4, 3.2, 7.8, 9.5),
        "request_rate": (240, 242, 241, 480, 610, 620, 610),
    },
    "Checkout Service": {
        "latency_ms": (108, 110, 109, 180, 680, 1550, 2100),
        "error_rate": (0.10, 0.10, 0.09, 0.8, 6.0, 12.0, 16.0),
        "request_rate": (120, 121, 122, 245, 305, 310, 305),
    },
    "Order Service": {
        "latency_ms": (72, 73, 72, 104, 240, 390, 470),
        "error_rate": (0.10, 0.10, 0.10, 0.4, 1.8, 4.5, 5.4),
        "request_rate": (100, 101, 100, 205, 250, 255, 250),
    },
    "Database Service": {
        "latency_ms": (18, 18, 19, 50, 390, 1120, 1800),
        "error_rate": (0.05, 0.05, 0.05, 0.5, 3.5, 8.0, 12.0),
        "request_rate": (160, 162, 161, 330, 440, 450, 440),
        "db_pool_utilization_percent": (38, 39, 38, 72, 100, 100, 100),
        "db_pool_size": (50, 50, 10, 10, 10, 10, 10),
    },
}

HEALTHY_OFFSETS = (12, 9, 6, 3)
INCIDENT_OFFSETS = (8, 6, 5, 4, 2, 1, 0)


def _service_map(db: Session) -> dict[str, Service]:
    records = list(db.scalars(select(Service).where(Service.name.in_(CHECKOUT_SERVICES))).all())
    services = {service.name: service for service in records}
    for name in CHECKOUT_SERVICES:
        service = services.get(name)
        if service is None:
            service = Service(
                name=name,
                environment=CHECKOUT_ENVIRONMENT,
                owner="Checkout Demo",
                status="Operational",
            )
            db.add(service)
            services[name] = service
        elif service.environment != CHECKOUT_ENVIRONMENT:
            raise RuntimeError(
                f"Cannot initialize the synthetic checkout demo because a non-demo "
                f"service already uses the name {name!r}."
            )
    db.flush()
    return services


def _state(db: Session) -> CheckoutSimulationState:
    state = db.get(CheckoutSimulationState, 1)
    if state is None:
        state = CheckoutSimulationState(
            id=1, state="healthy", run_number=0, active_incident_id=None, updated_at=utc_now()
        )
        db.add(state)
        db.flush()
    return state


def _delete_demo_records(db: Session, service_ids: list[int]) -> None:
    db.execute(delete(Metric).where(Metric.service_id.in_(service_ids)))
    db.execute(delete(LogEvent).where(LogEvent.service_id.in_(service_ids)))
    db.execute(delete(Deployment).where(Deployment.service_id.in_(service_ids)))


def _record_points(
    db: Session,
    services: dict[str, Service],
    points: dict[str, dict[str, tuple[float, ...]]],
    offsets: tuple[int, ...],
    now: datetime,
) -> None:
    for service_name, metric_series in points.items():
        service = services[service_name]
        for index, minutes_ago in enumerate(offsets):
            timestamp = now - timedelta(minutes=minutes_ago)
            for metric_name, values in metric_series.items():
                db.add(Metric(
                    service_id=service.id,
                    timestamp=timestamp,
                    metric_name=metric_name,
                    value=float(values[index]),
                ))


def initialize_checkout_simulation(db: Session) -> None:
    """Create the demo's dedicated services and its persisted healthy baseline."""
    services = _service_map(db)
    state = _state(db)
    has_metrics = db.scalar(
        select(Metric.id)
        .where(Metric.service_id == services["API Gateway"].id)
        .limit(1)
    )
    if has_metrics is None:
        _delete_demo_records(db, [service.id for service in services.values()])
        now = datetime.now(timezone.utc)
        _record_points(db, services, HEALTHY_POINTS, HEALTHY_OFFSETS, now)
        state.state = "healthy"
        state.updated_at = now
        for service in services.values():
            service.status = "Operational"
        db.add(LogEvent(
            service_id=services["Checkout Service"].id,
            timestamp=now,
            level="info",
            message="[SYNTHETIC] Healthy checkout baseline initialized; DB_POOL_SIZE=50.",
        ))
    db.commit()


def _current_data(db: Session):
    services = _service_map(db)
    state = _state(db)
    rows = list(db.scalars(
        select(Metric)
        .where(Metric.service_id.in_([service.id for service in services.values()]))
        .order_by(Metric.timestamp, Metric.id)
    ).all())
    grouped: dict[int, dict[datetime, dict]] = {service.id: {} for service in services.values()}
    for row in rows:
        sample = grouped[row.service_id].setdefault(row.timestamp, {
            "timestamp": row.timestamp,
            "latency_ms": None,
            "error_rate_percent": None,
            "request_volume_rps": None,
            "db_pool_utilization_percent": None,
            "db_pool_size": None,
        })
        metric_key = {
            "latency_ms": "latency_ms",
            "error_rate": "error_rate_percent",
            "request_rate": "request_volume_rps",
            "db_pool_utilization_percent": "db_pool_utilization_percent",
            "db_pool_size": "db_pool_size",
        }.get(row.metric_name)
        if metric_key:
            sample[metric_key] = int(row.value) if metric_key == "db_pool_size" else row.value

    result = []
    for name in CHECKOUT_SERVICES:
        service = services[name]
        history = list(grouped[service.id].values())
        latest = history[-1] if history else {}
        result.append({
            "service_id": service.id,
            "name": name,
            "status": service.status,
            "latency_ms": latest.get("latency_ms"),
            "error_rate_percent": latest.get("error_rate_percent"),
            "request_volume_rps": latest.get("request_volume_rps"),
            "db_pool_utilization_percent": latest.get("db_pool_utilization_percent"),
            "db_pool_size": latest.get("db_pool_size"),
            "history": history,
            "is_synthetic": True,
        })
    return state, result, services


def get_checkout_metrics(db: Session) -> dict:
    state, services, _ = _current_data(db)
    return {
        "state": state.state,
        "run_number": state.run_number,
        "active_incident_id": state.active_incident_id,
        "updated_at": state.updated_at,
        "services": services,
        "is_synthetic": True,
    }


def get_checkout_health(db: Session) -> dict:
    state, services, _ = _current_data(db)
    degraded = any(service["status"] != "Operational" for service in services)
    health_services = []
    for service in services:
        if service["status"] == "Operational":
            summary = "Synthetic checks are within the healthy demo baseline."
        elif service["name"] == "Database Service":
            summary = "Synthetic connection pool exhausted at 100% utilization."
        elif service["name"] == "Checkout Service":
            summary = "Synthetic database acquisition timeouts are increasing."
        else:
            summary = "Synthetic upstream checkout latency and errors are elevated."
        health_services.append({
            "name": service["name"],
            "status": service["status"],
            "summary": summary,
            "latency_ms": service["latency_ms"],
            "error_rate_percent": service["error_rate_percent"],
            "db_pool_utilization_percent": service["db_pool_utilization_percent"],
            "is_synthetic": True,
        })
    return {
        "state": state.state,
        "overall_status": "degraded" if degraded else "healthy",
        "services": health_services,
        "is_synthetic": True,
    }


def get_checkout_events(db: Session, limit: int = 100) -> dict:
    _, _, services = _current_data(db)
    service_ids = [service.id for service in services.values()]
    logs = db.scalars(
        select(LogEvent)
        .where(LogEvent.service_id.in_(service_ids))
        .order_by(LogEvent.timestamp.desc(), LogEvent.id.desc())
        .limit(limit)
    ).all()
    deployments = db.scalars(
        select(Deployment)
        .where(Deployment.service_id.in_(service_ids))
        .order_by(Deployment.timestamp.desc(), Deployment.id.desc())
        .limit(limit)
    ).all()
    events = [{
        "id": f"log-{log.id}",
        "timestamp": log.timestamp,
        "kind": "log",
        "level": log.level,
        "service": log.service.name,
        "title": log.message.removeprefix("[SYNTHETIC] ").split(".", 1)[0],
        "detail": log.message,
        "is_synthetic": True,
    } for log in logs]
    events.extend({
        "id": f"deployment-{deployment.id}",
        "timestamp": deployment.timestamp,
        "kind": "deployment",
        "level": "info",
        "service": deployment.service.name,
        "title": f"Deployment {deployment.version}",
        "detail": deployment.changes,
        "is_synthetic": True,
    } for deployment in deployments)
    events.sort(key=lambda event: (event["timestamp"], event["id"]), reverse=True)
    return {"items": events[:limit], "is_synthetic": True}


def start_checkout_simulation(db: Session) -> dict:
    db.connection().exec_driver_sql("BEGIN IMMEDIATE")
    services = _service_map(db)
    state = _state(db)
    now = datetime.now(timezone.utc)
    if state.active_incident_id is not None:
        previous = db.scalar(
            select(Recommendation)
            .where(Recommendation.incident_id == state.active_incident_id)
            .limit(1)
        )
        if previous and previous.approval_status in {"pending", "approved"}:
            previous.approval_status = "cancelled"
        add_audit_event(
            db,
            incident_id=state.active_incident_id,
            event_type="simulation_cancelled",
            actor="Simulation restart",
            action=previous.action if previous else None,
            details={"reason": "A new checkout simulation run replaced the active run."},
        )
    _delete_demo_records(db, [service.id for service in services.values()])
    _record_points(db, services, INCIDENT_POINTS, INCIDENT_OFFSETS, now)

    services["API Gateway"].status = "Degraded"
    services["Checkout Service"].status = "Degraded"
    services["Order Service"].status = "Degraded"
    services["Database Service"].status = "Degraded"

    events = [
        (
            8, "Checkout Service", "info",
            "Healthy checkout baseline: steady request volume and low latency; DB_POOL_SIZE=50.",
        ),
        (
            5, "Database Service", "info",
            "Faulty synthetic deployment applied: DB_POOL_SIZE changed from 50 to 10.",
        ),
        (
            4, "API Gateway", "warning",
            "Synthetic checkout traffic increased to approximately 2x baseline.",
        ),
        (
            2, "Database Service", "error",
            "Synthetic database connection pool exhausted; utilization reached 100%.",
        ),
        (
            1, "Checkout Service", "error",
            "Synthetic timeout waiting for a database connection from the pool.",
        ),
        (
            0, "Order Service", "warning",
            "Synthetic upstream checkout request exceeded its timeout; retry volume increased.",
        ),
        (
            0, "API Gateway", "error",
            "Synthetic checkout requests are returning elevated 5xx errors after upstream timeouts.",
        ),
    ]
    for minutes_ago, service_name, level, message in events:
        db.add(LogEvent(
            service_id=services[service_name].id,
            timestamp=now - timedelta(minutes=minutes_ago),
            level=level,
            message=f"[SYNTHETIC] {message}",
        ))

    db.add(Deployment(
        service_id=services["Database Service"].id,
        version="checkout-demo-incident",
        changes="[SYNTHETIC] Faulty demo configuration: DB_POOL_SIZE changed from 50 to 10.",
        timestamp=now - timedelta(minutes=5),
    ))
    db.flush()

    incident = Incident(
        title="Checkout database pool exhausted — simulation",
        severity="high",
        status="investigating",
        service_id=services["Database Service"].id,
        created_at=now,
    )
    db.add(incident)
    db.flush()

    pool_metric = db.scalar(
        select(Metric)
        .where(
            Metric.service_id == services["Database Service"].id,
            Metric.metric_name == "db_pool_size",
        )
        .order_by(Metric.timestamp.desc(), Metric.id.desc())
        .limit(1)
    )
    utilization_metric = db.scalar(
        select(Metric)
        .where(
            Metric.service_id == services["Database Service"].id,
            Metric.metric_name == "db_pool_utilization_percent",
        )
        .order_by(Metric.timestamp.desc(), Metric.id.desc())
        .limit(1)
    )
    exhaustion_log = db.scalar(
        select(LogEvent)
        .where(
            LogEvent.service_id == services["Database Service"].id,
            LogEvent.message.like("%connection pool exhausted%"),
        )
        .order_by(LogEvent.timestamp.desc(), LogEvent.id.desc())
        .limit(1)
    )
    deployment = db.scalar(
        select(Deployment)
        .where(Deployment.service_id == services["Database Service"].id)
        .order_by(Deployment.timestamp.desc(), Deployment.id.desc())
        .limit(1)
    )
    support_refs = []
    for source_type, record in (
        ("metric", pool_metric),
        ("metric", utilization_metric),
        ("log", exhaustion_log),
        ("deployment", deployment),
    ):
        if record is not None:
            db.add(Evidence(
                incident_id=incident.id,
                source_type=source_type,
                source_id=record.id,
                relevance=0.95,
                created_at=now,
            ))
            support_refs.append(f"{source_type}:{record.id}")

    recommendation = Recommendation(
        incident_id=incident.id,
        action=RESTORE_POOL_ACTION,
        action_code=RESTORE_POOL_ACTION_CODE,
        risk="medium",
        confidence=0.94,
        reason=(
            "A synthetic deployment reduced the database connection pool from 50 to 10. "
            "The pool is at 100% utilization and the checkout timeline shows connection timeouts."
        ),
        supporting_evidence=__import__("json").dumps(support_refs),
        expected_impact=(
            "Synthetic pool utilization, database latency, and checkout errors should return "
            "within the predefined recovery thresholds."
        ),
        preconditions=__import__("json").dumps([
            "The active incident is the checkout simulation.",
            "The recorded database pool size is 10.",
            "A named operator explicitly approves this allowlisted action.",
        ]),
        rollback_plan=(
            "If any recovery threshold fails, restore the simulated pool value to 10, "
            "retain degraded status, and leave the incident unresolved."
        ),
        approval_status="pending",
        created_at=now,
    )
    db.add(recommendation)
    state.state = "incident"
    state.run_number += 1
    state.active_incident_id = incident.id
    state.updated_at = now
    add_audit_event(
        db,
        incident_id=incident.id,
        event_type="recommendation_created",
        actor="Simulation",
        action=RESTORE_POOL_ACTION,
        details={
            "action_code": RESTORE_POOL_ACTION_CODE,
            "risk": "medium",
            "approval_status": "pending",
            "supporting_evidence": support_refs,
        },
    )
    db.commit()
    return get_checkout_metrics(db)


def reset_checkout_simulation(db: Session) -> dict:
    db.connection().exec_driver_sql("BEGIN IMMEDIATE")
    services = _service_map(db)
    state = _state(db)
    now = datetime.now(timezone.utc)
    if state.active_incident_id is not None:
        previous = db.scalar(
            select(Recommendation)
            .where(Recommendation.incident_id == state.active_incident_id)
            .limit(1)
        )
        previous_action = db.scalar(
            select(Action)
            .where(
                Action.incident_id == state.active_incident_id,
                Action.status == "approved",
            )
            .order_by(Action.created_at.desc(), Action.id.desc())
            .limit(1)
        )
        if previous and previous.approval_status in {"pending", "approved"}:
            previous.approval_status = "cancelled"
        if previous_action:
            previous_action.status = "rejected"
            previous_action.result = "Cancelled by safe simulation reset. No infrastructure was changed."
            previous_action.updated_at = now
        add_audit_event(
            db,
            incident_id=state.active_incident_id,
            event_type="simulation_reset",
            actor="Simulation reset",
            action=previous.action if previous else None,
            details={"reason": "The checkout demo was reset to its synthetic healthy baseline."},
        )
    _delete_demo_records(db, [service.id for service in services.values()])
    _record_points(db, services, HEALTHY_POINTS, HEALTHY_OFFSETS, now)
    for service in services.values():
        service.status = "Operational"
    state.state = "healthy"
    state.active_incident_id = None
    state.updated_at = now
    db.add(LogEvent(
        service_id=services["Checkout Service"].id,
        timestamp=now,
        level="info",
        message="[SYNTHETIC] Demo reset to the healthy baseline; DB_POOL_SIZE=50.",
    ))
    db.add(Deployment(
        service_id=services["Database Service"].id,
        version="checkout-demo-healthy",
        changes="[SYNTHETIC] Demo reset restored DB_POOL_SIZE=50; no external system was changed.",
        timestamp=now,
    ))
    db.commit()
    return get_checkout_metrics(db)