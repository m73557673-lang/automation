"""Allowlisted simulation-only remediation and its append-only audit records."""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Action,
    CheckoutSimulationState,
    Incident,
    LogEvent,
    Metric,
    Recommendation,
    RemediationAuditEvent,
    Service,
    utc_now,
)
from .incident_service import serialize_remediation

CHECKOUT_DEMO_ENVIRONMENT = "synthetic-checkout-demo"
RESTORE_POOL_ACTION_CODE = "restore_db_pool_size_50"
RESTORE_POOL_ACTION = "Restore the simulated DB_POOL_SIZE from 10 to 50."
RECOVERY_THRESHOLDS = {
    "db_pool_size": 50,
    "db_pool_utilization_percent_max": 70,
    "database_latency_ms_max": 250,
    "database_error_rate_percent_max": 1,
    "checkout_latency_ms_max": 300,
    "checkout_error_rate_percent_max": 1,
}


class SimulationRemediationError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def add_audit_event(
    db: Session,
    *,
    incident_id: int | None,
    event_type: str,
    actor: str | None = None,
    action: str | None = None,
    details: dict | None = None,
) -> RemediationAuditEvent:
    event = RemediationAuditEvent(
        incident_id=incident_id,
        event_type=event_type,
        actor=actor,
        action=action,
        details=json.dumps(details or {}, sort_keys=True),
    )
    db.add(event)
    return event


