import json
from unittest.mock import MagicMock
import pytest
from generation.gemini_client import (
    GeminiClientWrapper,
    GeminiError,
    GeminiConfigurationError,
    GeminiAPIError
)
from generation.groq_client import GroqClientWrapper, GroqError
from generation.answer_generator import AnswerGenerator
from schemas.retrieval import RetrievedChunk


@pytest.fixture
def sample_retrieved_chunk():
    return RetrievedChunk(
        chunk_id="chk_1",
        document_id="doc_1",
        source="principles_cpb.pdf",
        page=4,
        chunk_index=0,
        text="Sweep gas flow rate dictates carbon dioxide clearance across the microporous membrane.",
        score=0.92,
        retrieval_method="hybrid"
    )


def test_gemini_client_wrapper_missing_key():
    """Verify GeminiConfigurationError when no key is supplied."""
    client = GeminiClientWrapper(api_key="")
    with pytest.raises(GeminiConfigurationError):
        client.generate_chat_completion(messages=[{"role": "user", "content": "Hello"}])


def test_gemini_message_conversion():
    """Verify system instructions extraction and role alternation."""
    messages = [
        {"role": "system", "content": "You are a clinical perfusion AI."},
        {"role": "user", "content": "First user query."},
        {"role": "user", "content": "Second user query in same turn."},
        {"role": "assistant", "content": "Clinical assistant reply."},
        {"role": "user", "content": "Final user query."}
    ]

    system_instruction, contents = GeminiClientWrapper._convert_messages(messages)

    assert system_instruction == "You are a clinical perfusion AI."
    # Consecutive user messages should be merged into a single Content with 2 parts
    assert len(contents) == 3
    assert contents[0].role == "user"
    assert len(contents[0].parts) == 2
    assert contents[1].role == "model"
    assert contents[2].role == "user"


def test_answer_generator_uses_gemini_primary(sample_retrieved_chunk):
    """When Gemini is healthy, it is called first and Groq is not invoked."""
    mock_gemini = MagicMock(spec=GeminiClientWrapper)
    mock_gemini.generate_chat_completion.return_value = "Gemini answer on sweep gas regulation."

    mock_groq = MagicMock(spec=GroqClientWrapper)

    gen = AnswerGenerator(
        gemini_client=mock_gemini,
        groq_client=mock_groq,
        primary_provider="gemini"
    )

    response = gen.generate_answer(
        question="How is CO2 cleared during CPB?",
        retrieved_chunks=[sample_retrieved_chunk]
    )

    assert "sweep gas regulation" in response.answer
    assert mock_gemini.generate_chat_completion.called
    assert not mock_groq.generate_chat_completion.called


def test_answer_generator_fallback_to_groq_on_gemini_error(sample_retrieved_chunk):
    """When Gemini raises an error, AnswerGenerator automatically falls back to Groq."""
    mock_gemini = MagicMock(spec=GeminiClientWrapper)
    mock_gemini.generate_chat_completion.side_effect = GeminiAPIError("Gemini rate limit exceeded (429)")

    mock_groq = MagicMock(spec=GroqClientWrapper)
    mock_groq.generate_chat_completion.return_value = "Groq fallback answer on sweep gas."

    gen = AnswerGenerator(
        gemini_client=mock_gemini,
        groq_client=mock_groq,
        primary_provider="gemini"
    )

    response = gen.generate_answer(
        question="How is CO2 cleared?",
        retrieved_chunks=[sample_retrieved_chunk]
    )

    assert "Groq fallback answer" in response.answer
    assert mock_gemini.generate_chat_completion.called
    assert mock_groq.generate_chat_completion.called


def test_stream_answer_uses_gemini_primary(sample_retrieved_chunk):
    """When Gemini streaming is healthy, it streams tokens without invoking Groq."""
    mock_gemini = MagicMock(spec=GeminiClientWrapper)

    def mock_gemini_stream(*args, **kwargs):
        yield "Gemini token 1 "
        yield "Gemini token 2"

    mock_gemini.stream_chat_completion = mock_gemini_stream

    mock_groq = MagicMock(spec=GroqClientWrapper)
    mock_groq.stream_chat_completion = MagicMock()

    gen = AnswerGenerator(
        gemini_client=mock_gemini,
        groq_client=mock_groq,
        primary_provider="gemini"
    )

    tokens = list(gen.stream_answer(
        question="Explain sweep gas.",
        retrieved_chunks=[sample_retrieved_chunk]
    ))

    assert tokens == ["Gemini token 1 ", "Gemini token 2"]
    assert not mock_groq.stream_chat_completion.called


def test_stream_answer_fallback_to_groq_on_gemini_failure(sample_retrieved_chunk):
    """When Gemini streaming fails before yielding tokens, it transparently streams from Groq."""
    mock_gemini = MagicMock(spec=GeminiClientWrapper)

    def failing_gemini_stream(*args, **kwargs):
        raise GeminiAPIError("Gemini streaming quota exhausted")
        yield  # unreachable generator

    mock_gemini.stream_chat_completion = failing_gemini_stream

    mock_groq = MagicMock(spec=GroqClientWrapper)

    def mock_groq_stream(*args, **kwargs):
        yield "Groq token 1 "
        yield "Groq token 2"

    mock_groq.stream_chat_completion = mock_groq_stream

    gen = AnswerGenerator(
        gemini_client=mock_gemini,
        groq_client=mock_groq,
        primary_provider="gemini"
    )

    tokens = list(gen.stream_answer(
        question="Explain sweep gas.",
        retrieved_chunks=[sample_retrieved_chunk]
    ))

    assert tokens == ["Groq token 1 ", "Groq token 2"]


def test_mcq_generation_fallback_to_groq(sample_retrieved_chunk):
    """MCQ generation fails over from Gemini to Groq cleanly."""
    mock_gemini = MagicMock(spec=GeminiClientWrapper)
    mock_gemini.generate_chat_completion.side_effect = GeminiAPIError("Quota exceeded")

    mock_mcq_json = json.dumps({
        "questions": [
            {
                "question": "What governs CO2 clearance during CPB?",
                "options": [
                    {"key": "A", "text": "Sweep gas flow rate"},
                    {"key": "B", "text": "FiO2 adjustment"},
                    {"key": "C", "text": "Arterial cannula size"},
                    {"key": "D", "text": "Pump occlusion"}
                ],
                "correct_answer": "A",
                "explanation": "Sweep gas flow rate governs CO2 clearance.",
                "supporting_chunk_id": "chk_1"
            }
        ]
    })
    mock_groq = MagicMock(spec=GroqClientWrapper)
    mock_groq.generate_chat_completion.return_value = mock_mcq_json

    gen = AnswerGenerator(
        gemini_client=mock_gemini,
        groq_client=mock_groq,
        primary_provider="gemini"
    )

    mcq_res = gen.generate_mcqs(
        topic="Gas exchange",
        num_questions=1,
        difficulty="intermediate",
        retrieved_chunks=[sample_retrieved_chunk]
    )

    assert mcq_res.total_questions == 1
    assert mcq_res.questions[0].correct_answer == "A"
    assert "Sweep gas" in mcq_res.questions[0].options[0].text
