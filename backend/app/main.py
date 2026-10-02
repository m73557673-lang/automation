import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .database import SessionLocal, engine, get_db, initialize_database
from .models import (
    Action,
    Deployment,
    Evidence,
    Incident,
    KnowledgeDocument,
    Metric,
    Postmortem,
    Recommendation,
    Service,
    utc_now,
)
from .schemas import (
    ActionDecision,
    ActionOut,
    ActionPage,
    DashboardOut,
    EvidenceOut,
    EvidencePage,
    HealthOut,
    IncidentCreate,
    IncidentDetailOut,
    IncidentPage,
    KnowledgeDocumentOut,
    KnowledgeDocumentPage,
    MetricOut,
    MetricPage,
    Page,
    PostmortemOut,
    PostmortemPage,
    RecommendationOut,
    RemediationOut,
    ServiceOut,
    ServicePage,
)
from .services.incident_service import (
    create_incident,
    get_dashboard,
    get_investigation,
    seed_database,
    serialize_action,
    serialize_evidence,
    serialize_incident,
    serialize_knowledge,
    serialize_postmortem,
    serialize_remediation,
    serialize_service,
)


class JsonFormatter(logging.Formatter):
    def format(self, record):
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


def _page(items, total: int, skip: int, limit: int) -> dict:
    return {"items": items, "total": total, "skip": skip, "limit": limit}


def _incident_or_404(db: Session, incident_id: int) -> Incident:
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return incident


