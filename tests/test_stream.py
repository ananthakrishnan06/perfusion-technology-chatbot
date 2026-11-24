import json
from unittest.mock import MagicMock
import pytest


def test_short_streamed_answer_does_not_trigger_sync_fallback(test_client, monkeypatch):
    from api.dependencies import get_container
    generator = get_container().answer_generator
    monkeypatch.setattr(generator, "stream_answer", lambda **kwargs: iter(["ECMO supports gas exchange."]))
    fallback = MagicMock(side_effect=AssertionError("Short answers should only be generated once"))
    monkeypatch.setattr(generator, "generate_answer", fallback)
    response = test_client.post("/api/v1/chat/stream", json={"question": "What is ECMO?"})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "done"
    assert events[-1]["answer"] == "ECMO supports gas exchange."
    fallback.assert_not_called()


def test_chat_stream_endpoint(test_client, sample_perfusion_pdf_bytes, admin_auth_headers, monkeypatch):
    """Test POST /api/v1/chat/stream returns valid Server-Sent Events (SSE)."""
    # 1. Ingest document
    files = [
        ("files", ("perfusion_stream.pdf", sample_perfusion_pdf_bytes, "application/pdf"))
    ]
    test_client.post("/api/v1/documents/upload", files=files, headers=admin_auth_headers)

    # 2. Mock streaming generator
    from api.dependencies import get_container
    container = get_container()

    def mock_stream(*args, **kwargs):
        yield "• **Point 1**: "
        yield "Arterial line filters remove gaseous microemboli.\n"
        yield "• **Point 2**: "
        yield "Normal ACT should exceed 480 seconds."

    monkeypatch.setattr(
        container.answer_generator,
        "stream_answer",
        mock_stream
    )

    # 3. Request stream
    payload = {
        "question": "What are the essential safety checks in CPB for 3 marks?",
        "top_k": 3
    }
    res = test_client.post("/api/v1/chat/stream", json=payload)
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]

    body = res.text
    assert "data:" in body
    assert "Point 1" in body
    assert "Point 2" in body
    assert '"type": "done"' in body




def test_stream_retrieval_failure_is_a_safe_error(test_client, monkeypatch):
    from api.dependencies import get_container
    service = get_container().chat_service
    monkeypatch.setattr(service.hybrid_retriever, "retrieve", MagicMock(side_effect=RuntimeError("private-provider-detail")))
    response = test_client.post("/api/v1/chat/stream", json={"question": "Explain a bypass circuit"})
    assert response.status_code == 200
    assert "private-provider-detail" not in response.text
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "error"


def test_stream_insufficient_evidence_has_no_citations(test_client, monkeypatch, sample_perfusion_pdf_bytes, admin_auth_headers):
    from api.dependencies import get_container
    from generation.answer_generator import INSUFFICIENT_EVIDENCE_PHRASE
    response = test_client.post("/api/v1/documents/upload", files=[("files", ("manual.pdf", sample_perfusion_pdf_bytes, "application/pdf"))], headers=admin_auth_headers)
    assert response.status_code == 200
    monkeypatch.setattr(get_container().answer_generator, "stream_answer", lambda **kwargs: iter([INSUFFICIENT_EVIDENCE_PHRASE]))
    response = test_client.post("/api/v1/chat/stream", json={"question": "Explain an oxygenator"})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    done = events[-1]
    assert done["type"] == "done"
    assert done["grounded"] is False
    assert done["insufficient_evidence"] is True
    assert done["citations"] == []



@pytest.mark.parametrize("ownership,expected", [("not_found", 404), ("db_unavailable", 503), ("error", 503)])
@pytest.mark.parametrize("route", ["ask", "stream"])
def test_chat_rejects_unverifiable_conversation(test_client, monkeypatch, auth_headers, ownership, expected, route):
    from api.dependencies import get_container
    service = get_container().chat_service
    monkeypatch.setattr(service.conversation_service, "check_conversation_ownership", lambda *args: ownership)
    response = test_client.post("/api/v1/chat/" + route, json={"question": "Explain ECMO", "conversation_id": "missing"}, headers=auth_headers)
    assert response.status_code == expected
