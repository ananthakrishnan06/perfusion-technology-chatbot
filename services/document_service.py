import logging
import os
import uuid
from pathlib import Path
from typing import List, Optional, Tuple
from config import settings
from schemas.document import (
    ChunkMetadata,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentMetadata,
    DocumentUploadBatchResponse,
    DocumentUploadResult,
)
from ingestion.pdf_loader import PDFLoader, PDFProcessingError
from ingestion.chunker import StructureAwareChunker
from storage.metadata_store import MetadataStore
from retrieval.embeddings import EmbeddingManager
from retrieval.vector_store import FAISSVectorStore
from retrieval.keyword_search import BM25KeywordSearch

logger = logging.getLogger(__name__)


class DocumentService:
    """
    Coordinates document ingestion, validation, extraction, chunking,
    indexing in FAISS and BM25, and metadata management.
    """

    def __init__(
        self,
        metadata_store: MetadataStore,
        vector_store: FAISSVectorStore,
        keyword_search: BM25KeywordSearch,
        embedding_manager: Optional[EmbeddingManager] = None,
        chunker: Optional[StructureAwareChunker] = None,
        documents_dir: Optional[Path] = None
    ):
        self.metadata_store = metadata_store
        self.vector_store = vector_store
        self.keyword_search = keyword_search
        self.embedding_manager = embedding_manager or EmbeddingManager()
        self.chunker = chunker or StructureAwareChunker()
        self.documents_dir = documents_dir or settings.DOCUMENTS_DIR

        # Initialize keyword search from loaded metadata on startup
        self._sync_bm25_from_store()

    def _sync_bm25_from_store(self) -> None:
        """Sync the BM25 index with all currently stored chunks."""
        all_chunks = self.metadata_store.get_all_chunks()
        self.keyword_search.index_chunks(all_chunks)

    def process_pdf_file(self, file_bytes: bytes, original_filename: str) -> DocumentUploadResult:
        """
        Process a single PDF file: validate, extract, chunk, embed, index, and store.
        """
        # 1. Extract and validate
        try:
            extracted_pages, summary = PDFLoader.load_and_extract(file_bytes, original_filename)
        except PDFProcessingError as pe:
            return DocumentUploadResult(
                document_id="unassigned",
                original_filename=original_filename,
                processing_status="failed",
                page_count=0,
                chunk_count=0,
                error_details=str(pe)
            )
        except Exception as e:
            return DocumentUploadResult(
                document_id="unassigned",
                original_filename=original_filename,
                processing_status="failed",
                page_count=0,
                chunk_count=0,
                error_details=f"Unexpected extraction failure: {str(e)}"
            )

        file_hash = summary["file_hash"]

        # 2. Check for duplicate document
        existing_doc = self.metadata_store.get_document_by_hash(file_hash)
        if existing_doc:
            return DocumentUploadResult(
                document_id=existing_doc.document_id,
                original_filename=original_filename,
                processing_status="already_indexed",
                page_count=existing_doc.total_pages,
                chunk_count=existing_doc.total_chunks,
                ocr_warning=existing_doc.ocr_warning,
                error_details="Document with identical content hash is already indexed."
            )

        # 3. Generate unique document ID and save raw file safely using internal ID
        document_id = str(uuid.uuid4())
        safe_file_path = self.documents_dir / f"{document_id}.pdf"
        try:
            with open(safe_file_path, "wb") as f:
                f.write(file_bytes)
        except Exception as e:
            logger.error(f"Failed to save document to {safe_file_path}: {e}")
            return DocumentUploadResult(
                document_id=document_id,
                original_filename=original_filename,
                processing_status="failed",
                page_count=summary["total_pages"],
                chunk_count=0,
                error_details=f"Failed to store file on disk: {str(e)}"
            )

        # 4. Chunk document
        chunks: List[ChunkMetadata] = self.chunker.chunk_document(
            pages=extracted_pages,
            document_id=document_id,
            source_filename=original_filename
        )

        # 5. Embed and Index in FAISS (if chunks exist)
        if chunks:
            try:
                texts = [c.text for c in chunks]
                chunk_ids = [c.chunk_id for c in chunks]
                embeddings = self.embedding_manager.embed_texts(texts)
                self.vector_store.add_vectors(chunk_ids, embeddings)
            except Exception as e:
                logger.error(f"Failed to embed and index chunks for {original_filename}: {e}")
                # Clean up disk file
                if safe_file_path.exists():
                    safe_file_path.unlink()
                return DocumentUploadResult(
                    document_id=document_id,
                    original_filename=original_filename,
                    processing_status="failed",
                    page_count=summary["total_pages"],
                    chunk_count=0,
                    error_details=f"Embedding or vector indexing failed: {str(e)}"
                )

        # 6. Store metadata
        doc_metadata = DocumentMetadata(
            document_id=document_id,
            filename=original_filename,
            file_hash=file_hash,
            file_size_bytes=summary["file_size_bytes"],
            total_pages=summary["total_pages"],
            total_chunks=len(chunks),
            low_text_pages=summary["low_text_pages"],
            ocr_needed=summary["ocr_needed"],
            ocr_warning=summary["ocr_warning"],
            status="indexed"
        )
        self.metadata_store.add_document(doc_metadata, chunks)

        # 7. Update BM25 index with all chunks
        self._sync_bm25_from_store()

        return DocumentUploadResult(
            document_id=document_id,
            original_filename=original_filename,
            processing_status="indexed",
            page_count=summary["total_pages"],
            chunk_count=len(chunks),
            ocr_warning=summary["ocr_warning"]
        )

    def process_batch(self, files: List[Tuple[bytes, str]]) -> DocumentUploadBatchResponse:
        """Process multiple uploaded PDF files."""
        results: List[DocumentUploadResult] = []
        for file_bytes, filename in files:
            res = self.process_pdf_file(file_bytes, filename)
            results.append(res)

        total_failed = sum(1 for r in results if r.processing_status == "failed")
        total_uploaded = len(results) - total_failed

        return DocumentUploadBatchResponse(
            results=results,
            total_uploaded=total_uploaded,
            total_failed=total_failed
        )

    def list_documents(self) -> DocumentListResponse:
        """List all indexed documents."""
        docs = self.metadata_store.list_documents()
        return DocumentListResponse(documents=docs, total_documents=len(docs))

    def get_document(self, document_id: str) -> Optional[DocumentDetailResponse]:
        """Get document details and sample chunks."""
        doc = self.metadata_store.get_document(document_id)
        if not doc:
            return None

        chunks = self.metadata_store.get_all_chunks(document_ids=[document_id])
        return DocumentDetailResponse(
            document=doc,
            sample_chunks=chunks[:10]  # First 10 chunks as sample
        )

    def delete_document(self, document_id: str) -> bool:
        """
        Delete a document, remove its disk file, and rebuild the FAISS & BM25 index
        from remaining documents to guarantee its passages are completely excluded.
        """
        doc = self.metadata_store.get_document(document_id)
        if not doc:
            return False

        # Remove disk file
        file_path = self.documents_dir / f"{document_id}.pdf"
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError as e:
                logger.warning(f"Could not delete physical PDF file {file_path}: {e}")

        # Remove from metadata store
        self.metadata_store.delete_document(document_id)

        # Rebuild FAISS & BM25 indices from remaining chunks
        self.rebuild_indices()
        return True

    def rebuild_indices(self) -> dict:
        """
        Rebuild both FAISS and BM25 indexes from all active chunks currently in metadata store.
        """
        all_chunks = self.metadata_store.get_all_chunks()

        # 1. Rebuild BM25
        self.keyword_search.index_chunks(all_chunks)

        # 2. Rebuild FAISS
        if all_chunks:
            texts = [c.text for c in all_chunks]
            chunk_ids = [c.chunk_id for c in all_chunks]
            embeddings = self.embedding_manager.embed_texts(texts)
            self.vector_store.rebuild(chunk_ids, embeddings)
        else:
            self.vector_store.clear()

        return {
            "status": "success",
            "total_chunks_indexed": len(all_chunks),
            "total_documents": len(self.metadata_store.list_documents())
        }
