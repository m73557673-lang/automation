import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import sessionmaker

from app.database import create_sqlite_engine, get_db, initialize_database
from app.main import create_app
from app.models import (
    Action,
    CheckoutSimulationState,
    Deployment,
    Incident,
    LogEvent,
    Metric,
    Recommendation,
    RemediationAuditEvent,
    Service,
)


@pytest.fixture
def test_app(tmp_path):
    db_engine = create_sqlite_engine(f"sqlite:///{tmp_path / 'api-tests.sqlite'}")
    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    application = create_app(db_engine)

    def override_get_db():
        with factory() as db:
            yield db

    application.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(application) as client:
            yield client, factory
    finally:
        db_engine.dispose()


def test_health_and_paginated_collections_are_available_at_both_prefixes(test_app):
    client, _ = test_app
    for path in ("/health", "/api/health"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "connected"}

    services = client.get("/services?skip=1&limit=2")
    assert services.status_code == 200
    assert services.json()["total"] == 8
    assert len(services.json()["items"]) == 2
    assert services.json()["skip"] == 1

    incidents = client.get("/api/incidents?skip=1&limit=1")
    assert incidents.status_code == 200
    assert incidents.json()["total"] == 3
    assert len(incidents.json()["items"]) == 1
    assert incidents.json()["items"][0]["service_id"] > 0


def test_incident_create_validation_and_related_records(test_app):
    client, _ = test_app
    service_id = client.get("/services?limit=1").json()["items"][0]["id"]

    invalid = client.post("/incidents", json={
        "title": " ",
        "severity": "urgent",
        "service_id": service_id,
    })
    assert invalid.status_code == 422
    assert "errors" in invalid.json()

    created = client.post("/api/incidents", json={
        "title": "Scenario created in API test",
        "severity": "high",
        "service_id": service_id,
        "summary": "A synthetic test symptom with enough context.",
    })
    assert created.status_code == 201
    incident = created.json()
    incident_id = incident["id"]
    assert incident["service_id"] == service_id
    assert incident["summary"] == "A synthetic test symptom with enough context."
    assert incident["is_synthetic"] is True

    detail = client.get(f"/incidents/{incident_id}")
    assert detail.status_code == 200
    assert detail.json()["title"] == incident["title"]
    assert client.get(f"/incidents/{incident_id}/evidence").json()["total"] == 1
    recommendation = client.get(f"/incidents/{incident_id}/recommendation")
    assert recommendation.status_code == 200
    assert "No infrastructure action" in recommendation.json()["action"]
    assert client.get(f"/incidents/{incident_id}/metrics").status_code == 200
    assert client.get(f"/incidents/{incident_id}/postmortem").status_code == 404

    missing_service = client.post("/incidents", json={
        "title": "Unknown service scenario",
        "severity": "low",
        "service_id": 999999,
    })
    assert missing_service.status_code == 404


def test_unapproved_and_non_allowlisted_remediation_requests_are_rejected_and_audited(test_app):
    client, factory = test_app
    started = client.post("/api/simulation/start").json()
    incident_id = started["active_incident_id"]
    recommendation = client.get(f"/api/incidents/{incident_id}/recommendation").json()
    valid_payload = {
        "operator_name": "Test operator",
        "recommendation_id": recommendation["id"],
        "action_code": "restore_db_pool_size_50",
    }

    unapproved = client.post(f"/api/incidents/{incident_id}/simulate-fix", json=valid_payload)
    assert unapproved.status_code == 409
    assert "approval" in unapproved.json()["detail"].lower()

    disallowed = client.post(
        f"/api/incidents/{incident_id}/approve",
        json={**valid_payload, "action_code": "delete_database"},
    )
    assert disallowed.status_code == 409
    assert "allowlist" in disallowed.json()["detail"].lower()

    with factory() as db:
        database = db.scalar(select(Service).where(Service.name == "Database Service"))
        assert database is not None
        pool = db.scalar(
            select(Metric.value)
            .where(Metric.service_id == database.id, Metric.metric_name == "db_pool_size")
            .order_by(Metric.timestamp.desc(), Metric.id.desc())
        )
        assert pool == 10
        incident = db.get(Incident, incident_id)
        assert incident is not None and incident.status == "investigating"
        event_types = set(db.scalars(select(RemediationAuditEvent.event_type)).all())
        assert "execution_rejected" in event_types
        assert "approval_rejected" in event_types


