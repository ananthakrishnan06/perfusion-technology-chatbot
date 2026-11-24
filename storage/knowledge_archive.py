"""Durable storage for administrator changes to the local FAISS knowledge base."""
from sqlalchemy.orm import defer

from schemas.document import ChunkMetadata, DocumentMetadata
from storage.admin_models import KnowledgeDocument
from storage.db import get_session_factory


def archive_document(db, service, doc_id):
    doc = service.metadata_store.get_document(doc_id)
    if not doc:
        return
    row = db.get(KnowledgeDocument, doc_id)
    if not row:
        row = KnowledgeDocument(id=doc_id, deleted=False)
        db.add(row)
    row.metadata_json = doc.model_dump()
    row.chunks = [chunk.model_dump() for chunk in service.metadata_store.get_all_chunks([doc_id])]
    path = service.documents_dir / (doc_id + ".pdf")
    if row.pdf is None and path.is_file():
        row.pdf = path.read_bytes()


def tombstone(db, doc_id):
    row = db.get(KnowledgeDocument, doc_id)
    if not row:
        row = KnowledgeDocument(id=doc_id)
        db.add(row)
    row.deleted = True
    row.pdf = None
    row.chunks = None
    row.metadata_json = None


def restore_library(service):
    factory = get_session_factory()
    if not factory:
        return
    changed = False
    with factory() as db:
        for row in db.query(KnowledgeDocument).options(defer(KnowledgeDocument.pdf), defer(KnowledgeDocument.chunks)).yield_per(10):
            existing = service.metadata_store.get_document(row.id)
            path = service.documents_dir / (row.id + ".pdf")
            if row.deleted:
                if existing:
                    service.metadata_store.delete_document(row.id)
                    path.unlink(missing_ok=True)
                    changed = True
                continue
            if not existing or existing.model_dump() != row.metadata_json:
                doc = DocumentMetadata.model_validate(row.metadata_json)
                service.metadata_store.add_document(doc, [ChunkMetadata.model_validate(c) for c in row.chunks])
                changed = True
            if not path.exists() and row.pdf:
                service.documents_dir.mkdir(parents=True, exist_ok=True)
                path.write_bytes(row.pdf)
    if changed:
        service.rebuild_indices()
