import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.database import create_sqlite_engine, get_db
from app.main import create_app
from app.models import AIInvestigation, Action, Incident, Metric
from app.services.ai_investigation import configured_ai_provider


class FakeProvider:
    def __init__(self, response):
        self.response = response

    def complete_json(self, prompt: str) -> str:
        if callable(self.response):
            return self.response(prompt)
        return self.response


def _valid_response(prompt: str) -> str:
    request = json.loads(prompt)
    evidence = request["context"]["evidence"]
    refs = [item["id"] for item in evidence]
    deployments = [item["id"] for item in evidence if item["kind"] == "deployment"]
    candidates = request["allowed_hypotheses"]
    first_candidate = candidates[0]
    candidate_refs = first_candidate["evidence_ids"] or refs[:1]
    patterns = [
        {"code": code, "evidence_ids": pattern_refs[:1]}
        for code, pattern_refs in request["detected_log_patterns"].items()
        if pattern_refs
    ]
    return json.dumps({
        "triage": {
            "severity": "high",
            "scope": "dependency_chain",
            "evidence_ids": refs[:1],
        },
        "log_analysis": {"patterns": patterns},
        "change_analysis": {
            "relationship": "temporal_association" if deployments else "unknown",
            "evidence_ids": deployments[:1],
        },
        "root_cause": {
            "hypotheses": [{
                "key": first_candidate["key"],
                "evidence_ids": candidate_refs[:1],
            }],
        },
        "remediation": {
            "plan_code": "inspect_pool_configuration",
            "risk": "high",
            "evidence_ids": refs[:1],
        },
        "validation": {"assessment": "awaiting_action", "evidence_ids": []},
        "postmortem": {
            "summary": "Review-only draft based on stored checkout scenario evidence.",
            "impact": "Synthetic training scenario; no production users were affected.",
            "timeline": "Stored records show a sequence of simulated service signals.",
            "prevention": "Compare aligned metrics and request human review before action.",
            "evidence_ids": refs[:1],
        },
    })


@pytest.fixture
def client_factory(tmp_path):
    engines = []

    def create(provider=None):
        db_engine = create_sqlite_engine(f"sqlite:///{tmp_path / f'ai-{len(engines)}.sqlite'}")
        engines.append(db_engine)
        factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
        application = create_app(db_engine, ai_provider=provider)

        def override_get_db():
            with factory() as db:
                yield db

        application.dependency_overrides[get_db] = override_get_db
        return TestClient(application), factory

    yield create
    for db_engine in engines:
        db_engine.dispose()


def test_checkout_investigation_uses_deterministic_evidence_and_persists(client_factory):
    client, factory = client_factory()
    with client:
        assert client.post("/api/simulation/start").status_code == 200
        response = client.post("/api/simulation/ai-investigation")
        assert response.status_code == 200
        report = response.json()
        assert report["provider_status"] == "not_configured"
        assert report["is_synthetic"] is True
        assert len(report["agents"]["root_cause"]["hypotheses"]) >= 2
        statements = [fact["statement"] for fact in report["observed_facts"]]
        assert any("DB_POOL_SIZE changed from 50 to 10" in item for item in statements)
        assert any("Request rate rose" in item for item in statements)
        assert any("timeout" in item.lower() for item in statements)
        assert any("historical incident" in item.lower() for item in statements)
        assert report["support_score_method"]
        assert "not a calibrated probability" in report["support_score_method"]

        saved = client.get("/api/simulation/ai-investigation")
        assert saved.status_code == 200
        assert saved.json()["id"] == report["id"]
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(AIInvestigation)) == 1
            assert db.scalar(select(func.count()).select_from(Action)) == 0
    client.close()


