from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field


class ChunkMetadata(BaseModel):
    """Metadata representing a single passage chunk from a document."""
    chunk_id: str = Field(..., description="Unique chunk identifier, e.g., {doc_id}_p{page}_c{idx}")
    document_id: str = Field(..., description="Unique document identifier")
    source: str = Field(..., description="Original filename of the PDF")
    page: int = Field(..., ge=1, description="1-based original PDF page number")
    chunk_index: int = Field(..., ge=0, description="Sequential index of the chunk within the document")
    text: str = Field(..., min_length=1, description="Extracted and cleaned passage text")
    char_count: Optional[int] = Field(None, description="Character count of the text")
    estimated_tokens: Optional[int] = Field(None, description="Estimated token count")


class DocumentMetadata(BaseModel):
    """Metadata representing an uploaded and indexed document."""
    document_id: str = Field(..., description="Unique document identifier")
    filename: str = Field(..., description="Original filename")
    file_hash: str = Field(..., description="SHA-256 hash of file content for deduplication")
    file_size_bytes: int = Field(..., ge=0, description="File size in bytes")
    total_pages: int = Field(..., ge=0, description="Total number of pages in the PDF")
    total_chunks: int = Field(..., ge=0, description="Total number of extracted chunks")
    low_text_pages: List[int] = Field(default_factory=list, description="Pages with little or no extractable text")
    ocr_needed: bool = Field(default=False, description="Flag indicating if the document appears to be scanned")
    ocr_warning: Optional[str] = Field(None, description="Human-readable warning regarding OCR requirement")
    uploaded_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO timestamp of upload"
    )
    status: str = Field(default="indexed", description="Processing status: indexed, failed, processing")
    error_message: Optional[str] = Field(None, description="Error details if processing failed")


class DocumentUploadResult(BaseModel):
    """Response returned for a single uploaded document."""
    document_id: str
    original_filename: str
    processing_status: str
    page_count: int
    chunk_count: int
    ocr_warning: Optional[str] = None
    error_details: Optional[str] = None


class DocumentUploadBatchResponse(BaseModel):
    """Response returned for uploading one or multiple documents."""
    results: List[DocumentUploadResult]
    total_uploaded: int
    total_failed: int


class DocumentListResponse(BaseModel):
    """List of all registered documents."""
    documents: List[DocumentMetadata]
    total_documents: int


class DocumentDetailResponse(BaseModel):
    """Detailed document metadata and chunk overview."""
    document: DocumentMetadata
    sample_chunks: List[ChunkMetadata] = Field(default_factory=list)

