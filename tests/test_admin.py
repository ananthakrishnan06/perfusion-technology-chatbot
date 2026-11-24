from fastapi.testclient import TestClient

from api.dependencies import get_container
from api.routes_auth import hash_password
from config import settings
from main import app
from storage.admin_models import KnowledgeDocument
from storage.db import get_session_factory


def test_bootstrap_dashboard_password_rotation(test_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_BOOTSTRAP_EMAIL", "bootstrap@example.invalid")
    monkeypatch.setattr(settings, "ADMIN_BOOTSTRAP_PASSWORD_HASH", hash_password("temporary-secret"))
    browser = TestClient(app, headers={"X-Perfusion-Session": "cookie"})
    assert browser.get("/api/v1/admin/page", follow_redirects=False).status_code == 303
    credentials = {"email": "bootstrap@example.invalid", "password": "temporary-secret"}
    response = browser.post("/api/v1/auth/login", json=credentials)
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "admin" and response.json()["password_change_required"]
    assert browser.get("/api/v1/admin/page").status_code == 200
    assert browser.get("/api/v1/admin/users").status_code == 403
    response = browser.post("/api/v1/admin/password", json={"current": "temporary-secret", "replacement": "new-long-admin-secret"})
    assert response.status_code == 204
    assert browser.post("/api/v1/auth/login", json=credentials).status_code == 401
    credentials["password"] = "new-long-admin-secret"
    assert browser.post("/api/v1/auth/login", json=credentials).status_code == 200
    assert browser.get("/api/v1/admin/users").status_code == 200
    assert browser.post("/api/v1/admin/users/perfusion-bootstrap-admin", json={"action": "delete"}).status_code == 403


def test_admin_tracks_and_revokes_user_session(test_client, verified_registration, admin_auth_headers):
    result = verified_registration(test_client, {"email": "private@example.org", "name": "Student One", "password": "a-long-test-password", "role": "admin"})
    assert result.json()["role"] != "admin"
    token = result.json()["token"]
    headers = {"Authorization": "Bearer " + token}
    assert test_client.get("/api/v1/admin/users", headers=headers).status_code == 403
    assert test_client.get("/api/v1/auth/me", headers=headers).status_code == 200
    assert test_client.post("/api/v1/chat/ask", headers=headers, json={"question": "Hello"}).status_code == 200
    report = test_client.get("/api/v1/admin/usage?export=true", headers=admin_auth_headers)
    assert report.status_code == 200 and result.json()["sub"] in report.text and "private@" not in report.text
    records = test_client.get("/api/v1/admin/users", headers=admin_auth_headers)
    assert "private@" not in records.text and "Student One" in records.text
    sessions = test_client.get("/api/v1/admin/sessions", headers=admin_auth_headers)
    assert "private@" not in sessions.text and token not in sessions.text
    session = next(row for row in sessions.json() if row["user_id"] == result.json()["sub"])
    assert test_client.delete("/api/v1/admin/sessions/" + session["id"], headers=admin_auth_headers).status_code == 200
    assert test_client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_admin_pdf_archive_and_scoped_retrieval(test_client, sample_perfusion_pdf_bytes, admin_auth_headers, auth_headers):
    upload = {"files": ("perfusion.pdf", sample_perfusion_pdf_bytes, "application/pdf")}
    payload = {"categories": '{"course":"Perfusion","subject":"Bypass","module":"Circuit equipment"}'}
    assert test_client.post("/api/v1/admin/documents/upload", files=upload, data=payload, headers=auth_headers).status_code == 403
    response = test_client.post("/api/v1/admin/documents/upload", files=upload, data=payload, headers=admin_auth_headers)
    assert response.status_code == 200, response.text
    doc_id = response.json()[0]["document_id"]
    assert test_client.get(f"/api/v1/admin/documents/{doc_id}/preview", headers=admin_auth_headers).headers["content-type"] == "image/png"
    with get_session_factory()() as db:
        row = db.get(KnowledgeDocument, doc_id)
        assert row.pdf == sample_perfusion_pdf_bytes and row.chunks
    service = get_container().chat_service
    from schemas.chat import ChatRequest
    assert service.select_documents(ChatRequest(question="Oxygenation",subject="Bypass"), "Oxygenation") == [doc_id]
    assert doc_id not in service.select_documents(ChatRequest(question="Oxygenation",subject="Other"), "Oxygenation")
    from services.document_service import DocumentService
    from storage.metadata_store import MetadataStore
    from storage.knowledge_archive import restore_library
    from unittest.mock import Mock
    original = get_container().document_service
    fresh_dir = original.documents_dir.parent / "fresh-container"
    fresh = DocumentService(metadata_store=MetadataStore(fresh_dir / "metadata.json"),
                            vector_store=Mock(), keyword_search=Mock(),
                            embedding_manager=original.embedding_manager,
                            documents_dir=fresh_dir / "documents")
    restore_library(fresh)
    assert (fresh.documents_dir / (doc_id + ".pdf")).read_bytes() == sample_perfusion_pdf_bytes
    assert fresh.metadata_store.get_all_chunks([doc_id])
    duplicate = test_client.post("/api/v1/admin/documents/upload", files=upload, data=payload, headers=admin_auth_headers)
    assert duplicate.json()[0]["processing_status"] == "already_indexed"
    assert test_client.delete(f"/api/v1/admin/documents/{doc_id}", headers=admin_auth_headers).status_code == 200
    assert not get_container().metadata_store.get_all_chunks([doc_id])
    with get_session_factory()() as db:
        assert db.get(KnowledgeDocument, doc_id).deleted
    restore_library(fresh)
    assert fresh.metadata_store.get_document(doc_id) is None



def test_admin_settings_enforce_daily_quota_and_maintenance(test_client, admin_auth_headers):
    assert test_client.put("/api/v1/admin/settings", headers=admin_auth_headers, json={"daily_requests": 1}).status_code == 200
    assert test_client.post("/api/v1/chat/ask", json={"question": "Hello"}).status_code == 200
    assert test_client.post("/api/v1/chat/ask", json={"question": "Hello"}).status_code == 429
    assert test_client.put("/api/v1/admin/settings", headers=admin_auth_headers, json={"maintenance": True, "registrations": False}).status_code == 200
    assert test_client.get("/api/v1/auth/config").json()["maintenance"] is True
    assert test_client.post("/api/v1/chat/stream", json={"question": "Hello"}).status_code == 503
    registration = {"name": "New User", "email": "new@example.org", "password": "a-long-password"}
    assert test_client.post("/api/v1/auth/register", json=registration).status_code == 403



def test_usage_report_records_stream_and_gives_real_totals(test_client, admin_auth_headers):
    import json
    from storage.admin_models import UsageEvent

    response = test_client.post("/api/v1/chat/stream", json={"question": "Hello"})
    assert response.status_code == 200
    assert any(json.loads(line[6:])["type"] == "done" for line in response.text.splitlines() if line.startswith("data: "))
    with get_session_factory()() as db:
        row = db.query(UsageEvent).one()
        assert row.operation == "chat_stream" and row.success
    report = test_client.get("/api/v1/admin/usage", headers=admin_auth_headers).json()
    assert report["total"] == 1 and report["failed"] == 0
    assert report["daily"] == {report["end"]: 1}
    assert report["start"] < report["end"]
