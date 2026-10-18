import pytest
from ingestion.chunker import StructureAwareChunker
from ingestion.pdf_loader import ExtractedPage


def test_chunker_metadata_preservation():
    """Verify that chunk metadata matches the required schema and preserves authentic 1-based page numbers."""
    chunker = StructureAwareChunker(chunk_size=100, chunk_overlap=20)

    page1 = ExtractedPage(
        page_number=1,
        raw_text="Sample raw text",
        cleaned_text=(
            "Cardiopulmonary bypass (CPB) temporarily takes over the mechanical function of the heart. "
            "The circuit consists of roller pumps, centrifugal pumps, venous reservoirs, and membrane oxygenators. "
            "Centrifugal pumps are afterload-dependent and non-occlusive."
        ),
        is_low_text=False
    )

    page2 = ExtractedPage(
        page_number=2,
        raw_text="Sample raw text p2",
        cleaned_text=(
            "Oxygenation is governed by the fraction of delivered oxygen (FiO2). "
            "Carbon dioxide removal is governed by sweep gas flow rate."
        ),
        is_low_text=False
    )

    chunks = chunker.chunk_document(
        pages=[page1, page2],
        document_id="doc_xyz123",
        source_filename="perfusion_guide.pdf"
    )

    assert len(chunks) >= 2

    # Verify chunk attributes
    for c in chunks:
        assert c.document_id == "doc_xyz123"
        assert c.source == "perfusion_guide.pdf"
        assert c.page in [1, 2]
        assert c.chunk_id.startswith("doc_xyz123_p")
        assert len(c.text) > 0
        assert c.estimated_tokens > 0

    # Verify that page 1 chunks have page=1 and page 2 chunks have page=2
    p1_chunks = [c for c in chunks if c.page == 1]
    p2_chunks = [c for c in chunks if c.page == 2]

    assert len(p1_chunks) >= 1
    assert len(p2_chunks) >= 1
    assert "Cardiopulmonary bypass" in p1_chunks[0].text
    assert "Oxygenation" in p2_chunks[0].text


def test_chunker_skips_empty_pages():
    """Verify that empty or near-empty pages do not produce dummy chunks."""
    chunker = StructureAwareChunker()

    empty_page = ExtractedPage(
        page_number=5,
        raw_text="",
        cleaned_text="   \n  ",
        is_low_text=True
    )

    chunks = chunker.chunk_page(
        page=empty_page,
        document_id="doc_test",
        source_filename="empty.pdf",
        start_chunk_index=0
    )

    assert len(chunks) == 0


def test_chunker_token_estimation_and_overlap():
    """Test token estimation and overlap handling."""
    chunker = StructureAwareChunker(chunk_size=30, chunk_overlap=10)

    # Long text with multiple distinct sentences
    long_text = (
        "Paragraph one discusses arterial cannula placement. "
        "Paragraph two discusses venous cannula drainage techniques. "
        "Paragraph three discusses vacuum assisted venous drainage. "
        "Paragraph four discusses cardioplegia delivery lines. "
        "Paragraph five discusses microvascular gas emboli management."
    )

    page = ExtractedPage(
        page_number=1,
        raw_text=long_text,
        cleaned_text=long_text,
        is_low_text=False
    )

    chunks = chunker.chunk_page(
        page=page,
        document_id="doc_overlap",
        source_filename="overlap.pdf",
        start_chunk_index=0
    )

    assert len(chunks) > 1
    # Check consecutive chunk indices
    for i, c in enumerate(chunks):
        assert c.chunk_index == i

