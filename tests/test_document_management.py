import pytest
from services.document_service import DocumentService


def test_document_ingestion_and_listing(temp_test_env, sample_perfusion_pdf_bytes):
    """Test full document ingestion, indexing, and listing."""
    container = temp_test_env["container"]
    doc_service: DocumentService = container.document_service

    # Ingest document
    result = doc_service.process_pdf_file(sample_perfusion_pdf_bytes, "cardiac_perfusion.pdf")

    assert result.processing_status == "indexed"
    assert result.original_filename == "cardiac_perfusion.pdf"
    assert result.page_count == 3
    assert result.chunk_count >= 3
    assert result.document_id != "unassigned"

    doc_id = result.document_id

    # Verify listing
    list_res = doc_service.list_documents()
    assert list_res.total_documents == 1
    assert list_res.documents[0].document_id == doc_id
    assert list_res.documents[0].filename == "cardiac_perfusion.pdf"

    # Verify details
    detail_res = doc_service.get_document(doc_id)
    assert detail_res is not None
    assert detail_res.document.document_id == doc_id
    assert len(detail_res.sample_chunks) > 0


def test_duplicate_document_prevention(temp_test_env, sample_perfusion_pdf_bytes):
    """Test that ingesting the identical PDF twice returns already_indexed status without duplicate chunks."""
    container = temp_test_env["container"]
    doc_service: DocumentService = container.document_service

    # First ingestion
    res1 = doc_service.process_pdf_file(sample_perfusion_pdf_bytes, "file1.pdf")
    assert res1.processing_status == "indexed"

    # Second ingestion of exact same content
    res2 = doc_service.process_pdf_file(sample_perfusion_pdf_bytes, "file1_duplicate.pdf")
    assert res2.processing_status == "already_indexed"
    assert res2.document_id == res1.document_id

    # Verify only 1 document is in metadata store
    list_res = doc_service.list_documents()
    assert list_res.total_documents == 1


def test_document_deletion_and_search_exclusion(temp_test_env, sample_perfusion_pdf_bytes):
    """Test deleting a document ensures all its passages are excluded from subsequent searches."""
    container = temp_test_env["container"]
    doc_service: DocumentService = container.document_service
    retriever = container.hybrid_retriever

    # Ingest document
    res = doc_service.process_pdf_file(sample_perfusion_pdf_bytes, "deleteme.pdf")
    doc_id = res.document_id

    # Verify search returns results before deletion
    before_search = retriever.retrieve(query="heparin and ACT monitoring", top_k=3)
    assert len(before_search) > 0

    # Delete document
    deleted = doc_service.delete_document(doc_id)
    assert deleted is True

    # Verify document no longer exists
    assert doc_service.get_document(doc_id) is None
    assert doc_service.list_documents().total_documents == 0

    # Verify search returns NO results after deletion
    after_search = retriever.retrieve(query="heparin and ACT monitoring", top_k=3)
    assert len(after_search) == 0


def test_index_rebuild(temp_test_env, sample_perfusion_pdf_bytes):
    """Test manual index rebuild operation."""
    container = temp_test_env["container"]
    doc_service: DocumentService = container.document_service

    doc_service.process_pdf_file(sample_perfusion_pdf_bytes, "textbook.pdf")
    rebuild_res = doc_service.rebuild_indices()

    assert rebuild_res["status"] == "success"
    assert rebuild_res["total_documents"] == 1
    assert rebuild_res["total_chunks_indexed"] >= 3