def serialize_recommendation(recommendation: Recommendation) -> dict:
    try:
        evidence = json.loads(recommendation.supporting_evidence or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        evidence = []
    try:
        preconditions = json.loads(recommendation.preconditions or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        preconditions = []
    return {
        "id": recommendation.id,
        "incident_id": recommendation.incident_id,
        "action": recommendation.action,
        "action_code": recommendation.action_code,
        "risk": recommendation.risk,
        "confidence": recommendation.confidence,
        "reason": recommendation.reason,
        "supporting_evidence": evidence if isinstance(evidence, list) else [],
        "expected_impact": recommendation.expected_impact,
        "preconditions": preconditions if isinstance(preconditions, list) else [],
        "rollback_plan": recommendation.rollback_plan,
        "approval_status": recommendation.approval_status,
        "created_at": recommendation.created_at,
    }


def serialize_audit_event(event: RemediationAuditEvent) -> dict:
    try:
        details = json.loads(event.details or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        details = {}
    return {
        "id": event.id,
        "incident_id": event.incident_id,
        "event_type": event.event_type,
        "actor": event.actor,
        "action": event.action,
        "details": details if isinstance(details, dict) else {},
        "created_at": event.created_at,
    }


def active_checkout_recommendation(
    db: Session,
    incident_id: int,
    requested_action_code: str | None,
) -> tuple[Incident | None, Recommendation | None, str | None]:
    incident = db.get(Incident, incident_id)
    if incident is None:
        return None, None, "Incident not found."

    simulation = db.get(CheckoutSimulationState, 1)
    if (
        simulation is None
        or simulation.state != "incident"
        or simulation.active_incident_id != incident.id
    ):
        return incident, None, "The incident is not the active checkout simulation."
    if (
        incident.service.name != "Database Service"
        or incident.service.environment != CHECKOUT_DEMO_ENVIRONMENT
    ):
        return incident, None, "Remediation is restricted to the synthetic checkout demo."
    if incident.status not in {"open", "investigating"}:
        return incident, None, "The incident is not in an eligible state."

    recommendation = db.scalar(
        select(Recommendation)
        .where(Recommendation.incident_id == incident.id)
        .order_by(Recommendation.created_at.desc(), Recommendation.id.desc())
        .limit(1)
    )
    if recommendation is None:
        return incident, None, "No remediation recommendation exists for this incident."
    if (
        recommendation.action_code != RESTORE_POOL_ACTION_CODE
        or recommendation.action != RESTORE_POOL_ACTION
        or requested_action_code != RESTORE_POOL_ACTION_CODE
    ):
        return incident, recommendation, "The requested action is not on the simulation allowlist."
    return incident, recommendation, None


def _write_rejection(
    db: Session,
    *,
    incident_id: int | None,
    actor: str | None,
    action_code: str | None,
    event_type: str,
    detail: str,
    status_code: int = 409,
    extra: dict | None = None,
) -> None:
    add_audit_event(
        db,
        incident_id=incident_id,
        event_type=event_type,
        actor=actor,
        action=action_code,
        details={"reason": detail, **(extra or {})},
    )
    db.commit()
    raise SimulationRemediationError(status_code, detail)


def _validate_request_identity(operator_name: str | None) -> str | None:
    if not isinstance(operator_name, str):
        return None
    clean = operator_name.strip()
    return clean if len(clean) >= 2 else None


def _latest_metric(db: Session, service_id: int, metric_name: str) -> Metric | None:
    return db.scalar(
        select(Metric)
        .where(Metric.service_id == service_id, Metric.metric_name == metric_name)
        .order_by(Metric.timestamp.desc(), Metric.id.desc())
        .limit(1)
    )


def approve_simulated_remediation(
    db: Session,
    *,
    incident_id: int,
    operator_name: str | None,
    action_code: str | None,
    recommendation_id: int | None,
) -> dict:
    db.connection().exec_driver_sql("BEGIN IMMEDIATE")
    actor = _validate_request_identity(operator_name)
    incident, recommendation, reason = active_checkout_recommendation(
        db, incident_id, action_code
    )
    if incident is None:
        _write_rejection(
            db, incident_id=None, actor=actor, action_code=action_code,
            event_type="approval_rejected", detail=reason or "Incident not found.",
            status_code=404, extra={"requested_incident_id": incident_id},
        )
    if actor is None:
        reason = "A clearly identified operator name is required."
    elif reason is None and recommendation_id != recommendation.id:
        reason = "The approved recommendation ID does not match the active recommendation."
    elif reason is None and recommendation.approval_status != "pending":
        reason = f"This recommendation is already {recommendation.approval_status}."
    if reason:
        _write_rejection(
            db, incident_id=incident.id, actor=actor, action_code=action_code,
            event_type="approval_rejected", detail=reason,
            extra={"recommendation_id": recommendation_id},
        )

    pool_size = _latest_metric(db, incident.service_id, "db_pool_size")
    if pool_size is None or pool_size.value != 10:
        _write_rejection(
            db, incident_id=incident.id, actor=actor, action_code=action_code,
            event_type="approval_rejected",
            detail="The active synthetic pool size is not the expected value of 10.",
            extra={"observed_pool_size": pool_size.value if pool_size else None},
        )

    existing_action = db.scalar(
        select(Action)
        .where(
            Action.incident_id == incident.id,
            Action.status.in_(("approved", "simulated_validated")),
        )
        .order_by(Action.created_at.desc(), Action.id.desc())
        .limit(1)
    )
    if existing_action is not None:
        _write_rejection(
            db, incident_id=incident.id, actor=actor, action_code=action_code,
            event_type="approval_rejected",
            detail="A remediation has already been approved or executed for this incident.",
            extra={"existing_action_id": existing_action.id},
        )

    action = Action(
        incident_id=incident.id,
        action=RESTORE_POOL_ACTION,
        approved_by=actor,
        status="approved",
        result=f"Approved by {actor} for this synthetic simulation only.",
    )
    recommendation.approval_status = "approved"
    db.add(action)
    db.flush()
    add_audit_event(
        db,
        incident_id=incident.id,
        event_type="approval_granted",
        actor=actor,
        action=RESTORE_POOL_ACTION,
        details={
            "action_code": RESTORE_POOL_ACTION_CODE,
            "recommendation_id": recommendation.id,
            "action_id": action.id,
            "approval_status": "approved",
        },
    )
    db.commit()
    db.refresh(action)
    return serialize_remediation(action)


def simulate_approved_remediation(
    db: Session,
    *,
    incident_id: int,
    operator_name: str | None,
    action_code: str | None,
    recommendation_id: int | None,
) -> dict:
    db.connection().exec_driver_sql("BEGIN IMMEDIATE")
    actor = _validate_request_identity(operator_name)
    incident, recommendation, reason = active_checkout_recommendation(
        db, incident_id, action_code
    )
    if incident is None:
        _write_rejection(
            db, incident_id=None, actor=actor, action_code=action_code,
            event_type="execution_rejected", detail=reason or "Incident not found.",
            status_code=404, extra={"requested_incident_id": incident_id},
        )
    if actor is None:
        reason = "A clearly identified operator name is required."
    elif reason is None and recommendation_id != recommendation.id:
        reason = "The simulation recommendation ID does not match the active recommendation."
    if reason:
        _write_rejection(
            db, incident_id=incident.id, actor=actor, action_code=action_code,
            event_type="execution_rejected", detail=reason,
            extra={"recommendation_id": recommendation_id},
        )

    action = db.scalar(
        select(Action)
        .where(
            Action.incident_id == incident.id,
            Action.status == "approved",
            Action.action == RESTORE_POOL_ACTION,
        )
        .order_by(Action.created_at.desc(), Action.id.desc())
        .limit(1)
    )
    if (
        recommendation.approval_status != "approved"
        or action is None
        or action.approved_by != actor
    ):
        _write_rejection(
            db, incident_id=incident.id, actor=actor, action_code=action_code,
            event_type="execution_rejected",
            detail="An explicit, matching operator approval is required before simulation.",
            extra={"recommendation_id": recommendation.id},
        )

    database = incident.service
    pool_metric = _latest_metric(db, database.id, "db_pool_size")
    if pool_metric is None or pool_metric.value != 10:
        _write_rejection(
            db, incident_id=incident.id, actor=actor, action_code=action_code,
            event_type="execution_rejected",
            detail="The synthetic pool size is no longer 10; this recommendation is stale.",
            extra={"observed_pool_size": pool_metric.value if pool_metric else None},
        )

    checkout = db.scalar(
        select(Service).where(
            Service.name == "Checkout Service",
            Service.environment == CHECKOUT_DEMO_ENVIRONMENT,
        )
    )
    if checkout is None:
        _write_rejection(
            db, incident_id=incident.id, actor=actor, action_code=action_code,
            event_type="execution_rejected",
            detail="The synthetic checkout service is unavailable.",
        )

    database_metric_names = (
        "db_pool_size",
        "db_pool_utilization_percent",
        "latency_ms",
        "error_rate",
    )
    checkout_metric_names = ("latency_ms", "error_rate")
    before = {}
    for name in database_metric_names:
        metric = _latest_metric(db, database.id, name)
        before[f"database_{name}"] = metric.value if metric else None
    for name in checkout_metric_names:
        metric = _latest_metric(db, checkout.id, name)
        before[f"checkout_{name}"] = metric.value if metric else None

    now = utc_now()
    original_statuses = {
        service.id: service.status
        for service in db.scalars(
            select(Service).where(Service.environment == CHECKOUT_DEMO_ENVIRONMENT)
        ).all()
    }
    recovery_values = {
        (database.id, "db_pool_size"): 50,
        (database.id, "db_pool_utilization_percent"): 45,
        (database.id, "latency_ms"): 110,
        (database.id, "error_rate"): 0.2,
        (checkout.id, "latency_ms"): 140,
        (checkout.id, "error_rate"): 0.3,
    }
    for (service_id, metric_name), value in recovery_values.items():
        db.add(Metric(
            service_id=service_id,
            timestamp=now,
            metric_name=metric_name,
            value=float(value),
        ))
    db.flush()

    after = {}
    after_values = {}
    for (service_id, metric_name), value in recovery_values.items():
        latest = _latest_metric(db, service_id, metric_name)
        after_values[(service_id, metric_name)] = latest.value if latest else None
        prefix = "database" if service_id == database.id else "checkout"
        after[f"{prefix}_{metric_name}"] = latest.value if latest else None

    checks = {
        "pool_size_restored": after_values.get((database.id, "db_pool_size")) == RECOVERY_THRESHOLDS["db_pool_size"],
        "pool_utilization_within_limit": after_values.get((database.id, "db_pool_utilization_percent"), 101)
        <= RECOVERY_THRESHOLDS["db_pool_utilization_percent_max"],
        "database_latency_within_limit": after_values.get((database.id, "latency_ms"), float("inf"))
        <= RECOVERY_THRESHOLDS["database_latency_ms_max"],
        "database_errors_within_limit": after_values.get((database.id, "error_rate"), float("inf"))
        <= RECOVERY_THRESHOLDS["database_error_rate_percent_max"],
        "checkout_latency_within_limit": after_values.get((checkout.id, "latency_ms"), float("inf"))
        <= RECOVERY_THRESHOLDS["checkout_latency_ms_max"],
        "checkout_errors_within_limit": after_values.get((checkout.id, "error_rate"), float("inf"))
        <= RECOVERY_THRESHOLDS["checkout_error_rate_percent_max"],
    }
    passed = all(checks.values())
    simulation = db.get(CheckoutSimulationState, 1)
    if passed:
        for service in db.scalars(
            select(Service).where(Service.environment == CHECKOUT_DEMO_ENVIRONMENT)
        ).all():
            service.status = "Operational"
        incident.status = "resolved"
        incident.resolved_at = now
        simulation.state = "healthy"
        simulation.active_incident_id = None
        simulation.updated_at = now
        action.status = "simulated_validated"
        action.result = (
            "Recovery thresholds passed in the synthetic checkout simulation. "
            "Only local demo configuration and telemetry were updated; no live systems were contacted."
        )
        recommendation.approval_status = "validated"
        event_type = "execution_succeeded"
    else:
        # Fail closed: restore the demo telemetry snapshot and keep the incident unresolved.
        for (service_id, metric_name) in recovery_values:
            prefix = "database" if service_id == database.id else "checkout"
            previous_value = before.get(f"{prefix}_{metric_name}")
            if previous_value is not None:
                db.add(Metric(
                    service_id=service_id,
                    timestamp=now,
                    metric_name=metric_name,
                    value=float(previous_value),
                ))
        for service in db.scalars(
            select(Service).where(Service.environment == CHECKOUT_DEMO_ENVIRONMENT)
        ).all():
            service.status = original_statuses.get(service.id, "Degraded")
        action.status = "rejected"
        action.result = (
            "Synthetic recovery validation failed. The demo pool setting was restored to 10; "
            "the incident remains unresolved."
        )
        recommendation.approval_status = "execution_failed"
        event_type = "execution_failed"

    db.add(LogEvent(
        service_id=database.id,
        timestamp=now,
        level="info" if passed else "error",
        message=(
            "[SYNTHETIC] Simulation restored DB_POOL_SIZE from 10 to 50."
            if passed
            else "[SYNTHETIC] Recovery thresholds failed; demo DB_POOL_SIZE was restored to 10."
        ),
    ))
    action.updated_at = now
    details = {
        "action_code": RESTORE_POOL_ACTION_CODE,
        "recommendation_id": recommendation.id,
        "action_id": action.id,
        "validation_passed": passed,
        "before_metrics": before,
        "after_metrics": after,
        "checks": checks,
        "thresholds": RECOVERY_THRESHOLDS,
        "execution_scope": "synthetic_checkout_demo_only",
    }
    add_audit_event(
        db,
        incident_id=incident.id,
        event_type=event_type,
        actor=actor,
        action=RESTORE_POOL_ACTION,
        details=details,
    )
    db.commit()
    db.refresh(action)
    result = serialize_remediation(action)
    result.update({
        "validation_passed": passed,
        "before_metrics": before,
        "after_metrics": after,
        "thresholds": {**RECOVERY_THRESHOLDS, **checks},
    })
    return result


def reject_simulated_remediation(
    db: Session,
    *,
    incident_id: int,
    operator_name: str | None,
    action_code: str | None,
    recommendation_id: int | None,
) -> dict:
    db.connection().exec_driver_sql("BEGIN IMMEDIATE")
    actor = _validate_request_identity(operator_name)
    incident, recommendation, reason = active_checkout_recommendation(
        db, incident_id, action_code
    )
    if incident is None:
        _write_rejection(
            db, incident_id=None, actor=actor, action_code=action_code,
            event_type="rejection_rejected", detail=reason or "Incident not found.",
            status_code=404, extra={"requested_incident_id": incident_id},
        )
    if actor is None:
        reason = "A clearly identified operator name is required."
    elif reason is None and recommendation_id != recommendation.id:
        reason = "The rejected recommendation ID does not match the active recommendation."
    elif reason is None and recommendation.approval_status != "pending":
        reason = f"This recommendation is already {recommendation.approval_status}."
    if reason:
        _write_rejection(
            db, incident_id=incident.id, actor=actor, action_code=action_code,
            event_type="rejection_rejected", detail=reason,
            extra={"recommendation_id": recommendation_id},
        )

    recommendation.approval_status = "rejected"
    action = Action(
        incident_id=incident.id,
        action=RESTORE_POOL_ACTION,
        approved_by=actor,
        status="rejected",
        result=f"Rejected by {actor}. No simulated configuration was changed.",
    )
    db.add(action)
    db.flush()
    add_audit_event(
        db,
        incident_id=incident.id,
        event_type="action_rejected",
        actor=actor,
        action=RESTORE_POOL_ACTION,
        details={
            "action_id": action.id,
            "action_code": RESTORE_POOL_ACTION_CODE,
            "recommendation_id": recommendation.id,
            "approval_status": "rejected",
        },
    )
    db.commit()
    db.refresh(action)
    return serialize_remediation(action)