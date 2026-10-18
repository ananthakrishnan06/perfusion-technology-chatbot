import json
from unittest.mock import MagicMock
import pytest


def test_chat_stream_endpoint(test_client, sample_perfusion_pdf_bytes, monkeypatch):
    """Test POST /api/v1/chat/stream returns valid Server-Sent Events (SSE)."""
    # 1. Ingest document
    files = [
        ("files", ("perfusion_stream.pdf", sample_perfusion_pdf_bytes, "application/pdf"))
    ]
    test_client.post("/api/v1/documents/upload", files=files)

    # 2. Mock Groq streaming generator
    from api.dependencies import get_container
    container = get_container()

    def mock_stream(*args, **kwargs):
        yield "• **Point 1**: "
        yield "Arterial line filters remove gaseous microemboli.\n"
        yield "• **Point 2**: "
        yield "Normal ACT should exceed 480 seconds."

    monkeypatch.setattr(
        container.answer_generator.groq_client,
        "stream_chat_completion",
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

