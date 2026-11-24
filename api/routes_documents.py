import re
from typing import List

from api.pdf_preview import render_pdf_page
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from config import settings
from starlette.concurrency import run_in_threadpool
from storage.admin_state import audit, read_options
from storage.db import get_db
from storage.knowledge_archive import archive_document, tombstone
from schemas.auth import UserProfile
from schemas.document import (
    DocumentDetailResponse,
    LibraryDocument,
    LibraryResponse,
    DocumentUploadBatchResponse,
)
from services.document_service import DocumentService
from api.dependencies import get_document_service, get_current_user

from api.routes_auth import require_admin

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.post(
    "/upload",
    response_model=DocumentUploadBatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload and process one or more PDF documents"
)
async def upload_documents(
    files: List[UploadFile] = File(..., description="One or more PDF files to ingest"),
    current_user: UserProfile = Depends(require_admin),
    doc_service: DocumentService = Depends(get_document_service),
    db=Depends(get_db),
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

    max_bytes = min(read_options().get("max_pdf_mb", settings.MAX_UPLOAD_SIZE_MB), settings.MAX_UPLOAD_SIZE_MB) * 1024 * 1024
    if len(files) > 10:
        raise HTTPException(413, "Upload at most 10 documents at a time.")
    batch_bytes = 0
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
            batch_bytes += len(chunk)
            if batch_bytes > max_bytes:
                raise HTTPException(413, "The upload exceeds the maximum batch size.")
            chunks.append(chunk)

        file_bytes = b"".join(chunks)
        prepared_files.append((file_bytes, filename))

    batch_response = await run_in_threadpool(doc_service.process_batch, prepared_files)
    if db is not None:
        for result in batch_response.results:
            if result.processing_status == "indexed":
                archive_document(db, doc_service, result.document_id)
                audit(db, current_user.sub, "pdf_uploaded", result.document_id)
            elif result.processing_status == "failed":
                audit(db, current_user.sub, "pdf_index_failed")
        db.commit()

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
    response_model=LibraryResponse,
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
    documents = [
        LibraryDocument(**doc.model_dump(), preview_available=library_pdf_path(doc_service, doc.document_id) is not None)
        for doc in doc_service.metadata_store.list_documents()
        if doc.status == "indexed"
    ]
    documents.sort(key=lambda doc: doc.uploaded_at, reverse=True)
    return LibraryResponse(documents=documents, total_documents=len(documents))


def library_pdf_path(service, document_id):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", document_id):
        return None
    path = service.documents_dir / (document_id + ".pdf")
    return path if path.is_file() else None


@router.get("/{document_id}/preview", summary="Read a page from a published PDF")
def preview_document(
    document_id: str,
    page: int = 1,
    current_user: UserProfile = Depends(get_current_user),
    doc_service: DocumentService = Depends(get_document_service),
):
    document = doc_service.metadata_store.get_document(document_id)
    path = library_pdf_path(doc_service, document_id)
    if not document or document.status != "indexed" or not path:
        raise HTTPException(404, "This PDF is unavailable.")
    return render_pdf_page(path, page)


@router.get("/{document_id}/download", summary="Download a published PDF")
def download_document(
    document_id: str,
    current_user: UserProfile = Depends(get_current_user),
    doc_service: DocumentService = Depends(get_document_service),
):
    document = doc_service.metadata_store.get_document(document_id)
    path = library_pdf_path(doc_service, document_id)
    if not document or document.status != "indexed" or not path:
        raise HTTPException(404, "This PDF is unavailable.")
    return FileResponse(path, media_type="application/pdf", filename=document.filename,
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


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
    if not doc_detail or (doc_detail.document.status != "indexed" and current_user.role != "admin"):
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
    current_user: UserProfile = Depends(require_admin),
    doc_service: DocumentService = Depends(get_document_service),
    db=Depends(get_db),
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
    if db is not None:
        tombstone(db, document_id)
        audit(db, current_user.sub, "pdf_deleted", document_id)
        db.commit()
    return {
        "status": "success",
        "message": f"Document '{document_id}' successfully removed from knowledge base and indices.",
        "document_id": document_id
    }

