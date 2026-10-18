import logging
from typing import List, Optional
from config import settings
from schemas.retrieval import RetrievalQuery, RetrievalResponse, RetrievedChunk
from retrieval.hybrid_search import HybridRetriever

logger = logging.getLogger(__name__)


class RetrievalService:
    """
    Coordinates search operations across documents without calling an LLM.
    Useful for testing retrieval independently of answer generation.
    """

    def __init__(self, hybrid_retriever: HybridRetriever):
        self.hybrid_retriever = hybrid_retriever

    def search(
        self,
        query: str,
        document_ids: Optional[List[str]] = None,
        top_k: int = settings.TOP_K_FINAL
    ) -> RetrievalResponse:
        """
        Execute hybrid search and return structured retrieved chunks.
        """
        chunks = self.hybrid_retriever.retrieve(
            query=query,
            document_ids=document_ids,
            top_k=top_k
        )

        method = chunks[0].retrieval_method if chunks else "hybrid"

        return RetrievalResponse(
            query=query,
            retrieved_chunks=chunks,
            total_retrieved=len(chunks),
            retrieval_method=method
        )

