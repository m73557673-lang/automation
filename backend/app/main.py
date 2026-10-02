import logging
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine, get_db
from .models import Evidence, Incident, Postmortem, Remediation, Runbook, Service
from .schemas import (
    IncidentCreate, IncidentOut, EvidenceOut, ServiceOut, RunbookOut,
    RemediationOut, PostmortemOut,
)
from .services.incident_service import (
    create_incident, get_dashboard, get_investigation, seed_database,
    serialize_runbook, serialize_service,
)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        import json
        return json.dumps({
            "time": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        })


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
logger = logging.getLogger("incident_commander")


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_database(db)
    logger.info("database initialized")
    yield


app = FastAPI(
    title="Autonomous AI-Powered Incident Commander",
    description="Local incident-response prototype with simulated evidence and approval-gated remediation.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def unexpected_error_handler(_, exc: Exception):
    logger.error("unhandled application error", exc_info=(type(exc), exc, exc.__traceback__))
    return JSONResponse(status_code=500, content={"detail": "An unexpected error occurred. Check the server log for details."})


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)):
    return get_dashboard(db)


@app.get("/api/incidents", response_model=list[IncidentOut])
def incidents(db: Session = Depends(get_db)):
    return list(db.scalars(select(Incident).order_by(Incident.created_at.desc())).all())


@app.post("/api/incidents", response_model=IncidentOut, status_code=201)
def add_incident(payload: IncidentCreate, db: Session = Depends(get_db)):
    return create_incident(db, payload)


@app.get("/api/incidents/{incident_id}/investigation")
def investigation(incident_id: int, db: Session = Depends(get_db)):
    result = get_investigation(db, incident_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return result


@app.get("/api/services", response_model=list[ServiceOut])
def services(db: Session = Depends(get_db)):
    return [serialize_service(service) for service in db.scalars(select(Service).order_by(Service.name)).all()]


@app.get("/api/knowledge", response_model=list[RunbookOut])
def knowledge(q: str = Query(default="", max_length=120), db: Session = Depends(get_db)):
    query = f"%{q.strip()}%"
    records = list(db.scalars(
        select(Runbook).where(
            Runbook.title.ilike(query) | Runbook.service.ilike(query) |
            Runbook.content.ilike(query) | Runbook.tags.ilike(query)
        ).order_by(Runbook.title)
    ).all()) if q.strip() else list(db.scalars(select(Runbook).order_by(Runbook.title)).all())
    return [serialize_runbook(record) for record in records]


@app.post("/api/incidents/{incident_id}/remediation/approve", response_model=RemediationOut)
def approve_remediation(incident_id: int, db: Session = Depends(get_db)):
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    existing = db.scalar(
        select(Remediation).where(Remediation.incident_id == incident_id).order_by(Remediation.id.desc())
    )
    if existing and existing.state in ("approved", "validated"):
        return existing
    if existing and existing.state == "rejected":
        raise HTTPException(status_code=409, detail="This proposal was rejected. Create a new incident to start another simulation.")
    remediation = Remediation(
        incident_id=incident_id,
        action=f"Simulation only: roll back the latest {incident.service} change, then compare latency and error-rate samples.",
        state="approved",
        approved_at=datetime.now(timezone.utc),
        result="Approved by operator. No production systems or infrastructure were changed.",
    )
    db.add(remediation)
    incident.status = "investigating"
    db.commit()
    db.refresh(remediation)
    logger.info("simulation remediation approved incident_id=%s", incident_id)
    return remediation


@app.post("/api/incidents/{incident_id}/remediation/reject", response_model=RemediationOut)
def reject_remediation(incident_id: int, db: Session = Depends(get_db)):
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    remediation = Remediation(
        incident_id=incident_id,
        action=f"Simulation only: rollback candidate for {incident.service}.",
        state="rejected",
        result="Rejected by operator. No changes were made.",
    )
    db.add(remediation)
    db.commit()
    db.refresh(remediation)
    return remediation


@app.post("/api/remediations/{remediation_id}/validate", response_model=RemediationOut)
def validate_recovery(remediation_id: int, db: Session = Depends(get_db)):
    remediation = db.get(Remediation, remediation_id)
    if remediation is None:
        raise HTTPException(status_code=404, detail="Remediation proposal not found.")
    if remediation.state != "approved":
        raise HTTPException(status_code=409, detail="Only an approved simulation can be validated.")
    remediation.validation_passed = True
    remediation.state = "validated"
    remediation.result = "Simulated recovery check passed: sample latency and error rate returned to the scenario baseline."
    incident = db.get(Incident, remediation.incident_id)
    if incident:
        incident.status = "resolved"
    service = db.scalar(select(Service).where(Service.name == incident.service)) if incident else None
    if service:
        service.status = "Operational"
        service.latency_ms = 176
        service.error_rate = 0.2
        latency_history = json.loads(service.latency_history)
        error_history = json.loads(service.error_history)
        if latency_history:
            latency_history[-1] = 176
        if error_history:
            error_history[-1] = 0.2
        service.latency_history = json.dumps(latency_history)
        service.error_history = json.dumps(error_history)
    db.commit()
    db.refresh(remediation)
    logger.info("simulated recovery validated remediation_id=%s", remediation_id)
    return remediation


@app.get("/api/postmortems", response_model=list[PostmortemOut])
def postmortems(db: Session = Depends(get_db)):
    return list(db.scalars(select(Postmortem).order_by(Postmortem.created_at.desc())).all())


@app.post("/api/incidents/{incident_id}/postmortem/generate", response_model=PostmortemOut)
def generate_postmortem(incident_id: int, db: Session = Depends(get_db)):
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    existing = db.scalar(select(Postmortem).where(Postmortem.incident_id == incident_id))
    if existing:
        return existing
    evidence = list(db.scalars(select(Evidence).where(Evidence.incident_id == incident_id)).all())
    summary = f"Generated from a synthetic incident scenario. {incident.summary}"
    root_cause = evidence[0].message if evidence else "No correlated evidence has been attached yet; root cause remains unconfirmed."
    remediation = db.scalar(
        select(Remediation).where(Remediation.incident_id == incident_id).order_by(Remediation.id.desc())
    )
    postmortem = Postmortem(
        incident_id=incident_id,
        title=f"Post-incident review: {incident.title}",
        summary=summary,
        root_cause=f"Scenario hypothesis only — not an AI finding: {root_cause}",
        impact=f"Simulated impact to {incident.service}; no production traffic or users were affected by this prototype.",
        prevention=remediation.result if remediation and remediation.result else "Confirm the hypothesis with real operational evidence before defining prevention work.",
        is_synthetic=True,
    )
    db.add(postmortem)
    db.commit()
    db.refresh(postmortem)
    logger.info("synthetic postmortem generated incident_id=%s", incident_id)
    return postmortem