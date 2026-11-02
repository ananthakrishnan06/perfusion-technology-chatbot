import io
import json
import os
from unittest.mock import MagicMock
import pytest
from generation.groq_client import GroqAPIError, GroqConfigurationError


def test_health_endpoint(test_client):
    """Test GET /health returns 200 OK with proper service metadata."""
    res = test_client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["service"] == "PerfusionGPT"
    assert "version" in data


def test_document_upload_and_management_api(test_client, sample_perfusion_pdf_bytes, auth_headers):
    """Test full document REST API flow: upload, list, get details, delete, and auth enforcement."""
    # 0. Verify unauthenticated document access returns 401
    files_unauth = [
        ("files", ("perfusion_manual.pdf", sample_perfusion_pdf_bytes, "application/pdf"))
    ]
    assert test_client.post("/api/v1/documents/upload", files=files_unauth).status_code == 401
    assert test_client.get("/api/v1/documents").status_code == 401
    assert test_client.get("/api/v1/documents/dummy_id").status_code == 401
    assert test_client.delete("/api/v1/documents/dummy_id").status_code == 401

    # 1. Upload valid PDF with authentication
    files = [
        ("files", ("perfusion_manual.pdf", sample_perfusion_pdf_bytes, "application/pdf"))
    ]
    res_upload = test_client.post("/api/v1/documents/upload", files=files, headers=auth_headers)
    assert res_upload.status_code == 200
    upload_data = res_upload.json()
    assert upload_data["total_uploaded"] == 1
    assert upload_data["total_failed"] == 0
    doc_id = upload_data["results"][0]["document_id"]
    assert upload_data["results"][0]["processing_status"] == "indexed"
    assert upload_data["results"][0]["page_count"] == 3

    # 2. List documents
    res_list = test_client.get("/api/v1/documents", headers=auth_headers)
    assert res_list.status_code == 200
    list_data = res_list.json()
    assert list_data["total_documents"] == 1
    assert list_data["documents"][0]["document_id"] == doc_id

    # 3. Get document details
    res_detail = test_client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers)
    assert res_detail.status_code == 200
    detail_data = res_detail.json()
    assert detail_data["document"]["document_id"] == doc_id
    assert len(detail_data["sample_chunks"]) > 0

    # 4. Search sources endpoint (no LLM call)
    search_payload = {
        "query": "What are centrifugal pumps in CPB?",
        "top_k": 3
    }
    res_search = test_client.post("/api/v1/retrieval/search", json=search_payload)
    assert res_search.status_code == 200
    search_data = res_search.json()
    assert search_data["total_retrieved"] > 0
    assert "centrifugal" in search_data["retrieved_chunks"][0]["text"].lower()
    assert search_data["retrieved_chunks"][0]["page"] == 1

    # 5. Delete document
    res_del = test_client.delete(f"/api/v1/documents/{doc_id}", headers=auth_headers)
    assert res_del.status_code == 200
    del_data = res_del.json()
    assert del_data["status"] == "success"

    # Verify 404 after deletion
    res_get_deleted = test_client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers)
    assert res_get_deleted.status_code == 404


def test_upload_invalid_file(test_client, auth_headers):
    """Test uploading an invalid non-PDF file returns 400 Bad Request."""
    files = [
        ("files", ("notes.txt", b"plain text notes", "text/plain"))
    ]
    res = test_client.post("/api/v1/documents/upload", files=files, headers=auth_headers)
    assert res.status_code == 400
    assert "Only .pdf files are accepted" in res.json()["detail"]


def test_upload_size_limit_streaming(test_client, auth_headers, monkeypatch):
    """Test that file exceeding MAX_UPLOAD_SIZE_MB is rejected early with 413."""
    from config import settings
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)  # 1 MB threshold for test
    oversized_data = b"%PDF-1.4\n" + b"0" * (1024 * 1024 + 100)
    files = [
        ("files", ("large_test.pdf", oversized_data, "application/pdf"))
    ]
    res = test_client.post("/api/v1/documents/upload", files=files, headers=auth_headers)
    assert res.status_code == 413
    assert "exceeds maximum allowed upload size" in res.json()["detail"]


