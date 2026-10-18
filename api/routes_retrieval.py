from fastapi import APIRouter, Depends, HTTPException, status
from schemas.retrieval import RetrievalQuery, RetrievalResponse
from services.retrieval_service import RetrievalService
from services.document_service import DocumentService
from api.dependencies import get_retrieval_service, get_document_service

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
    doc_service: DocumentService = Depends(get_document_service)
):
    """
    Rebuild FAISS dense vector index and BM25 sparse keyword index from all
    currently indexed document chunks.
    """
    try:
        result = doc_service.rebuild_indices()
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Index rebuild failed: {str(e)}"
        )

