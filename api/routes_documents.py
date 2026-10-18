from typing import List
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from schemas.document import (
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentUploadBatchResponse,
)
from services.document_service import DocumentService
from api.dependencies import get_document_service

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.post(
    "/upload",
    response_model=DocumentUploadBatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload and process one or more PDF documents"
)
async def upload_documents(
    files: List[UploadFile] = File(..., description="One or more PDF files to ingest"),
    doc_service: DocumentService = Depends(get_document_service)
):
    """
    Ingest PDF documents into the PerfusionGPT knowledge base.
    
    Validates file extensions, size, structure, extracts text with PyMuPDF,
    performs structure-aware chunking, generates embeddings, and indexes
    in FAISS and BM25.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files uploaded. Please provide at least one PDF file."
        )

    prepared_files = []
    for f in files:
        filename = f.filename or "unknown.pdf"
        file_bytes = await f.read()
        prepared_files.append((file_bytes, filename))

    batch_response = doc_service.process_batch(prepared_files)

    # If all uploaded files failed, return 400 Bad Request with details
    if batch_response.total_failed > 0 and batch_response.total_uploaded == 0:
        error_msgs = [f"{r.original_filename}: {r.error_details}" for r in batch_response.results]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"All uploaded files failed processing: {'; '.join(error_msgs)}"
        )

    return batch_response


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List all indexed documents"
)
def list_documents(doc_service: DocumentService = Depends(get_document_service)):
    """
    Retrieve all registered documents, their identifiers, filenames,
    page counts, chunk counts, and processing statuses.
    """
    return doc_service.list_documents()


@router.get(
    "/{document_id}",
    response_model=DocumentDetailResponse,
    summary="Get document details and sample passages"
)
def get_document(
    document_id: str,
    doc_service: DocumentService = Depends(get_document_service)
):
    """
    Retrieve metadata, page counts, OCR flags, and sample chunks for a specific document.
    """
    doc_detail = doc_service.get_document(document_id)
    if not doc_detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found."
        )
    return doc_detail


@router.delete(
    "/{document_id}",
    summary="Delete a document and exclude all its passages"
)
def delete_document(
    document_id: str,
    doc_service: DocumentService = Depends(get_document_service)
):
    """
    Remove a document from the active knowledge base, delete its stored file,
    and rebuild vector and keyword indices to ensure its passages are completely excluded.
    """
    deleted = doc_service.delete_document(document_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found."
        )
    return {
        "status": "success",
        "message": f"Document '{document_id}' successfully removed from knowledge base and indices.",
        "document_id": document_id
    }