def test_approved_simulation_compares_metrics_and_resolves_only_after_thresholds_pass(test_app):
    client, factory = test_app
    started = client.post("/api/simulation/start").json()
    incident_id = started["active_incident_id"]
    recommendation = client.get(f"/api/incidents/{incident_id}/recommendation").json()
    assert recommendation["incident_id"] == incident_id
    assert recommendation["action"] == "Restore the simulated DB_POOL_SIZE from 10 to 50."
    assert recommendation["risk"] == "medium"
    assert recommendation["reason"]
    assert recommendation["supporting_evidence"]
    assert recommendation["expected_impact"]
    assert recommendation["preconditions"]
    assert recommendation["rollback_plan"]
    assert recommendation["approval_status"] == "pending"

    payload = {
        "operator_name": "Test operator",
        "recommendation_id": recommendation["id"],
        "action_code": "restore_db_pool_size_50",
    }
    approved = client.post(f"/api/incidents/{incident_id}/approve", json=payload)
    assert approved.status_code == 200
    assert approved.json()["state"] == "approved"
    assert approved.json()["incident_id"] == incident_id
    assert client.get(f"/api/incidents/{incident_id}/recommendation").json()["approval_status"] == "approved"
    assert client.get(f"/api/incidents/{incident_id}").json()["status"] == "investigating"

    executed = client.post(f"/api/incidents/{incident_id}/simulate-fix", json=payload)
    assert executed.status_code == 200
    result = executed.json()
    assert result["state"] == "validated"
    assert result["validation_passed"] is True
    assert result["before_metrics"]["database_db_pool_size"] == 10
    assert result["after_metrics"]["database_db_pool_size"] == 50
    assert result["before_metrics"] != result["after_metrics"]
    assert all(result["thresholds"][name] is True for name in (
        "pool_size_restored",
        "pool_utilization_within_limit",
        "database_latency_within_limit",
        "database_errors_within_limit",
        "checkout_latency_within_limit",
        "checkout_errors_within_limit",
    ))
    assert client.get(f"/api/incidents/{incident_id}").json()["status"] == "resolved"
    assert client.get(f"/api/incidents/{incident_id}/recommendation").json()["approval_status"] == "validated"

    duplicate = client.post(f"/api/incidents/{incident_id}/simulate-fix", json=payload)
    assert duplicate.status_code == 409
    metrics = client.get("/api/simulation/metrics").json()
    assert metrics["state"] == "healthy"
    assert metrics["active_incident_id"] is None
    database_metrics = {item["name"]: item for item in metrics["services"]}
    assert database_metrics["Database Service"]["db_pool_size"] == 50
    assert all(item["status"] == "Operational" for item in metrics["services"])

    audit = client.get(f"/api/incidents/{incident_id}/audit-log")
    assert audit.status_code == 200
    event_types = {item["event_type"] for item in audit.json()["items"]}
    assert {"recommendation_created", "approval_granted", "execution_succeeded", "execution_rejected"} <= event_types
    success_event = next(item for item in audit.json()["items"] if item["event_type"] == "execution_succeeded")
    assert success_event["actor"] == "Test operator"
    assert success_event["details"]["before_metrics"]["database_db_pool_size"] == 10
    assert success_event["details"]["after_metrics"]["database_db_pool_size"] == 50

    with factory() as db:
        incident = db.get(Incident, incident_id)
        recommendation_row = db.scalar(
            select(Recommendation).where(Recommendation.incident_id == incident_id)
        )
        simulation = db.get(CheckoutSimulationState, 1)
        action = db.scalar(select(Action).where(Action.incident_id == incident_id))
        assert incident is not None and incident.status == "resolved"
        assert recommendation_row is not None and recommendation_row.approval_status == "validated"
        assert simulation is not None and simulation.state == "healthy"
        assert action is not None and action.status == "simulated_validated"


def test_safe_reset_cancels_approval_and_invalid_state_cannot_execute(test_app):
    client, factory = test_app
    started = client.post("/api/simulation/start").json()
    incident_id = started["active_incident_id"]
    recommendation = client.get(f"/api/incidents/{incident_id}/recommendation").json()
    payload = {
        "operator_name": "Reset operator",
        "recommendation_id": recommendation["id"],
        "action_code": "restore_db_pool_size_50",
    }
    assert client.post(f"/api/incidents/{incident_id}/approve", json=payload).status_code == 200

    reset = client.post("/api/simulation/reset")
    assert reset.status_code == 200
    assert reset.json()["state"] == "healthy"
    assert reset.json()["active_incident_id"] is None
    assert reset.json()["services"][3]["db_pool_size"] == 50

    stale_execution = client.post(f"/api/incidents/{incident_id}/simulate-fix", json=payload)
    assert stale_execution.status_code == 409
    assert client.get(f"/api/incidents/{incident_id}").json()["status"] == "investigating"
    assert client.get(f"/api/incidents/{incident_id}/recommendation").json()["approval_status"] == "cancelled"
    audit = client.get(f"/api/incidents/{incident_id}/audit-log").json()["items"]
    assert any(item["event_type"] == "simulation_reset" for item in audit)
    assert any(item["event_type"] == "execution_rejected" for item in audit)

    with factory() as db:
        action = db.scalar(select(Action).where(Action.incident_id == incident_id))
        assert action is not None and action.status == "rejected"
        incident = db.get(Incident, incident_id)
        assert incident is not None and incident.resolved_at is None


