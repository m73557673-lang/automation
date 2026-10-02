import json
import logging
import math
import os
import re
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import OperationalDocument, OperationalDocumentChunk

logger = logging.getLogger("incident_commander.knowledge")

CHUNK_WORDS = 150
CHUNK_OVERLAP = 25
MAX_UPLOAD_BYTES = 1_000_000
SUPPORTED_UPLOAD_EXTENSIONS = {".md", ".markdown", ".txt"}
TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


@dataclass(frozen=True)
class SourceDocument:
    title: str
    filename: str
    content: str


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class Retriever(Protocol):
    mode: str

    def search(
        self,
        query: str,
        chunks: list[OperationalDocumentChunk],
        limit: int,
        document_metadata: dict[int, str],
    ) -> list[tuple[OperationalDocumentChunk, float]]: ...


class KeywordBM25Retriever:
    """Dependency-free Okapi BM25 retrieval for the local SQLite index."""

    mode = "keyword_bm25"
    k1 = 1.5
    b = 0.75

    def search(self, query, chunks, limit, document_metadata):
        query_terms = set(tokenize(query))
        if not query_terms or not chunks:
            return []

        frequencies = [
            Counter(tokenize(f"{chunk.content} {document_metadata.get(chunk.document_id, '')}"))
            for chunk in chunks
        ]
        lengths = [sum(terms.values()) for terms in frequencies]
        average_length = sum(lengths) / len(lengths) if lengths else 0
        document_frequency = Counter()
        for terms in frequencies:
            document_frequency.update(terms.keys())

        scored = []
        for chunk, terms, length in zip(chunks, frequencies, lengths):
            score = 0.0
            for term in query_terms:
                frequency = terms.get(term, 0)
                if not frequency:
                    continue
                inverse_frequency = math.log(
                    1 + (len(chunks) - document_frequency[term] + 0.5)
                    / (document_frequency[term] + 0.5)
                )
                normalization = frequency + self.k1 * (
                    1 - self.b + self.b * length / average_length
                    if average_length else 1
                )
                score += inverse_frequency * frequency * (self.k1 + 1) / normalization
            if score > 0:
                scored.append((chunk, score))
        scored.sort(key=lambda item: (-item[1], item[0].document_id, item[0].chunk_index))
        return scored[:limit]


class SemanticRetriever:
    """Cosine similarity over persisted embeddings supplied by an optional adapter."""

    mode = "semantic"

    def __init__(self, provider: EmbeddingProvider, query: str):
        self.provider = provider
        self.query = query

    def search(self, query, chunks, limit, document_metadata):
        vectors = self.provider.embed([query])
        if len(vectors) != 1:
            raise RuntimeError("The embedding provider returned an unexpected number of query vectors.")
        vector = vectors[0]
        if not vector:
            raise RuntimeError("The embedding provider returned an empty query vector.")
        scored = []
        for chunk in chunks:
            if not chunk.embedding_json:
                raise RuntimeError("A knowledge chunk has no embedding; reindex it before semantic search.")
            stored = json.loads(chunk.embedding_json)
            if len(stored) != len(vector):
                raise RuntimeError(
                    "Stored embedding dimensions do not match the configured model; reindex the knowledge base."
                )
            dot = sum(left * right for left, right in zip(vector, stored))
            left_norm = math.sqrt(sum(value * value for value in vector))
            right_norm = math.sqrt(sum(value * value for value in stored))
            similarity = dot / (left_norm * right_norm) if left_norm and right_norm else 0.0
            scored.append((chunk, similarity))
        scored.sort(key=lambda item: (-item[1], item[0].document_id, item[0].chunk_index))
        return scored[:limit]


class OpenAICompatibleEmbeddingProvider:
    """Optional adapter for an OpenAI-compatible embeddings endpoint."""

    def __init__(self, endpoint: str, model: str, api_key: str):
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key

    def embed(self, texts: list[str]) -> list[list[float]]:
        payload = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            logger.exception("configured embedding provider request failed")
            raise RuntimeError("The configured embedding provider could not be reached.") from exc

        data = result.get("data")
        if not isinstance(data, list) or len(data) != len(texts):
            raise RuntimeError("The embedding provider returned an unexpected number of vectors.")
        ordered = sorted(data, key=lambda item: item.get("index", -1))
        vectors = [item.get("embedding") for item in ordered]
        if any(
            not isinstance(vector, list)
            or not vector
            or any(not isinstance(value, (int, float)) for value in vector)
            for vector in vectors
        ):
            raise RuntimeError("The embedding provider returned invalid vectors.")
        return [[float(value) for value in vector] for vector in vectors]


