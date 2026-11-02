import logging
from fastapi import APIRouter, Depends, HTTPException, status
from schemas.retrieval import RetrievalQuery, RetrievalResponse
from schemas.auth import UserProfile
from services.retrieval_service import RetrievalService
from services.document_service import DocumentService
from api.dependencies import get_retrieval_service, get_document_service
from api.routes_auth import get_current_user
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Retrieval & Indexing"])


@router.post(
    "/retrieval/search",
    response_model=RetrievalResponse,
    summary="Search source passages without calling LLM"
)
def search_sources(
    request: RetrievalQuery,
    retrieval_service: RetrievalService = Depends(get_retrieval_service)
):
    """
    Search relevant passages, document filenames, page numbers, and ranking
    metadata without invoking the Groq answer generator.
    
    Enables testing and verifying hybrid retrieval independently of the LLM.
    """
    return retrieval_service.search(
        query=request.query,
        document_ids=request.document_ids,
        top_k=request.top_k
    )


@router.post(
    "/index/rebuild",
    summary="Rebuild vector and keyword indices from stored metadata"
)
def rebuild_index(
    current_user: UserProfile = Depends(get_current_user),
    doc_service: DocumentService = Depends(get_document_service)
):
    """
    Rebuild FAISS dense vector index and BM25 sparse keyword index from all
    currently indexed document chunks. Requires administrative privileges.
    """
    user_email = (current_user.email or "").strip().lower()
    user_role = (current_user.role or "").strip().lower()
    is_admin = user_role in ("admin", "administrator") or user_email in settings.ADMIN_EMAILS
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative privileges required to rebuild indices."
        )

    try:
        result = doc_service.rebuild_indices()
        return result
    except Exception as e:
        logger.error(f"Failed to rebuild knowledge base indices: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to rebuild knowledge base indices. Please contact the administrator."
        )