def test_failed_recovery_threshold_rolls_back_and_keeps_incident_open(test_app, monkeypatch):
    from app.services.remediation import RECOVERY_THRESHOLDS

    monkeypatch.setitem(RECOVERY_THRESHOLDS, "checkout_latency_ms_max", 100)
    client, factory = test_app
    started = client.post("/api/simulation/start").json()
    incident_id = started["active_incident_id"]
    recommendation = client.get(f"/api/incidents/{incident_id}/recommendation").json()
    payload = {
        "operator_name": "Threshold test operator",
        "recommendation_id": recommendation["id"],
        "action_code": "restore_db_pool_size_50",
    }
    assert client.post(f"/api/incidents/{incident_id}/approve", json=payload).status_code == 200

    failed = client.post(f"/api/incidents/{incident_id}/simulate-fix", json=payload)
    assert failed.status_code == 200
    result = failed.json()
    assert result["validation_passed"] is False
    assert result["state"] == "rejected"
    assert result["after_metrics"]["checkout_latency_ms"] == 140
    assert result["thresholds"]["checkout_latency_within_limit"] is False
    assert client.get(f"/api/incidents/{incident_id}").json()["status"] == "investigating"
    assert client.get(f"/api/incidents/{incident_id}/recommendation").json()["approval_status"] == "execution_failed"

    restored = client.get("/api/simulation/metrics").json()
    assert restored["state"] == "incident"
    assert restored["active_incident_id"] == incident_id
    by_name = {service["name"]: service for service in restored["services"]}
    assert by_name["Database Service"]["db_pool_size"] == 10
    assert by_name["Database Service"]["latency_ms"] == 1800
    assert by_name["Checkout Service"]["latency_ms"] == 2100
    assert all(service["status"] == "Degraded" for service in restored["services"])
    audit = client.get(f"/api/incidents/{incident_id}/audit-log").json()["items"]
    failed_event = next(item for item in audit if item["event_type"] == "execution_failed")
    assert failed_event["details"]["validation_passed"] is False

    with factory() as db:
        incident = db.get(Incident, incident_id)
        action = db.scalar(select(Action).where(Action.incident_id == incident_id))
        simulation = db.get(CheckoutSimulationState, 1)
        assert incident is not None and incident.resolved_at is None
        assert action is not None and action.status == "rejected"
        assert simulation is not None and simulation.state == "incident"