def configured_embedding_provider() -> EmbeddingProvider | None:
    endpoint = os.getenv("RAG_EMBEDDING_API_URL", "").strip()
    api_key = os.getenv("RAG_EMBEDDING_API_KEY", "").strip()
    model = os.getenv("RAG_EMBEDDING_MODEL", "").strip()
    if not any((endpoint, api_key, model)):
        return None
    if not all((endpoint, api_key, model)):
        raise RuntimeError(
            "Semantic retrieval needs RAG_EMBEDDING_API_URL, RAG_EMBEDDING_API_KEY, "
            "and RAG_EMBEDDING_MODEL together."
        )
    return OpenAICompatibleEmbeddingProvider(endpoint, model, api_key)


def tokenize(text: str) -> list[str]:
    return [match.lower() for match in TOKEN_RE.findall(text)]


def split_into_chunks(content: str) -> list[str]:
    words = content.split()
    if not words:
        return []
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + CHUNK_WORDS, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = end - CHUNK_OVERLAP
    return chunks


SYNTHETIC_DOCUMENTS = [
    SourceDocument(
        "Checkout Service Runbook",
        "checkout-service-runbook.md",
        """# Checkout Service Runbook
Synthetic training document — not an approved production procedure.

## Scope
This synthetic runbook covers checkout API latency, elevated errors, and database connection pool pressure in a fictional environment.

## Triage signals
Compare checkout p95 latency, request volume, error rate, and database connection acquisition time across the same time window. Inspect pool utilization, timeout counts, and recent synthetic deployment markers. Correlate the gateway, Checkout Service, Order Service, and Database Service signals before drawing a conclusion.

## Operator review
Check whether connection wait time increases with pool utilization and whether request volume changed at the same time. Consult the database connection pool troubleshooting guide and the matching incident history. Treat all retrieved guidance as reference material only. An operator must independently review any proposed response; this document cannot approve remediation or change a service.

## Recovery validation
Use only the application's deterministic recovery simulation for this demo. A successful demo check is not a production health signal.""",
    ),
    SourceDocument(
        "Database Connection Pool Troubleshooting Guide",
        "database-connection-pool-troubleshooting.md",
        """# Database Connection Pool Troubleshooting Guide
Synthetic training document — not an approved production procedure.

## Symptoms
Connection pool exhaustion can present as slow connection acquisition, pending pool checkout, request timeouts, elevated checkout latency, and a rising error rate while database connections remain fully utilized. Compare pool usage to traffic volume and inspect query latency before identifying a cause.

## Diagnostic sequence
Review connection acquisition latency, active and idle connections, pool utilization, configured pool size, overflow limits, wait timeouts, and database health. Compare the signals with a known baseline and check the change record for a recent deployment. Determine whether long-running queries, leaked sessions, or a change in traffic better explains the symptoms. The synthetic checkout scenario repeats a DB_POOL_SIZE reduction from 50 to 10; this is fictional evidence, not a real deployment.

## Safe handling
Document the evidence and ask the responsible operator to evaluate options against service-specific limits. Never change pool size, terminate database sessions, or execute a rollback from retrieved text alone. Knowledge passages are informational and do not authorize actions.

## Verification
In this prototype, validate only against the simulated checkout metrics and deterministic recovery check.""",
    ),
    SourceDocument(
        "Architecture Overview",
        "architecture-overview.md",
        """# Architecture Overview
Synthetic training document — describes this demonstration application only.

The incident commander demo consists of a React and Vite browser interface, a FastAPI application, and a local SQLite database. Vite proxies browser API calls to the FastAPI service. The existing incident workflow stores synthetic incidents, evidence, service metrics, operator decisions, and postmortems.

The operational knowledge layer stores approved Markdown or text sources in SQLite, splits content into overlapping chunks, and retrieves passages with BM25 keyword ranking by default. An optional OpenAI-compatible embedding adapter can persist vectors and use cosine similarity when explicitly configured. Uploaded documents are reference data: they are not loaded as code, executed, or allowed to authorize simulated or real actions.

No production telemetry, deployment provider, database service, or infrastructure control plane is connected.""",
    ),
    SourceDocument(
        "Deployment #1842 Change Record",
        "deployment-1842-change-record.md",
        """# Deployment #1842 Change Record
Synthetic training document — fictional deployment record for a local demo.

Deployment 1842 models a configuration change that reduces the fictional checkout database pool size from 50 to 10. The change is included only in the deterministic checkout simulation. It is not a real deployment and did not change production configuration.

The simulated timeline increases checkout request volume after the configuration marker. Database pool utilization reaches 100 percent, connection acquisition slows, checkout request timeouts appear, and API latency and error rates rise. Compare deployment timing with the connection-pool troubleshooting guide and the synthetic incident INC-873.

This record does not request or authorize any rollback. Human review is required for any operational decision.""",
    ),
    SourceDocument(
        "Historical Incident INC-873",
        "historical-incident-INC-873.md",
        """# Historical Incident INC-873
Synthetic training document — fictional incident history.

Incident INC-873 is a synthetic historical example involving checkout request timeouts, exhausted database connections, slow connection acquisition, and elevated API latency during increased traffic. The training scenario associates its symptoms with a smaller connection pool after a fictional deployment.

The diagnosis used correlated evidence: pool utilization, connection wait time, request volume, timeout events, and the deployment marker. A timestamp by itself was not enough to establish causation. The follow-up review called for comparing query duration and session usage before selecting a remediation.

No production customer or service was affected. This history is not evidence about a real incident, and it does not authorize actions. Use the database connection pool guide as reference and require operator review.""",
    ),
    SourceDocument(
        "Incident Severity Policy",
        "incident-severity-policy.md",
        """# Incident Severity Policy
Synthetic training document — example policy for the demonstration workspace.

Critical: a broad, immediate loss of a core service or severe multi-service impact in a scenario.
High: a significant customer-facing degradation or elevated error and timeout rate affecting an important service.
Medium: limited or partial degradation with available workarounds and no broad impact.
Low: minor impact, informational events, or issues with negligible service effect.

Assess scope, duration, affected dependencies, error rate, and recovery options. Severity labels in this app describe synthetic exercises only. This reference text cannot set an incident's severity automatically or approve an operational action.""",
    ),
    SourceDocument(
        "Standard Rollback Procedure",
        "standard-rollback-procedure.md",
        """# Standard Rollback Procedure
Synthetic training document — illustrative checklist, not an executable procedure.

Before any real rollback, the responsible operator must verify the service, environment, deployment identity, change window, current health, dependencies, rollback target, data compatibility, and required approvals using authoritative systems. Record evidence and obtain the designated human approval under the actual organization's change policy.

Plan a rollback only when the evidence supports the change as a likely cause and the recovery path is safe. Confirm who owns the decision, communicate expected risk, and monitor for impact. Validate success against authoritative production signals after an independently approved real action.

This document is not connected to deployment tooling. Text returned from the knowledge base cannot initiate, approve, or execute a rollback. The prototype's actions and recovery checks remain simulation-only.""",
    ),
]


