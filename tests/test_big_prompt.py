import pytest
from schemas.chat import ChatRequest, ChatMessage, MCQRequest
from generation.answer_generator import AnswerGenerator
from generation.prompts import build_chat_messages
from schemas.retrieval import RetrievedChunk


def test_schema_allows_large_prompt():
    """Verify ChatRequest and ChatMessage accept prompts up to 30,000 characters."""
    large_question = "Explain in detail the pathophysiology and management of cardiopulmonary bypass complications. " * 100
    assert len(large_question) > 9000

    req = ChatRequest(question=large_question)
    assert req.question == large_question

    large_content = "Comprehensive turn history content with detailed physiological data. " * 300
    msg = ChatMessage(role="user", content=large_content)
    assert len(msg.content) > 15000

    mcq_req = MCQRequest(topic="Centrifugal pumps vs roller pumps: detailed comparative biophysical analysis " * 10)
    assert len(mcq_req.topic) > 500


def test_contextualize_query_preserves_comprehensive_prompt():
    """Verify that comprehensive prompts with 15+ words are not destroyed into 8-word summaries."""
    gen = AnswerGenerator()
    long_case_prompt = (
        "A 68-year-old male undergoes coronary artery bypass grafting under hypothermic CPB. "
        "During this procedure, venous reservoir levels precipitously decline and mean arterial pressure drops to 42 mmHg. "
        "Explain the systematic troubleshooting steps, cannula repositioning guidelines, and volume resuscitation protocols."
    )
    history = [
        ChatMessage(role="user", content="What is CPB priming?"),
        ChatMessage(role="assistant", content="Priming is the fluid solution used to fill the circuit.")
    ]

    result = gen.contextualize_query(question=long_case_prompt, conversation_history=history)
    assert result == long_case_prompt, "Comprehensive prompts must be preserved verbatim for multi-topic hybrid retrieval."


def test_build_chat_messages_triggers_comprehensive_directive():
    """Verify that large multi-part prompts trigger the comprehensive directive in build_chat_messages."""
    long_prompt = (
        "Discuss the biophysical principles of membrane oxygenators, detailing hollow-fiber vs flat-sheet geometry, "
        "gas transfer dynamics (DO2 and VCO2 equations), prime volume impact, and microemboli entrapment mechanisms across circuit configurations."
    )
    chunks = [
        RetrievedChunk(
            chunk_id="chunk_1",
            document_id="doc_1",
            chunk_index=0,
            source="Sunith Ghosh CPB.pdf",
            page=45,
            text="Membrane oxygenators utilize microporous polypropylene hollow fibers to ensure efficient gas exchange.",
            score=0.92,
            retrieval_method="hybrid"
        )
    ]

    messages = build_chat_messages(question=long_prompt, retrieved_chunks=chunks)
    assert len(messages) == 2
    user_content = messages[1]["content"]
    assert "COMPREHENSIVE MULTI-PART / CLINICAL SCENARIO RESPONSE" in user_content
    assert "Address EVERY single question" in user_content