def test_legacy_sqlite_data_is_archived_and_migrated_without_loss(tmp_path):
    db_path = tmp_path / "legacy.sqlite"
    connection = sqlite3.connect(db_path)
    now = datetime.now(timezone.utc).isoformat()
    connection.executescript(
        """
        CREATE TABLE services (
            id INTEGER PRIMARY KEY, name TEXT, owner TEXT, tier TEXT, status TEXT,
            latency_ms REAL, error_rate REAL, request_rate REAL,
            latency_history TEXT, error_history TEXT, is_synthetic BOOLEAN
        );
        CREATE TABLE incidents (
            id INTEGER PRIMARY KEY, title TEXT, severity TEXT, status TEXT,
            service TEXT, summary TEXT, source TEXT, is_synthetic BOOLEAN, created_at TEXT
        );
        CREATE TABLE evidence (
            id INTEGER PRIMARY KEY, incident_id INTEGER, kind TEXT, source TEXT,
            message TEXT, observed_at TEXT, confidence REAL
        );
        CREATE TABLE runbooks (
            id INTEGER PRIMARY KEY, title TEXT, service TEXT, content TEXT, tags TEXT
        );
        CREATE TABLE remediations (
            id INTEGER PRIMARY KEY, incident_id INTEGER, action TEXT, state TEXT,
            created_at TEXT, approved_at TEXT, validation_passed BOOLEAN, result TEXT
        );
        CREATE TABLE postmortems (
            id INTEGER PRIMARY KEY, incident_id INTEGER, title TEXT, summary TEXT,
            root_cause TEXT, impact TEXT, prevention TEXT, created_at TEXT, is_synthetic BOOLEAN
        );
        """
    )
    connection.execute(
        "INSERT INTO services VALUES (7, 'legacy-api', 'Platform', 'Tier 1', 'Degraded', 250, 1.5, 80, '[100,250]', '[0.2,1.5]', 1)"
    )
    connection.execute(
        "INSERT INTO incidents VALUES (11, 'Legacy scenario', 'high', 'investigating', 'legacy-api', 'Preserve this summary', 'synthetic scenario', 1, ?)",
        (now,),
    )
    connection.execute(
        "INSERT INTO evidence VALUES (13, 11, 'log', 'legacy api', 'Preserve this signal', ?, 0.88)",
        (now,),
    )
    connection.execute(
        "INSERT INTO runbooks VALUES (17, 'Legacy runbook', 'legacy-api', 'Keep this procedure', 'legacy,test')"
    )
    connection.execute(
        "INSERT INTO remediations VALUES (19, 11, 'Review only', 'validated', ?, ?, 1, 'Imported simulation')",
        (now, now),
    )
    connection.execute(
        "INSERT INTO postmortems VALUES (23, 11, 'Legacy review', 'Keep report', 'Recorded cause', 'No real impact', 'Review signals', ?, 1)",
        (now,),
    )
    connection.commit()
    connection.close()

    db_engine = create_sqlite_engine(f"sqlite:///{db_path}")
    try:
        initialize_database(db_engine)
        factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
        with factory() as db:
            service = db.get(Service, 7)
            incident = db.get(Incident, 11)
            assert service is not None and service.name == "legacy-api"
            assert incident is not None and incident.title == "Legacy scenario"
            assert db.scalar(select(func.count()).select_from(Metric)) >= 4
            assert db.scalar(select(Action.status).where(Action.id == 19)) == "simulated_validated"

        with db_engine.connect() as connection:
            names = set(__import__("sqlalchemy").inspect(connection).get_table_names())
            assert "legacy_services" in names
            assert "legacy_incidents" in names
            assert "services" in names and "incidents" in names
    finally:
        db_engine.dispose()


