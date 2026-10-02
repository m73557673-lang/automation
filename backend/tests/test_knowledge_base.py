from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.database import create_sqlite_engine, get_db
from app.main import create_app
from app.models import OperationalDocument
from app.services.knowledge_base import SYNTHETIC_DOCUMENTS


def make_test_client(tmp_path, embedding_provider=None):
    db_engine = create_sqlite_engine(f"sqlite:///{tmp_path / 'knowledge-tests.sqlite'}")
    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    application = create_app(db_engine, embedding_provider=embedding_provider)

    def override_get_db():
        with factory() as db:
            yield db

    application.dependency_overrides[get_db] = override_get_db
    return db_engine, TestClient(application)


def test_seeded_synthetic_library_and_connection_pool_search(tmp_path):
    db_engine, client = make_test_client(tmp_path)
    try:
        with client:
            status = client.get("/api/knowledge/status")
            assert status.status_code == 200
            assert status.json()["retrieval_mode"] == "keyword_bm25"
            assert status.json()["indexed_document_count"] == 7
            assert status.json()["synthetic_document_count"] == 7
            assert status.json()["chunk_count"] >= 7

            library = client.get("/api/knowledge/documents").json()
            titles = {item["title"] for item in library["items"]}
            assert titles == {document.title for document in SYNTHETIC_DOCUMENTS}
            assert all(
                item["is_synthetic"]
                and item["approval_status"] == "approved"
                and item["indexing_status"] == "indexed"
                and item["indexed_chunk_count"] > 0
                for item in library["items"]
            )

            response = client.get(
                "/api/knowledge/search",
                params={"q": "checkout database connection pool timeouts", "limit": 10},
            )
            assert response.status_code == 200
            result = response.json()
            assert result["retrieval_mode"] == "keyword_bm25"
            passages = result["items"]
            result_titles = {passage["title"] for passage in passages}
            assert "Database Connection Pool Troubleshooting Guide" in result_titles
            assert "Historical Incident INC-873" in result_titles
            assert all(
                passage["title"]
                and passage["source"]
                and passage["excerpt"]
                and passage["approval_status"] == "approved"
                for passage in passages
            )
            assert all("synthetic" in passage["source"].lower() for passage in passages)
    finally:
        client.close()
        db_engine.dispose()


def test_approved_markdown_upload_is_chunked_searchable_and_retrievable(tmp_path):
    db_engine, client = make_test_client(tmp_path)
    try:
        with client:
            text = (
                "# Approved pool guide\n\n"
                + "Synthetic pool checkout saturation reference and operator review. " * 55
            )
            uploaded = client.post(
                "/api/knowledge/documents",
                data={
                    "title": "Approved Upload Test",
                    "source": "Approved operations handbook · section 4",
                    "approved_by": "On-call reviewer",
                    "approved": "true",
                },
                files={"file": ("approved-pool-guide.md", text, "text/markdown")},
            )
            assert uploaded.status_code == 201, uploaded.text
            document = uploaded.json()
            assert document["source"] == "Approved operations handbook · section 4"
            assert document["original_filename"] == "approved-pool-guide.md"
            assert document["approval_status"] == "approved"
            assert document["approved_by"] == "On-call reviewer"
            assert not document["is_synthetic"]
            assert document["indexing_status"] == "indexed"
            assert document["indexed_chunk_count"] > 1
            assert document["excerpt"]

            found = client.get(
                "/api/knowledge/search",
                params={"q": "approved pool checkout saturation"},
            ).json()
            passage = next(
                item for item in found["items"] if item["document_id"] == document["id"]
            )
            assert passage["title"] == "Approved Upload Test"
            assert passage["source"] == document["source"]
            assert "saturation" in passage["excerpt"].lower()

            details = client.get(f"/api/knowledge/documents/{document['id']}")
            assert details.status_code == 200
            chunk = client.get(f"/api/knowledge/documents/{document['id']}/chunks/0")
            assert chunk.status_code == 200
            assert chunk.json()["title"] == document["title"]
            assert chunk.json()["source"] == document["source"]
            assert chunk.json()["excerpt"]
    finally:
        client.close()
        db_engine.dispose()


def test_upload_requires_approval_and_rejects_pdf(tmp_path):
    db_engine, client = make_test_client(tmp_path)
    try:
        with client:
            denied = client.post(
                "/api/knowledge/documents",
                data={
                    "title": "Not approved",
                    "source": "Operations handbook",
                    "approved_by": "Reviewer",
                    "approved": "false",
                },
                files={"file": ("guide.md", "# Example", "text/markdown")},
            )
            assert denied.status_code == 400
            assert "approved" in denied.json()["detail"].lower()

            pdf = client.post(
                "/api/knowledge/documents",
                data={
                    "source": "Operations handbook",
                    "approved_by": "Reviewer",
                    "approved": "true",
                },
                files={"file": ("guide.pdf", b"%PDF-1.4 fake", "application/pdf")},
            )
            assert pdf.status_code == 415
            assert "Markdown" in pdf.json()["detail"]

        with sessionmaker(
            bind=db_engine, autoflush=False, expire_on_commit=False
        )() as db:
            assert db.scalar(
                select(OperationalDocument.title).where(OperationalDocument.title == "Not approved")
            ) is None
    finally:
        client.close()
        db_engine.dispose()


def test_configured_embedding_provider_selects_semantic_retriever(tmp_path):
    class FakeEmbeddingProvider:
        def __init__(self):
            self.requests = []

        def embed(self, texts):
            self.requests.append(texts)
            return [
                [0.0, 1.0] if "Historical Incident INC-873" in text or text == "borrowed sessions jammed"
                else [1.0, 0.0]
                for text in texts
            ]

    provider = FakeEmbeddingProvider()
    db_engine, client = make_test_client(tmp_path, provider)
    try:
        with client:
            status = client.get("/api/knowledge/status")
            assert status.json()["retrieval_mode"] == "semantic"
            response = client.get(
                "/api/knowledge/search",
                params={"q": "borrowed sessions jammed", "limit": 1},
            )
            assert response.status_code == 200
            assert response.json()["retrieval_mode"] == "semantic"
            assert response.json()["items"][0]["title"] == "Historical Incident INC-873"
            assert len(provider.requests) > 1
    finally:
        client.close()
        db_engine.dispose()