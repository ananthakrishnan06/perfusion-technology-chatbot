import pytest
from schemas.retrieval import RetrievedChunk
from generation.answer_generator import AnswerGenerator


def test_citation_generation_and_deduplication():
    """Verify that citations are extracted directly from retrieved chunks and deduplicated."""
    chunk1 = RetrievedChunk(
        chunk_id="doc1_p15_c0",
        document_id="doc1",
        source="gravlee_perfusion.pdf",
        page=15,
        chunk_index=0,
        text="Arterial line filters remove gaseous microemboli and particulate matter before blood re-enters the patient.",
        score=0.032,
        retrieval_method="hybrid_rrf"
    )

    # Identical chunk retrieved twice (e.g. from different stages)
    chunk2 = RetrievedChunk(
        chunk_id="doc1_p15_c0",
        document_id="doc1",
        source="gravlee_perfusion.pdf",
        page=15,
        chunk_index=0,
        text="Arterial line filters remove gaseous microemboli and particulate matter before blood re-enters the patient.",
        score=0.030,
        retrieval_method="hybrid_rrf"
    )

    chunk3 = RetrievedChunk(
        chunk_id="doc1_p45_c2",
        document_id="doc1",
        source="gravlee_perfusion.pdf",
        page=45,
        chunk_index=2,
        text="Centrifugal pumps do not occlude tubing and will not create excessive pressure if afterload spikes.",
        score=0.025,
        retrieval_method="hybrid_rrf"
    )

    citations = AnswerGenerator.build_citations_from_chunks([chunk1, chunk2, chunk3], max_citations=5)

    # Chunk 1 and Chunk 2 should deduplicate into 1 citation
    assert len(citations) == 2

    # Check 1-based page numbers
    assert citations[0].source == "gravlee_perfusion.pdf"
    assert citations[0].page == 15
    assert citations[0].chunk_id == "doc1_p15_c0"
    assert "Arterial line filters" in citations[0].excerpt

    assert citations[1].source == "gravlee_perfusion.pdf"
    assert citations[1].page == 45
    assert citations[1].chunk_id == "doc1_p45_c2"
    assert "Centrifugal pumps" in citations[1].excerpt


def test_citation_excerpt_formatting():
    """Test that long excerpts are truncated cleanly at sentence boundaries."""
    long_passage = (
        "During cardiopulmonary bypass, hypothermia decreases the systemic metabolic rate of oxygen consumption. "
        "For every ten degrees Celsius drop in core body temperature, metabolic rate decreases by approximately fifty percent. "
        "Alpha-stat and pH-stat are the two principal acid-base management strategies employed during hypothermic bypass. "
        "Additional details regarding rewarming rates must be carefully respected."
    )

    chunk = RetrievedChunk(
        chunk_id="doc_hypo_p8_c1",
        document_id="doc_hypo",
        source="hypothermia.pdf",
        page=8,
        chunk_index=1,
        text=long_passage,
        score=0.02,
        retrieval_method="hybrid_rrf"
    )

    citations = AnswerGenerator.build_citations_from_chunks([chunk])
    assert len(citations) == 1
    excerpt = citations[0].excerpt
    assert len(excerpt) <= 285
    assert "hypothermia decreases" in excerpt

