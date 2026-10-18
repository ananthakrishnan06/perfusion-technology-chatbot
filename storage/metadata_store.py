import json
import logging
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional, Set
from config import settings
from schemas.document import ChunkMetadata, DocumentMetadata

logger = logging.getLogger(__name__)


class MetadataStore:
    """
    Thread-safe, structured JSON storage for document and chunk metadata.
    Does not use pickle or unsafe deserialization.
    Performs atomic writes to disk to prevent data corruption.
    """

    def __init__(self, metadata_path: Path = settings.METADATA_FILE):
        self.metadata_path = metadata_path
        self._lock = threading.RLock()
        self.documents: Dict[str, DocumentMetadata] = {}
        self.chunks: Dict[str, ChunkMetadata] = {}
        self.hash_to_doc_id: Dict[str, str] = {}
        self.doc_to_chunk_ids: Dict[str, List[str]] = {}
        self.load_from_disk()

    def add_document(self, doc_meta: DocumentMetadata, chunks: List[ChunkMetadata]) -> None:
        """Add or update a document and its associated chunks, then persist."""
        with self._lock:
            # If replacing an existing document with the same ID, clean up old chunk references
            if doc_meta.document_id in self.documents:
                old_chunk_ids = self.doc_to_chunk_ids.get(doc_meta.document_id, [])
                for cid in old_chunk_ids:
                    self.chunks.pop(cid, None)

            self.documents[doc_meta.document_id] = doc_meta
            self.hash_to_doc_id[doc_meta.file_hash] = doc_meta.document_id

            chunk_ids = []
            for chunk in chunks:
                self.chunks[chunk.chunk_id] = chunk
                chunk_ids.append(chunk.chunk_id)

            self.doc_to_chunk_ids[doc_meta.document_id] = chunk_ids
            self.save_to_disk()

    def get_document(self, doc_id: str) -> Optional[DocumentMetadata]:
        with self._lock:
            return self.documents.get(doc_id)

    def get_document_by_hash(self, file_hash: str) -> Optional[DocumentMetadata]:
        with self._lock:
            doc_id = self.hash_to_doc_id.get(file_hash)
            if doc_id:
                return self.documents.get(doc_id)
            return None

    def list_documents(self) -> List[DocumentMetadata]:
        with self._lock:
            return list(self.documents.values())

    def get_chunk(self, chunk_id: str) -> Optional[ChunkMetadata]:
        with self._lock:
            return self.chunks.get(chunk_id)

    def get_chunks(self, chunk_ids: List[str]) -> List[ChunkMetadata]:
        with self._lock:
            return [self.chunks[cid] for cid in chunk_ids if cid in self.chunks]

    def get_all_chunks(self, document_ids: Optional[List[str]] = None) -> List[ChunkMetadata]:
        with self._lock:
            if not document_ids:
                return list(self.chunks.values())
            
            doc_id_set = set(document_ids)
            result = []
            for doc_id in doc_id_set:
                for chunk_id in self.doc_to_chunk_ids.get(doc_id, []):
                    if chunk_id in self.chunks:
                        result.append(self.chunks[chunk_id])
            return result

    def delete_document(self, doc_id: str) -> List[str]:
        """
        Delete document and all its chunks.
        Returns list of deleted chunk IDs.
        """
        with self._lock:
            if doc_id not in self.documents:
                return []

            doc = self.documents.pop(doc_id)
            self.hash_to_doc_id.pop(doc.file_hash, None)

            chunk_ids = self.doc_to_chunk_ids.pop(doc_id, [])
            for cid in chunk_ids:
                self.chunks.pop(cid, None)

            self.save_to_disk()
            return chunk_ids

    def clear(self) -> None:
        """Clear all stored metadata."""
        with self._lock:
            self.documents.clear()
            self.chunks.clear()
            self.hash_to_doc_id.clear()
            self.doc_to_chunk_ids.clear()
            self.save_to_disk()

    def save_to_disk(self) -> None:
        """
        Safely write metadata to disk using an atomic temporary file rename.
        """
        with self._lock:
            self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.metadata_path.with_suffix(".tmp")

            data = {
                "version": settings.APP_VERSION,
                "documents": {k: v.model_dump() for k, v in self.documents.items()},
                "chunks": {k: v.model_dump() for k, v in self.chunks.items()}
            }

            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                # Atomic replace
                if tmp_path.exists():
                    os.replace(tmp_path, self.metadata_path)
            except Exception as e:
                logger.error(f"Failed to persist metadata to {self.metadata_path}: {e}")
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
                raise

    def load_from_disk(self) -> None:
        """Load and validate persisted metadata from disk."""
        with self._lock:
            if not self.metadata_path.exists():
                return

            try:
                with open(self.metadata_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                self.documents.clear()
                self.chunks.clear()
                self.hash_to_doc_id.clear()
                self.doc_to_chunk_ids.clear()

                raw_docs = data.get("documents", {})
                for doc_id, doc_dict in raw_docs.items():
                    try:
                        doc_obj = DocumentMetadata.model_validate(doc_dict)
                        self.documents[doc_id] = doc_obj
                        self.hash_to_doc_id[doc_obj.file_hash] = doc_id
                        self.doc_to_chunk_ids[doc_id] = []
                    except Exception as err:
                        logger.warning(f"Skipping corrupted document entry {doc_id}: {err}")

                raw_chunks = data.get("chunks", {})
                for chunk_id, chunk_dict in raw_chunks.items():
                    try:
                        chunk_obj = ChunkMetadata.model_validate(chunk_dict)
                        self.chunks[chunk_id] = chunk_obj
                        if chunk_obj.document_id in self.doc_to_chunk_ids:
                            self.doc_to_chunk_ids[chunk_obj.document_id].append(chunk_id)
                    except Exception as err:
                        logger.warning(f"Skipping corrupted chunk entry {chunk_id}: {err}")

                logger.info(
                    f"Successfully loaded {len(self.documents)} documents and {len(self.chunks)} chunks from {self.metadata_path}"
                )

            except Exception as e:
                logger.error(f"Failed to load metadata from {self.metadata_path}: {e}")