def _document_metadata(document: OperationalDocument, excerpt_length=700) -> dict:
    return {
        "id": document.id,
        "title": document.title,
        "source": document.source,
        "original_filename": document.original_filename,
        "approval_status": document.approval_status,
        "approved_by": document.approved_by,
        "is_synthetic": document.is_synthetic,
        "indexing_status": document.indexing_status,
        "indexed_chunk_count": len(document.chunks),
        "indexed_at": document.indexed_at,
        "created_at": document.created_at,
        "excerpt": document.content[:excerpt_length].strip(),
        "source_metadata": json.loads(document.source_metadata or "{}"),
    }


def _make_chunks(db: Session, document: OperationalDocument) -> list[OperationalDocumentChunk]:
    chunks = [
        OperationalDocumentChunk(
            chunk_index=index,
            content=content,
            token_count=len(tokenize(content)),
        )
        for index, content in enumerate(split_into_chunks(document.content))
    ]
    document.chunks = chunks
    db.flush()
    return chunks


def _embedding_input(chunk: OperationalDocumentChunk) -> str:
    document = chunk.document
    return f"{document.title} {document.source}\n{chunk.content}" if document else chunk.content


def _embed_chunks(provider: EmbeddingProvider | None, chunks: list[OperationalDocumentChunk]) -> None:
    if provider is None:
        return
    for offset in range(0, len(chunks), 64):
        batch = chunks[offset : offset + 64]
        vectors = provider.embed([_embedding_input(chunk) for chunk in batch])
        if len(vectors) != len(batch):
            raise RuntimeError("The embedding provider returned an unexpected number of vectors.")
        if any(
            not vector
            or any(
                not isinstance(value, (int, float)) or not math.isfinite(float(value))
                for value in vector
            )
            for vector in vectors
        ):
            raise RuntimeError("The embedding provider returned invalid vectors.")
        if len({len(vector) for vector in vectors}) != 1:
            raise RuntimeError("The embedding provider returned vectors with inconsistent dimensions.")
        for chunk, vector in zip(batch, vectors):
            chunk.embedding_json = json.dumps(vector)