def create_app(database_engine: Engine = engine) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        initialize_database(database_engine)
        factory = sessionmaker(bind=database_engine, autoflush=False, expire_on_commit=False)
        with factory() as db:
            seed_database(db)
        logger.info("normalized SQLite database initialized")
        yield

    application = FastAPI(
        title="Autonomous AI-Powered Incident Commander",
        description=(
            "Incident-response prototype backed by a normalized local SQLite database. "
            "Evidence and recovery checks are simulated; no infrastructure is changed."
        ),
        version="0.2.0",
        lifespan=lifespan,
    )
    router = APIRouter()

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError):
        errors = [
            {
                "field": ".".join(str(part) for part in error["loc"] if part != "body"),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"detail": "Request validation failed.", "errors": errors},
        )

    @application.exception_handler(IntegrityError)
    async def integrity_error_handler(_: Request, exc: IntegrityError):
        logger.warning("database constraint rejected a request: %s", exc.orig)
        return JSONResponse(
            status_code=409,
            content={"detail": "The requested change conflicts with existing database records."},
        )

    @application.exception_handler(Exception)
    async def unexpected_error_handler(_: Request, exc: Exception):
        logger.error("unhandled application error", exc_info=(type(exc), exc, exc.__traceback__))
        return JSONResponse(
            status_code=500,
            content={"detail": "An unexpected error occurred. Check the server log for details."},
        )

    @router.get("/health", response_model=HealthOut)
    def health(db: Session = Depends(get_db)):
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}

    @router.get("/dashboard", response_model=DashboardOut)
    def dashboard(db: Session = Depends(get_db)):
        return get_dashboard(db)

    @router.get("/services", response_model=ServicePage)
    def services(
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
        db: Session = Depends(get_db),
    ):
        total = db.scalar(select(func.count()).select_from(Service)) or 0
        records = db.scalars(
            select(Service).order_by(Service.name).offset(skip).limit(limit)
        ).all()
        return _page([serialize_service(db, item) for item in records], total, skip, limit)

    @router.get("/incidents", response_model=IncidentPage)
    def incidents(
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
        db: Session = Depends(get_db),
    ):
        total = db.scalar(select(func.count()).select_from(Incident)) or 0
        records = db.scalars(
            select(Incident)
            .order_by(Incident.created_at.desc(), Incident.id.desc())
            .offset(skip)
            .limit(limit)
        ).all()
        return _page([serialize_incident(db, item) for item in records], total, skip, limit)

    @router.post("/incidents", response_model=IncidentDetailOut, status_code=status.HTTP_201_CREATED)
    def add_incident(payload: IncidentCreate, db: Session = Depends(get_db)):
        incident = create_incident(db, payload)
        if incident is None:
            raise HTTPException(status_code=404, detail="Service not found.")
        return serialize_incident(db, incident)

    @router.get("/incidents/{incident_id}", response_model=IncidentDetailOut)
    def incident_detail(incident_id: int, db: Session = Depends(get_db)):
        return serialize_incident(db, _incident_or_404(db, incident_id))

    @router.get("/incidents/{incident_id}/evidence", response_model=EvidencePage)
    def incident_evidence(
        incident_id: int,
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=100),
        db: Session = Depends(get_db),
    ):
        _incident_or_404(db, incident_id)
        filters = Evidence.incident_id == incident_id
        total = db.scalar(select(func.count()).select_from(Evidence).where(filters)) or 0
        records = db.scalars(
            select(Evidence)
            .where(filters)
            .order_by(Evidence.relevance.desc(), Evidence.created_at)
            .offset(skip)
            .limit(limit)
        ).all()
        return _page([serialize_evidence(db, item) for item in records], total, skip, limit)

    @router.get("/incidents/{incident_id}/metrics", response_model=MetricPage)
    def incident_metrics(
        incident_id: int,
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=100),
        db: Session = Depends(get_db),
    ):
        incident = _incident_or_404(db, incident_id)
        filters = [Metric.service_id == incident.service_id, Metric.timestamp >= incident.created_at]
        if incident.resolved_at:
            filters.append(Metric.timestamp <= incident.resolved_at)
        total = db.scalar(select(func.count()).select_from(Metric).where(*filters)) or 0
        records = db.scalars(
            select(Metric)
            .where(*filters)
            .order_by(Metric.timestamp, Metric.id)
            .offset(skip)
            .limit(limit)
        ).all()
        return _page([
            {
                "id": item.id,
                "service_id": item.service_id,
                "timestamp": item.timestamp,
                "metric_name": item.metric_name,
                "value": item.value,
            }
            for item in records
        ], total, skip, limit)

    @router.get("/incidents/{incident_id}/recommendation", response_model=RecommendationOut)
    def incident_recommendation(incident_id: int, db: Session = Depends(get_db)):
        _incident_or_404(db, incident_id)
        recommendation = db.scalar(
            select(Recommendation)
            .where(Recommendation.incident_id == incident_id)
            .order_by(Recommendation.created_at.desc(), Recommendation.id.desc())
            .limit(1)
        )
        if recommendation is None:
            raise HTTPException(status_code=404, detail="No recommendation is recorded for this incident.")
        return recommendation

    @router.get("/incidents/{incident_id}/actions", response_model=ActionPage)
    def incident_actions(
        incident_id: int,
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
        db: Session = Depends(get_db),
    ):
        _incident_or_404(db, incident_id)
        filters = Action.incident_id == incident_id
        total = db.scalar(select(func.count()).select_from(Action).where(filters)) or 0
        records = db.scalars(
            select(Action).where(filters).order_by(Action.created_at.desc()).offset(skip).limit(limit)
        ).all()
        return _page([serialize_action(item) for item in records], total, skip, limit)

    @router.get("/incidents/{incident_id}/postmortem", response_model=PostmortemOut)
    def incident_postmortem(incident_id: int, db: Session = Depends(get_db)):
        _incident_or_404(db, incident_id)
        postmortem = db.scalar(select(Postmortem).where(Postmortem.incident_id == incident_id))
        if postmortem is None:
            raise HTTPException(status_code=404, detail="No postmortem has been recorded for this incident.")
        return serialize_postmortem(db, postmortem)

    @router.get("/incidents/{incident_id}/investigation")
    def investigation(incident_id: int, db: Session = Depends(get_db)):
        result = get_investigation(db, incident_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Incident not found.")
        return result

    @router.get("/knowledge", response_model=KnowledgeDocumentPage)
    def knowledge(
        q: str = Query(default="", max_length=120),
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=100),
        db: Session = Depends(get_db),
    ):
        statement = select(KnowledgeDocument)
        count_statement = select(func.count()).select_from(KnowledgeDocument)
        if q.strip():
            term = f"%{q.strip()}%"
            criterion = or_(
                KnowledgeDocument.title.ilike(term),
                KnowledgeDocument.source.ilike(term),
                KnowledgeDocument.type.ilike(term),
                KnowledgeDocument.content.ilike(term),
            )
            statement = statement.where(criterion)
            count_statement = count_statement.where(criterion)
        total = db.scalar(count_statement) or 0
        records = db.scalars(
            statement.order_by(KnowledgeDocument.title).offset(skip).limit(limit)
        ).all()
        return _page([serialize_knowledge(item) for item in records], total, skip, limit)

    @router.get("/postmortems", response_model=PostmortemPage)
    def postmortems(
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
        db: Session = Depends(get_db),
    ):
        total = db.scalar(select(func.count()).select_from(Postmortem)) or 0
        records = db.scalars(
            select(Postmortem)
            .order_by(Postmortem.created_at.desc(), Postmortem.id.desc())
            .offset(skip)
            .limit(limit)
        ).all()
        return _page([serialize_postmortem(db, item) for item in records], total, skip, limit)

    @router.post(
        "/incidents/{incident_id}/remediation/approve",
        response_model=RemediationOut,
    )
    def approve_remediation(
        incident_id: int,
        payload: ActionDecision = Body(default=ActionDecision(approved_by="Incident Commander UI")),
        db: Session = Depends(get_db),
    ):
        incident = _incident_or_404(db, incident_id)
        latest = db.scalar(
            select(Action).where(Action.incident_id == incident_id).order_by(Action.created_at.desc()).limit(1)
        )
        if latest and latest.status in {"approved", "simulated_validated"}:
            return serialize_remediation(latest)
        if latest and latest.status == "rejected":
            raise HTTPException(status_code=409, detail="This simulation proposal was rejected.")
        recommendation = db.scalar(
            select(Recommendation)
            .where(Recommendation.incident_id == incident_id)
            .order_by(Recommendation.created_at.desc())
            .limit(1)
        )
        if recommendation is None:
            raise HTTPException(status_code=404, detail="No recommendation is available to approve.")
        action = Action(
            incident_id=incident.id,
            action=recommendation.action,
            approved_by=payload.approved_by,
            status="approved",
            result="Approved for simulation only. No production service or infrastructure was changed.",
        )
        if incident.status == "open":
            incident.status = "investigating"
        db.add(action)
        db.commit()
        db.refresh(action)
        logger.info("simulation action approved incident_id=%s", incident_id)
        return serialize_remediation(action)

    @router.post(
        "/incidents/{incident_id}/remediation/reject",
        response_model=RemediationOut,
    )
    def reject_remediation(
        incident_id: int,
        payload: ActionDecision = Body(default=ActionDecision(approved_by="Incident Commander UI")),
        db: Session = Depends(get_db),
    ):
        incident = _incident_or_404(db, incident_id)
        latest = db.scalar(
            select(Action).where(Action.incident_id == incident_id).order_by(Action.created_at.desc()).limit(1)
        )
        if latest and latest.status in {"approved", "simulated_validated"}:
            raise HTTPException(status_code=409, detail="An approved simulation cannot be rejected.")
        recommendation = db.scalar(
            select(Recommendation)
            .where(Recommendation.incident_id == incident_id)
            .order_by(Recommendation.created_at.desc())
            .limit(1)
        )
        if recommendation is None:
            raise HTTPException(status_code=404, detail="No recommendation is available to reject.")
        action = Action(
            incident_id=incident.id,
            action=recommendation.action,
            status="rejected",
            result=f"Rejected by {payload.approved_by}. No changes were made to infrastructure.",
        )
        db.add(action)
        db.commit()
        db.refresh(action)
        return serialize_remediation(action)

    @router.post("/remediations/{remediation_id}/validate", response_model=RemediationOut)
    def validate_recovery(remediation_id: int, db: Session = Depends(get_db)):
        action = db.get(Action, remediation_id)
        if action is None:
            raise HTTPException(status_code=404, detail="Simulation action not found.")
        if action.status != "approved":
            raise HTTPException(status_code=409, detail="Only an approved simulation can be validated.")
        action.status = "simulated_validated"
        action.result = (
            "Simulated recovery check passed. This records a prototype result only; "
            "no production metrics or infrastructure were changed."
        )
        action.updated_at = utc_now()
        incident = db.get(Incident, action.incident_id)
        if incident:
            incident.status = "resolved"
            incident.resolved_at = utc_now()
        db.commit()
        db.refresh(action)
        logger.info("simulated recovery check recorded action_id=%s", remediation_id)
        return serialize_remediation(action)

    @router.post("/incidents/{incident_id}/postmortem/generate", response_model=PostmortemOut)
    def generate_postmortem(incident_id: int, db: Session = Depends(get_db)):
        incident = _incident_or_404(db, incident_id)
        existing = db.scalar(select(Postmortem).where(Postmortem.incident_id == incident_id))
        if existing:
            return serialize_postmortem(db, existing)
        evidence = db.scalars(
            select(Evidence)
            .where(Evidence.incident_id == incident_id)
            .order_by(Evidence.relevance.desc())
        ).all()
        if evidence:
            evidence_data = serialize_evidence(db, evidence[0])
            root_cause = (
                f"Scenario hypothesis based on {evidence_data['source']}: {evidence_data['message']}"
            )
        else:
            root_cause = "No correlated evidence is attached; the scenario root cause remains unconfirmed."
        postmortem = Postmortem(
            incident_id=incident.id,
            summary=(
                f"Template report for {incident.title}. "
                "This report summarizes local scenario records; it was not generated by AI."
            ),
            root_cause=root_cause,
            prevention=(
                "Validate the scenario hypothesis against authoritative operational evidence "
                "before defining any production prevention work."
            ),
        )
        db.add(postmortem)
        db.commit()
        db.refresh(postmortem)
        logger.info("deterministic postmortem template created incident_id=%s", incident_id)
        return serialize_postmortem(db, postmortem)

    application.include_router(router)
    application.include_router(router, prefix="/api", include_in_schema=False)
    return application


app = create_app()