def test_existing_normalized_sqlite_schema_gets_additive_remediation_migration(tmp_path):
    db_path = tmp_path / "normalized-before-remediation.sqlite"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE schema_migrations (version VARCHAR(120) PRIMARY KEY, applied_at DATETIME NOT NULL);
        CREATE TABLE recommendations (
            id INTEGER PRIMARY KEY, incident_id INTEGER NOT NULL, action TEXT NOT NULL,
            risk VARCHAR(16) NOT NULL, confidence FLOAT NOT NULL, created_at DATETIME NOT NULL
        );
        CREATE TABLE checkout_simulation_state (
            id INTEGER PRIMARY KEY, state VARCHAR(16) NOT NULL, run_number INTEGER NOT NULL,
            updated_at DATETIME NOT NULL
        );
        INSERT INTO recommendations VALUES (77, 15, 'Preserved old advice', 'low', 0.5, '2026-10-02T00:00:00+00:00');
        INSERT INTO checkout_simulation_state VALUES (1, 'healthy', 3, '2026-10-02T00:00:00+00:00');
        """
    )
    connection.commit()
    connection.close()

    db_engine = create_sqlite_engine(f"sqlite:///{db_path}")
    try:
        initialize_database(db_engine)
        with db_engine.connect() as upgraded:
            recommendation_columns = {column["name"] for column in inspect(upgraded).get_columns("recommendations")}
            simulation_columns = {
                column["name"] for column in inspect(upgraded).get_columns("checkout_simulation_state")
            }
            preserved = upgraded.exec_driver_sql(
                "SELECT action, approval_status FROM recommendations WHERE id = 77"
            ).one()
            simulation = upgraded.exec_driver_sql(
                "SELECT state, run_number, active_incident_id FROM checkout_simulation_state WHERE id = 1"
            ).one()
        assert {
            "action_code",
            "reason",
            "supporting_evidence",
            "expected_impact",
            "preconditions",
            "rollback_plan",
            "approval_status",
        } <= recommendation_columns
        assert "active_incident_id" in simulation_columns
        assert preserved == ("Preserved old advice", "pending")
        assert simulation == ("healthy", 3, None)
    finally:
        db_engine.dispose()


def test_checkout_simulation_is_synthetic_reproducible_and_resettable(test_app):
    client, factory = test_app

    baseline = client.get("/api/simulation/metrics")
    assert baseline.status_code == 200
    assert baseline.json()["state"] == "healthy"
    assert baseline.json()["is_synthetic"] is True
    assert len(baseline.json()["services"]) == 4
    assert all(service["is_synthetic"] for service in baseline.json()["services"])
    assert client.get("/api/simulation/health").json()["overall_status"] == "healthy"
    baseline_by_name = {service["name"]: service for service in baseline.json()["services"]}
    assert baseline_by_name["Checkout Service"]["latency_ms"] < 150
    assert baseline_by_name["Checkout Service"]["error_rate_percent"] < 1
    assert baseline_by_name["Database Service"]["db_pool_size"] == 50
    assert baseline_by_name["Database Service"]["db_pool_utilization_percent"] < 50
    assert all(
        service["history"][-1]["timestamp"]
        and max(point["latency_ms"] for point in service["history"])
        - min(point["latency_ms"] for point in service["history"]) < 5
        for service in baseline.json()["services"]
    )

    first_run = client.post("/api/simulation/start")
    assert first_run.status_code == 200
    first = first_run.json()
    assert first["state"] == "incident"
    assert first["run_number"] == 1
    by_name = {service["name"]: service for service in first["services"]}
    assert by_name["Database Service"]["db_pool_size"] == 10
    assert by_name["Database Service"]["db_pool_utilization_percent"] == 100
    assert by_name["Checkout Service"]["latency_ms"] == 2100
    assert by_name["Checkout Service"]["error_rate_percent"] == 16
    assert by_name["API Gateway"]["request_volume_rps"] > 2 * 240

    health = client.get("/api/simulation/health").json()
    assert health["overall_status"] == "degraded"
    assert all(service["status"] == "Degraded" for service in health["services"])

    events = client.get("/api/simulation/events").json()
    assert events["is_synthetic"] is True
    assert any(event["kind"] == "deployment" for event in events["items"])
    assert any("DB_POOL_SIZE changed from 50 to 10" in event["detail"] for event in events["items"])
    assert any("timeout" in event["detail"].lower() for event in events["items"])
    assert all(event["timestamp"] and event["is_synthetic"] for event in events["items"])
    assert len(events["items"]) == 8
    event_times = [datetime.fromisoformat(event["timestamp"]) for event in events["items"]]
    assert event_times == sorted(event_times, reverse=True)

    second = client.post("/api/simulation/start").json()
    assert second["run_number"] == 2
    for first_service, second_service in zip(first["services"], second["services"]):
        assert first_service["name"] == second_service["name"]
        assert [
            {key: value for key, value in point.items() if key != "timestamp"}
            for point in first_service["history"]
        ] == [
            {key: value for key, value in point.items() if key != "timestamp"}
            for point in second_service["history"]
        ]
    second_events = client.get("/api/simulation/events").json()["items"]
    assert [
        (event["kind"], event["level"], event["service"], event["title"], event["detail"])
        for event in events["items"]
    ] == [
        (event["kind"], event["level"], event["service"], event["title"], event["detail"])
        for event in second_events
    ]

    with factory() as db:
        checkout_service = db.scalar(select(Service).where(Service.name == "Checkout Service"))
        assert checkout_service is not None
        stored_metrics = db.scalar(
            select(func.count()).select_from(Metric).where(Metric.service_id == checkout_service.id)
        )
        assert stored_metrics == 21
        database_service = db.scalar(select(Service).where(Service.name == "Database Service"))
        assert database_service is not None
        assert db.scalar(
            select(func.count()).select_from(Deployment).where(Deployment.service_id == database_service.id)
        ) == 1
        assert db.scalar(
            select(func.count()).select_from(LogEvent).where(LogEvent.service_id == database_service.id)
        ) == 2

    reset = client.post("/api/simulation/reset")
    assert reset.status_code == 200
    assert reset.json()["state"] == "healthy"
    assert reset.json()["run_number"] == 2
    assert client.get("/api/simulation/health").json()["overall_status"] == "healthy"
    restored = {service["name"]: service for service in reset.json()["services"]}
    assert restored["Database Service"]["db_pool_size"] == 50
    assert restored["Database Service"]["db_pool_utilization_percent"] < 50
    assert restored["Checkout Service"]["error_rate_percent"] < 1
    assert client.get("/api/simulation/events").json()["is_synthetic"] is True