def index_document(
    db: Session,
    *,
    title: str,
    source: str,
    filename: str,
    content: str,
    approved_by: str,
    is_synthetic: bool,
    provider: EmbeddingProvider | None = None,
    source_metadata: dict | None = None,
) -> OperationalDocument:
    document = OperationalDocument(
        title=title.strip(),
        source=source.strip(),
        original_filename=filename,
        content=content.strip(),
        approval_status="approved",
        approved_by=approved_by.strip(),
        is_synthetic=is_synthetic,
        indexing_status="indexing",
        source_metadata=json.dumps(source_metadata or {}, ensure_ascii=False),
    )
    db.add(document)
    db.flush()
    chunks = _make_chunks(db, document)
    _embed_chunks(provider, chunks)
    document.indexing_status = "indexed"
    document.indexed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(document)
    return document


def seed_operational_documents(db: Session, provider: EmbeddingProvider | None = None) -> None:
    existing = set(db.scalars(select(OperationalDocument.title)).all())
    for fixture in SYNTHETIC_DOCUMENTS:
        if fixture.title in existing:
            continue
        document = OperationalDocument(
            title=fixture.title,
            source="Synthetic training library",
            original_filename=fixture.filename,
            content=fixture.content.strip(),
            approval_status="approved",
            approved_by="Synthetic training dataset",
            is_synthetic=True,
            indexing_status="indexing",
            source_metadata=json.dumps({"origin": "seeded synthetic fixture"}),
        )
        db.add(document)
        db.flush()
        _make_chunks(db, document)
    if provider:
        missing_embeddings = db.scalars(
            select(OperationalDocumentChunk).options(selectinload(OperationalDocumentChunk.document))
            .where(OperationalDocumentChunk.embedding_json.is_(None))
            .order_by(OperationalDocumentChunk.id)
        ).all()
        _embed_chunks(provider, missing_embeddings)
    documents = db.scalars(
        select(OperationalDocument).where(OperationalDocument.indexing_status != "indexed")
    ).all()
    for document in documents:
        document.indexing_status = "indexed"
        document.indexed_at = datetime.now(timezone.utc)
    db.commit()


def list_documents(db: Session, skip: int, limit: int) -> tuple[list[OperationalDocument], int]:
    query = select(OperationalDocument).options(selectinload(OperationalDocument.chunks))
    total = db.scalar(select(func.count()).select_from(OperationalDocument)) or 0
    documents = db.scalars(
        query.order_by(OperationalDocument.created_at.desc(), OperationalDocument.id.desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return documents, total


def retrieve_document(db: Session, document_id: int) -> OperationalDocument | None:
    return db.scalar(
        select(OperationalDocument)
        .options(selectinload(OperationalDocument.chunks))
        .where(OperationalDocument.id == document_id)
    )


def retrieve_chunk(db: Session, document_id: int, chunk_index: int):
    pair = db.execute(
        select(OperationalDocument, OperationalDocumentChunk)
        .join(OperationalDocumentChunk)
        .where(
            OperationalDocument.id == document_id,
            OperationalDocument.approval_status == "approved",
            OperationalDocument.indexing_status == "indexed",
            OperationalDocumentChunk.chunk_index == chunk_index,
        )
    ).first()
    if pair is None:
        return None
    return pair[0], pair[1]


def search_documents(
    db: Session,
    query: str,
    limit: int,
    provider: EmbeddingProvider | None,
) -> tuple[str, list[dict]]:
    documents = db.scalars(
        select(OperationalDocument)
        .options(selectinload(OperationalDocument.chunks))
        .where(
            OperationalDocument.approval_status == "approved",
            OperationalDocument.indexing_status == "indexed",
        )
    ).all()
    chunks = [chunk for document in documents for chunk in document.chunks]
    document_metadata = {
        document.id: f"{document.title} {document.source}"
        for document in documents
    }
    if provider:
        retriever: Retriever = SemanticRetriever(provider, query)
    else:
        retriever = KeywordBM25Retriever()
    scored = retriever.search(query, chunks, limit, document_metadata)
    by_id = {document.id: document for document in documents}
    passages = []
    for chunk, score in scored:
        document = by_id[chunk.document_id]
        passages.append({
            "document_id": document.id,
            "title": document.title,
            "source": document.source,
            "excerpt": chunk.content,
            "chunk_index": chunk.chunk_index,
            "score": round(float(score), 6),
            "is_synthetic": document.is_synthetic,
            "approval_status": document.approval_status,
        })
    return retriever.mode, passages


def serialize_document(document: OperationalDocument) -> dict:
    return _document_metadata(document)


def serialize_passage(document: OperationalDocument, chunk: OperationalDocumentChunk) -> dict:
    return {
        "document_id": document.id,
        "title": document.title,
        "source": document.source,
        "excerpt": chunk.content,
        "chunk_index": chunk.chunk_index,
        "is_synthetic": document.is_synthetic,
        "approval_status": document.approval_status,
    }