def test_missing_provider_configuration_is_reported_without_a_secret(monkeypatch):
    for name in ("INCIDENT_AI_API_URL", "INCIDENT_AI_API_KEY", "INCIDENT_AI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    assert configured_ai_provider({}) == (None, "not_configured")
    assert configured_ai_provider({
        "INCIDENT_AI_API_URL": "https://provider.invalid/v1/chat/completions",
        "INCIDENT_AI_API_KEY": "test-only",
    }) == (None, "missing_credentials")


def test_malformed_model_output_uses_deterministic_fallback(client_factory):
    client, _ = client_factory(FakeProvider("this is not JSON"))
    with client:
        client.post("/api/simulation/start")
        response = client.post("/api/simulation/ai-investigation")
        assert response.status_code == 200
        report = response.json()
        assert report["provider_status"] == "invalid_response"
        assert report["agents"]["root_cause"]["source"] == "deterministic evidence synthesis"
        assert len(report["agents"]["root_cause"]["hypotheses"]) >= 2
        assert "deterministic results" in report["provider_message"]
    client.close()


def test_unsupported_hypothesis_citations_are_rejected(client_factory):
    def unsupported(prompt):
        data = json.loads(_valid_response(prompt))
        data["root_cause"]["hypotheses"] = [{
            "key": data["root_cause"]["hypotheses"][0]["key"],
            "evidence_ids": ["metric:999999"],
        }]
        return json.dumps(data)

    client, _ = client_factory(FakeProvider(unsupported))
    with client:
        client.post("/api/simulation/start")
        report = client.post("/api/simulation/ai-investigation").json()
        assert report["provider_status"] == "invalid_response"
        hypotheses = report["agents"]["root_cause"]["hypotheses"]
        assert all(not item.get("ai_selected", False) for item in hypotheses)
        assert all(ref != "metric:999999" for item in hypotheses for ref in item["evidence_ids"])
    client.close()


def test_hypothesis_outside_server_defined_candidates_is_rejected(client_factory):
    def unsupported(prompt):
        data = json.loads(_valid_response(prompt))
        data["root_cause"]["hypotheses"][0]["key"] = "credential_theft"
        return json.dumps(data)

    client, _ = client_factory(FakeProvider(unsupported))
    with client:
        client.post("/api/simulation/start")
        report = client.post("/api/simulation/ai-investigation").json()
        assert report["provider_status"] == "invalid_response"
        assert len(report["agents"]["root_cause"]["hypotheses"]) >= 2
        assert all(item["key"] != "credential_theft" for item in report["agents"]["root_cause"]["hypotheses"])
    client.close()


def test_provider_failure_falls_back_without_creating_an_action(client_factory):
    class FailedProvider:
        def complete_json(self, _prompt):
            raise RuntimeError("provider unavailable")

    client, factory = client_factory(FailedProvider())
    with client:
        client.post("/api/simulation/start")
        response = client.post("/api/simulation/ai-investigation")
        assert response.status_code == 200
        assert response.json()["provider_status"] == "provider_error"
        assert response.json()["agents"]["remediation"]["advisory_only"] is True
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(Action)) == 0
    client.close()


def test_structured_agent_output_is_used_but_action_stays_advisory(client_factory):
    client, factory = client_factory(FakeProvider(_valid_response))
    with client:
        client.post("/api/simulation/start")
        response = client.post("/api/simulation/ai-investigation")
        assert response.status_code == 200
        report = response.json()
        assert report["provider_status"] == "available"
        assert report["agents"]["triage"]["source"] == "AI-assisted"
        assert report["agents"]["remediation"]["advisory_only"] is True
        assert report["agents"]["validation"]["assessment"] == "awaiting_action"
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(Action)) == 0
    client.close()


def test_validation_compares_only_recorded_post_action_metrics(client_factory):
    client, factory = client_factory()
    with client:
        incident = client.get("/api/incidents?limit=1").json()["items"][0]
        incident_id = incident["id"]
        approval = client.post(f"/api/incidents/{incident_id}/remediation/approve")
        assert approval.status_code == 200

        with factory() as db:
            action = db.scalar(
                select(Action).where(Action.incident_id == incident_id).order_by(Action.created_at.desc())
            )
            incident_row = db.get(Incident, incident_id)
            prior = db.scalar(
                select(Metric)
                .where(Metric.service_id == incident_row.service_id, Metric.metric_name == "error_rate")
                .order_by(Metric.timestamp.desc())
            )
            assert action and prior
            db.add(Metric(
                service_id=incident_row.service_id,
                metric_name="error_rate",
                value=max(0, prior.value / 2),
                timestamp=action.created_at + timedelta(seconds=1),
            ))
            db.commit()

        report = client.post(f"/api/incidents/{incident_id}/ai-investigation").json()
        validation = report["agents"]["validation"]
        assert validation["assessment"] == "metrics_improved"
        assert validation["observations"][0]["metric"] == "error_rate"
        assert len(validation["evidence_ids"]) == 2
        assert "synthetic" in validation["detail"]