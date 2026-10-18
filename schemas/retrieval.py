from typing import List, Optional
from pydantic import BaseModel, Field


class RetrievalQuery(BaseModel):
    """Query parameters for source retrieval."""
    query: str = Field(..., min_length=1, description="Search question or topic")
    document_ids: Optional[List[str]] = Field(
        default=None,
        description="Optional list of document IDs to restrict search to. If omitted or empty, searches all documents."
    )
    top_k: int = Field(default=5, ge=1, le=50, description="Number of passages to retrieve")


class RetrievedChunk(BaseModel):
    """A retrieved passage chunk enriched with scoring and citation information."""
    chunk_id: str
    document_id: str
    source: str
    page: int
    chunk_index: int
    text: str
    score: float = Field(..., description="Combined relevance / RRF score")
    semantic_rank: Optional[int] = Field(None, description="Rank in semantic FAISS retrieval (1-based)")
    bm25_rank: Optional[int] = Field(None, description="Rank in BM25 keyword retrieval (1-based)")
    retrieval_method: str = Field(default="hybrid", description="Retrieval method used")


class RetrievalResponse(BaseModel):
    """Response containing retrieved source passages without LLM generation."""
    query: str
    retrieved_chunks: List[RetrievedChunk]
    total_retrieved: int
    retrieval_method: str = "hybrid"