def test_chat_ask_missing_evidence(test_client):
    """Test chat endpoint when index is empty returns insufficient evidence response without error."""
    payload = {
        "question": "What is the priming volume of an adult CPB circuit?",
        "top_k": 3
    }
    res = test_client.post("/api/v1/chat/ask", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["insufficient_evidence"] is True
    assert data["grounded"] is False
    assert "could not find sufficient supporting information" in data["answer"].lower()
    assert len(data["citations"]) == 0


def test_chat_ask_with_mocked_groq(test_client, sample_perfusion_pdf_bytes, auth_headers, monkeypatch):
    """Test chat ask endpoint with indexed documents and mocked completion response."""
    # 1. Ingest document first
    files = [
        ("files", ("perfusion.pdf", sample_perfusion_pdf_bytes, "application/pdf"))
    ]
    res_up = test_client.post("/api/v1/documents/upload", files=files, headers=auth_headers)
    assert res_up.status_code == 200

    # 2. Mock completion generator
    from api.dependencies import get_container
    container = get_container()

    mock_answer = (
        "### Function of Membrane Oxygenator\n\n"
        "According to the indexed documents, modern CPB membrane oxygenators utilize hollow-fiber microporous "
        "polypropylene or polymethylpentene (PMP) membranes. PaO2 is regulated by adjusting FiO2, while "
        "carbon dioxide elimination is controlled directly by the sweep gas flow rate."
    )
    monkeypatch.setattr(
        container.answer_generator,
        "_generate_completion",
        MagicMock(return_value=mock_answer)
    )

    # 3. Ask question
    payload = {
        "question": "How do membrane oxygenators control oxygenation and carbon dioxide removal?",
        "top_k": 3
    }
    res = test_client.post("/api/v1/chat/ask", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["grounded"] is True
    assert data["insufficient_evidence"] is False
    assert "sweep gas" in data["answer"]
    assert len(data["citations"]) > 0
    assert data["citations"][0]["source"] == "perfusion.pdf"
    assert data["citations"][0]["page"] == 2


def test_chat_groq_api_error_handling(test_client, sample_perfusion_pdf_bytes, auth_headers, monkeypatch):
    """Test that upstream LLM failures return clean 502 Bad Gateway responses without raw exceptions."""
    # Ingest document
    files = [
        ("files", ("perfusion.pdf", sample_perfusion_pdf_bytes, "application/pdf"))
    ]
    res_up = test_client.post("/api/v1/documents/upload", files=files, headers=auth_headers)
    assert res_up.status_code == 200

    from api.dependencies import get_container
    container = get_container()

    monkeypatch.setattr(
        container.answer_generator,
        "_generate_completion",
        MagicMock(side_effect=GroqAPIError("Connection timeout to Groq endpoint"))
    )

    payload = {"question": "Explain roller pumps.", "top_k": 2}
    res = test_client.post("/api/v1/chat/ask", json=payload)
    assert res.status_code == 502
    assert "upstream provider error" in res.json()["detail"]


def test_study_mcq_generation(test_client, sample_perfusion_pdf_bytes, auth_headers, monkeypatch):
    """Test MCQ generation endpoint with mocked LLM response."""
    # Ingest document
    files = [
        ("files", ("perfusion.pdf", sample_perfusion_pdf_bytes, "application/pdf"))
    ]
    res_up = test_client.post("/api/v1/documents/upload", files=files, headers=auth_headers)
    assert res_up.status_code == 200

    from api.dependencies import get_container
    container = get_container()

    mock_mcq_json = json.dumps({
        "questions": [
            {
                "question": "Which mechanism controls carbon dioxide elimination during cardiopulmonary bypass?",
                "options": [
                    {"key": "A", "text": "FiO2 adjustment"},
                    {"key": "B", "text": "Sweep gas flow rate"},
                    {"key": "C", "text": "Arterial line pressure"},
                    {"key": "D", "text": "Venous reservoir level"}
                ],
                "correct_answer": "B",
                "explanation": "Carbon dioxide removal is governed directly by sweep gas flow rate through the membrane oxygenator.",
                "supporting_chunk_id": "test_chunk"
            }
        ]
    })

    monkeypatch.setattr(
        container.answer_generator,
        "_generate_completion",
        MagicMock(return_value=mock_mcq_json)
    )

    payload = {
        "topic": "Oxygenator gas exchange",
        "num_questions": 1,
        "difficulty": "intermediate"
    }
    res = test_client.post("/api/v1/study/mcq", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["topic"] == "Oxygenator gas exchange"
    assert data["total_questions"] == 1
    assert data["questions"][0]["correct_answer"] == "B"
    assert "Sweep gas flow rate" in data["questions"][0]["options"][1]["text"]
    assert len(data["citations"]) > 0


def test_rebuild_index_endpoint(test_client, sample_perfusion_pdf_bytes, auth_headers, admin_auth_headers):
    """Test POST /api/v1/index/rebuild endpoint requires admin privileges."""
    # 1. Unauthenticated request rejected
    res_anon = test_client.post("/api/v1/index/rebuild")
    assert res_anon.status_code == 401

    # 2. Non-admin user rejected
    res_non_admin = test_client.post("/api/v1/index/rebuild", headers=auth_headers)
    assert res_non_admin.status_code == 403

    # Ingest document
    files = [
        ("files", ("perfusion.pdf", sample_perfusion_pdf_bytes, "application/pdf"))
    ]
    res_up = test_client.post("/api/v1/documents/upload", files=files, headers=admin_auth_headers)
    assert res_up.status_code == 200

    # 3. Admin request succeeds
    res = test_client.post("/api/v1/index/rebuild", headers=admin_auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["total_documents"] == 1
    assert data["total_chunks_indexed"] >= 3


@pytest.mark.skipif(
    not os.getenv("GROQ_API_KEY") or os.getenv("GROQ_API_KEY").startswith("gsk_your_groq_api_key"),
    reason="Live GROQ_API_KEY not configured. Set GROQ_API_KEY to run live integration test."
)
def test_live_groq_integration(test_client, sample_perfusion_pdf_bytes):
    """Optional live integration test that runs when a genuine GROQ_API_KEY is supplied."""
    files = [
        ("files", ("perfusion_live.pdf", sample_perfusion_pdf_bytes, "application/pdf"))
    ]
    upload_res = test_client.post("/api/v1/documents/upload", files=files)
    assert upload_res.status_code == 200

    chat_res = test_client.post("/api/v1/chat/ask", json={
        "question": "What is the Activated Clotting Time (ACT) target before initiating cardiopulmonary bypass?",
        "top_k": 3
    })
    assert chat_res.status_code == 200
    chat_data = chat_res.json()
    assert chat_data["grounded"] is True
    assert "400" in chat_data["answer"] or "480" in chat_data["answer"] or "ACT" in chat_data["answer"]


def test_transcribe_audio_endpoint(test_client, monkeypatch):
    """Test POST /api/v1/chat/transcribe endpoint with mocked Groq Whisper."""
    from generation.groq_client import GroqClientWrapper
    monkeypatch.setattr(
        GroqClientWrapper,
        "transcribe_audio",
        lambda self, file_bytes, filename, **kwargs: "What are the priming volume constituents for adult CPB?"
    )

    fake_audio = io.BytesIO(b"RIFF....WAVEfmt....data....fake audio bytes")
    files = {"file": ("recording.webm", fake_audio, "audio/webm")}
    res = test_client.post("/api/v1/chat/transcribe", files=files)
    assert res.status_code == 200
    data = res.json()
    assert data["text"] == "What are the priming volume constituents for adult CPB?"


def test_validation_error_handler_returns_string_detail(test_client):
    """Test that 422 validation errors return human-readable string message and detail."""
    res = test_client.post("/api/v1/chat/ask", json={"question": ""})
    assert res.status_code == 422
    data = res.json()
    assert data["error"] is True
    assert isinstance(data["detail"], str)
    assert isinstance(data["message"], str)
    assert "question" in data["detail"]
    # Verify it does not serialize as '[object Object]' or unhandled list
    assert "[object" not in data["detail"]


def test_chat_payload_sanitizes_null_conv_id_and_history(test_client, monkeypatch):
    """Test that string 'null' conversation_id and weird roles in history are sanitized."""
    from generation.gemini_client import GeminiClientWrapper
    monkeypatch.setattr(
        GeminiClientWrapper,
        "generate_chat_completion",
        lambda self, messages, **kwargs: "Normal perfusion answer."
    )

    payload = {
        "question": "What is prime volume?",
        "conversation_id": "null",
        "conversation_history": [
            {"role": "human", "content": "  hello  "},
            {"role": "unknown", "content": ""}
        ]
    }
    res = test_client.post("/api/v1/chat/ask", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["grounded"] is False
    assert "could not find sufficient" in data["answer"].lower()


