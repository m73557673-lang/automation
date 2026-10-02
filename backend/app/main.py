import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
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
    OperationalDocument,
    OperationalDocumentChunk,
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
from .services.checkout_simulation import (
    get_checkout_events,
    get_checkout_health,
    get_checkout_metrics,
    initialize_checkout_simulation,
    reset_checkout_simulation,
    start_checkout_simulation,
)
from .services.knowledge_base import (
    MAX_UPLOAD_BYTES,
    SUPPORTED_UPLOAD_EXTENSIONS,
    configured_embedding_provider,
    index_document,
    list_documents,
    retrieve_chunk,
    retrieve_document,
    search_documents,
    seed_operational_documents,
    serialize_document,
    serialize_passage,
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


def create_app(database_engine: Engine = engine, embedding_provider=None) -> FastAPI:
    provider = embedding_provider if embedding_provider is not None else configured_embedding_provider()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        initialize_database(database_engine)
        factory = sessionmaker(bind=database_engine, autoflush=False, expire_on_commit=False)
        with factory() as db:
            seed_database(db)
            initialize_checkout_simulation(db)
            seed_operational_documents(db, provider)
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

    @router.post("/simulation/start")
    def start_checkout_demo(db: Session = Depends(get_db)):
        try:
            return start_checkout_simulation(db)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/simulation/metrics")
    def checkout_demo_metrics(db: Session = Depends(get_db)):
        return get_checkout_metrics(db)

    @router.get("/simulation/health")
    def checkout_demo_health(db: Session = Depends(get_db)):
        return get_checkout_health(db)

    @router.get("/simulation/events")
    def checkout_demo_events(
        limit: int = Query(default=100, ge=1, le=200),
        db: Session = Depends(get_db),
    ):
        return get_checkout_events(db, limit)

    @router.post("/simulation/reset")
    def reset_checkout_demo(db: Session = Depends(get_db)):
        try:
            return reset_checkout_simulation(db)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

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

    @router.get("/knowledge/status")
    def knowledge_status(db: Session = Depends(get_db)):
        documents = db.scalars(select(OperationalDocument)).all()
        chunk_count = db.scalar(select(func.count()).select_from(OperationalDocumentChunk)) or 0
        return {
            "document_count": len(documents),
            "indexed_document_count": sum(item.indexing_status == "indexed" for item in documents),
            "chunk_count": chunk_count,
            "synthetic_document_count": sum(item.is_synthetic for item in documents),
            "retrieval_mode": "semantic" if provider else "keyword_bm25",
            "supported_extensions": sorted(SUPPORTED_UPLOAD_EXTENSIONS),
        }

    @router.get("/knowledge/documents")
    def operational_documents(
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=100),
        db: Session = Depends(get_db),
    ):
        documents, total = list_documents(db, skip, limit)
        return _page([serialize_document(item) for item in documents], total, skip, limit)

    @router.post("/knowledge/documents", status_code=status.HTTP_201_CREATED)
    async def upload_operational_document(
        file: UploadFile = File(...),
        source: str = Form(..., min_length=2, max_length=500),
        approved_by: str = Form(..., min_length=2, max_length=120),
        approved: bool = Form(...),
        title: str | None = Form(default=None, max_length=180),
        db: Session = Depends(get_db),
    ):
        from pathlib import PurePosixPath

        filename = PurePosixPath((file.filename or "").replace("\\", "/")).name
        extension = PurePosixPath(filename).suffix.lower()
        if extension not in SUPPORTED_UPLOAD_EXTENSIONS:
            raise HTTPException(
                status_code=415,
                detail="Only plain text (.txt) and Markdown (.md, .markdown) uploads are supported.",
            )
        if not approved:
            raise HTTPException(
                status_code=400,
                detail="The document must be approved before it can be indexed.",
            )
        raw_content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(raw_content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Documents must be 1 MB or smaller.")
        try:
            content = raw_content.decode("utf-8-sig").strip()
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="Upload must be valid UTF-8 text.") from exc
        if not content:
            raise HTTPException(status_code=400, detail="The document is empty.")
        clean_source = source.strip()
        clean_approver = approved_by.strip()
        if len(clean_source) < 2 or len(clean_approver) < 2:
            raise HTTPException(
                status_code=422,
                detail="Source attribution and approver name must contain at least two non-space characters.",
            )
        clean_title = (title or "").strip() or PurePosixPath(filename).stem.replace("_", " ").replace("-", " ")
        try:
            document = index_document(
                db,
                title=clean_title,
                source=clean_source,
                filename=filename,
                content=content,
                approved_by=clean_approver,
                is_synthetic=False,
                provider=provider,
                source_metadata={
                    "uploaded_filename": filename,
                    "content_type": file.content_type,
                    "approval_confirmed": True,
                },
            )
        except RuntimeError as exc:
            db.rollback()
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        logger.info("approved operational document indexed document_id=%s", document.id)
        return serialize_document(document)

    @router.get("/knowledge/documents/{document_id}")
    def operational_document_detail(document_id: int, db: Session = Depends(get_db)):
        document = retrieve_document(db, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Knowledge document not found.")
        return serialize_document(document)

    @router.get("/knowledge/documents/{document_id}/chunks/{chunk_index}")
    def operational_document_chunk(
        document_id: int,
        chunk_index: int,
        db: Session = Depends(get_db),
    ):
        result = retrieve_chunk(db, document_id, chunk_index)
        if result is None:
            raise HTTPException(status_code=404, detail="Knowledge passage not found.")
        document, chunk = result
        return serialize_passage(document, chunk)

    @router.get("/knowledge/search")
    def search_operational_knowledge(
        q: str = Query(min_length=1, max_length=500),
        limit: int = Query(default=10, ge=1, le=25),
        db: Session = Depends(get_db),
    ):
        if not q.strip():
            raise HTTPException(status_code=422, detail="Enter a search query.")
        try:
            retrieval_mode, passages = search_documents(db, q.strip(), limit, provider)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "query": q.strip(),
            "retrieval_mode": retrieval_mode,
            "items": passages,
        }

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