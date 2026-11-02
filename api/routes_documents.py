from typing import List
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from config import settings
from schemas.auth import UserProfile
from schemas.document import (
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentUploadBatchResponse,
)
from services.document_service import DocumentService
from api.dependencies import get_document_service, get_current_user

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.post(
    "/upload",
    response_model=DocumentUploadBatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload and process one or more PDF documents"
)
async def upload_documents(
    files: List[UploadFile] = File(..., description="One or more PDF files to ingest"),
    current_user: UserProfile = Depends(get_current_user),
    doc_service: DocumentService = Depends(get_document_service)
):
    """
    Ingest PDF documents into the PerfusionGPT knowledge base.
    Requires verified user authentication.
    Validates file extensions, size incrementally, structure, extracts text with PyMuPDF,
    performs structure-aware chunking, generates embeddings, and indexes in FAISS and BM25.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files uploaded. Please provide at least one PDF file."
        )

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    prepared_files = []
    for f in files:
        filename = f.filename or "unknown.pdf"
        # Validate upload size incrementally in chunks before buffering entire payload in RAM
        total_read = 0
        chunks = []
        while True:
            chunk = await f.read(64 * 1024)
            if not chunk:
                break
            total_read += len(chunk)
            if total_read > max_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File '{filename}' exceeds maximum allowed upload size of {settings.MAX_UPLOAD_SIZE_MB} MB."
                )
            chunks.append(chunk)

        file_bytes = b"".join(chunks)
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
def list_documents(
    current_user: UserProfile = Depends(get_current_user),
    doc_service: DocumentService = Depends(get_document_service)
):
    """
    Retrieve all registered documents, their identifiers, filenames,
    page counts, chunk counts, and processing statuses.
    Requires verified user authentication.
    """
    return doc_service.list_documents()


@router.get(
    "/{document_id}",
    response_model=DocumentDetailResponse,
    summary="Get document details and sample passages"
)
def get_document(
    document_id: str,
    current_user: UserProfile = Depends(get_current_user),
    doc_service: DocumentService = Depends(get_document_service)
):
    """
    Retrieve metadata, page counts, OCR flags, and sample chunks for a specific document.
    Requires verified user authentication.
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
    current_user: UserProfile = Depends(get_current_user),
    doc_service: DocumentService = Depends(get_document_service)
):
    """
    Remove a document from the active knowledge base, delete its stored file,
    and rebuild vector and keyword indices to ensure its passages are completely excluded.
    Requires verified user authentication.
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

